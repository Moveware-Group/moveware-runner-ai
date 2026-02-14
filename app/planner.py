from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from datetime import datetime

from .config import settings, PARENT_PLAN_COMMENT_PREFIX
from .llm_openai import OpenAIClient
from .llm_anthropic import AnthropicClient
from .models import JiraIssue
from .db import add_progress_event
from .metrics import ExecutionMetrics, calculate_cost, save_metrics


def _load_project_knowledge() -> str:
    """Load project knowledge file for planner context. Returns empty string if not found."""
    path = os.getenv("PROJECT_KNOWLEDGE_PATH")
    if path:
        p = Path(path)
    else:
        p = Path(__file__).resolve().parent.parent / "config" / "project-knowledge.md"
    if not p.exists():
        return ""
    try:
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        return (
            "\n\n**Project Knowledge (use this context; do not ask questions already answered here):**\n\n"
            f"{content}"
        )
    except Exception:
        return ""


@dataclass
class PlanResult:
    """Result of plan generation."""
    comment: str
    plan_data: Dict[str, Any]


def _system_prompt_claude() -> str:
    base = (
        "You are an expert software architect and technical planner with deep experience in system design. "
        "Your task is to create a comprehensive, well-thought-out implementation plan.\n\n"
        "Break down the Epic into user-facing Stories. Each Story should be a cohesive feature slice "
        "that delivers value independently. Within each Story, define specific technical sub-tasks (commits). "
        "Each Story will have ONE pull request containing all its sub-tasks.\n\n"
        "Think deeply about:\n"
        "- Technical dependencies and ordering\n"
        "- Edge cases and error handling\n"
        "- Security and performance implications\n"
        "- Testing requirements\n"
        "- Database migrations or schema changes\n"
        "- API contract changes\n\n"
        "Only mark a sub-task as 'independent: true' if it's infrastructure/build config that should have its own PR. "
        "The output MUST be valid JSON matching the schema exactly."
    )
    knowledge = _load_project_knowledge()
    if knowledge:
        base += (
            "\n\n**CRITICAL: Project context below.** Use this information. "
            "Do NOT ask questions about infrastructure, cloud provider, deployment, or conventions "
            "that are already stated here. Assume these facts when planning."
        )
        base += knowledge
    return base


def _system_prompt_review() -> str:
    return (
        "You are a senior technical reviewer providing a second opinion on implementation plans. "
        "Your role is to identify potential issues, gaps, and improvements in the proposed plan.\n\n"
        "Review the plan for:\n"
        "- Missing edge cases or error scenarios\n"
        "- Technical risks or dependencies not addressed\n"
        "- Story granularity (too large or too small)\n"
        "- Unclear requirements or assumptions\n"
        "- Testing gaps\n"
        "- Security concerns\n"
        "- Performance bottlenecks\n\n"
        "If the plan is solid, acknowledge it. If you find issues, suggest specific improvements."
    )


def _user_prompt(
    issue: JiraIssue,
    revision_feedback: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
) -> str:
    base = (
        f"Jira issue key: {issue.key}\n"
        f"Summary: {issue.summary}\n\n"
        "Description:\n"
        f"{issue.description}\n"
    )

    if revision_feedback:
        base += (
            "\n\n---\n\n"
            "PREVIOUS CONVERSATION HISTORY (HUMAN ANSWERS):\n"
            "All human comments from the Epic. These contain answers to questions.\n\n"
            f"{revision_feedback}\n\n"
            "---\n\n"
        )

        # Include previous plan's questions so the AI knows what was already asked
        prev_questions = (previous_plan or {}).get("questions") or []
        if prev_questions:
            base += (
                "QUESTIONS ALREADY ASKED AND ANSWERED (DO NOT RE-ASK):\n"
                "The following questions were in the previous plan. The human has answered them "
                "in the conversation above. You MUST NOT include any of these (or semantically equivalent "
                "rephrasing) in your new plan's 'questions' array:\n\n"
            )
            for i, q in enumerate(prev_questions, 1):
                base += f"  {i}. {q}\n"
            base += (
                "\nOnly add genuinely NEW questions that were never asked before and are critical. "
                "If everything is clarified, use \"questions\": [].\n\n"
            )

        base += (
            "IMPORTANT: Review ALL the conversation above before responding.\n"
            "- Do NOT repeat or rephrase questions that have already been answered\n"
            "- Incorporate all human answers into your assumptions and plan\n"
            "- Only ask NEW questions if critical information is still missing\n"
            "- Leave \"questions\" empty when answers have been provided\n\n"
            "Please revise the plan incorporating all the feedback and answers provided."
        )

    return base


PLAN_SCHEMA_HINT = {
    "overview": "Short overview of approach",
    "assumptions": ["..."],
    "risks": ["..."],
    "acceptance_criteria": ["..."],
    "stories": [
        {
            "summary": "User-facing feature story title",
            "description": "What user value this delivers and technical approach",
            "labels": ["optional"],
            "subtasks": [
                {
                    "summary": "Technical task within this story",
                    "description": "Specific implementation detail",
                    "independent": False,  # Set True if needs own PR
                }
            ],
        }
    ],
    "questions": ["Optional questions needing clarification"],
}


def _extract_claude_usage(resp: Dict[str, Any]) -> tuple[int, int, int]:
    """Extract (input_tokens, output_tokens, thinking_tokens) from Anthropic response."""
    usage = resp.get("usage") or {}
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    thinking = int(usage.get("thinking_tokens") or 0)
    return inp, out, thinking


def generate_plan(
    issue: JiraIssue,
    revision_feedback: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
    run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate implementation plan using multi-model approach:
    1. Claude (extended thinking) creates initial plan
    2. ChatGPT reviews and suggests improvements
    3. Claude incorporates feedback if needed
    """
    start_time = datetime.now()
    claude_in, claude_out, claude_thinking = 0, 0, 0
    openai_in, openai_out = 0, 0

    # Step 1: Claude generates initial plan with extended thinking
    if run_id:
        add_progress_event(run_id, "planning", "Using Claude extended thinking to analyze Epic", {})

    claude_client = AnthropicClient(settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL)
    
    schema_prompt = (
        "\n\nReturn JSON only. Do not wrap in markdown.\n"
        "CRITICAL: Must include 'stories' array (NOT 'subtasks' at top level).\n"
        "Each story must have nested 'subtasks' array.\n"
        "Schema example:\n"
        + json.dumps(PLAN_SCHEMA_HINT, indent=2)
    )
    
    user_prompt = _user_prompt(issue, revision_feedback, previous_plan) + schema_prompt
    
    print("Step 1: Generating plan with Claude extended thinking...")
    
    # Try plan generation with retry on JSON parse failure
    max_plan_attempts = 2
    initial_plan = None
    initial_plan_text = ""
    
    for plan_attempt in range(1, max_plan_attempts + 1):
        response = claude_client.messages_create({
            "model": settings.ANTHROPIC_MODEL,
            "system": _system_prompt_claude(),
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": 16000,
            "temperature": 1,
            "thinking": {
                "type": "enabled",
                "budget_tokens": 10000  # Extra thinking for planning!
            }
        })
        inp, out, thinking = _extract_claude_usage(response)
        claude_in += inp
        claude_out += out
        claude_thinking += thinking

        initial_plan_text = claude_client.extract_text(response)
        
        # Parse initial plan
        if run_id:
            add_progress_event(run_id, "planning", f"Parsing Claude's plan (attempt {plan_attempt})", {})
        
        try:
            initial_plan = _parse_plan_json(initial_plan_text)
            print(f"✅ Successfully parsed plan on attempt {plan_attempt}")
            break  # Success!
        except (ValueError, json.JSONDecodeError) as e:
            print(f"❌ Plan parsing failed on attempt {plan_attempt}: {e}")
            
            if plan_attempt < max_plan_attempts:
                # Retry with stricter instructions
                print(f"Retrying plan generation with stricter JSON formatting instructions...")
                user_prompt += (
                    "\n\n**CRITICAL - PREVIOUS RESPONSE HAD INVALID JSON:**\n"
                    f"Error: {str(e)[:200]}\n\n"
                    "**FIX YOUR JSON:**\n"
                    "- Do NOT use trailing commas before } or ]\n"
                    "- USE commas between array elements\n"
                    "- USE double quotes for strings, not single quotes\n"
                    "- Do NOT include comments in JSON\n"
                    "- VALIDATE your JSON is properly formatted\n\n"
                    "Please generate the plan again with VALID JSON."
                )
            else:
                # Final attempt failed
                raise ValueError(
                    f"Could not parse plan JSON after {max_plan_attempts} attempts. "
                    f"Last error: {e}\n"
                    f"Response preview: {initial_plan_text[:500]}"
                )
    
    # Step 2: ChatGPT reviews the plan
    if run_id:
        add_progress_event(run_id, "planning", "ChatGPT reviewing plan for gaps and improvements", {})
    
    print("Step 2: ChatGPT reviewing Claude's plan...")
    openai_client = OpenAIClient(settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    
    review_prompt = (
        f"Review this implementation plan for Epic: {issue.key}\n\n"
        f"**Epic Summary:** {issue.summary}\n\n"
        f"**Epic Description:**\n{issue.description}\n\n"
        f"**Proposed Plan:**\n{json.dumps(initial_plan, indent=2)}\n\n"
        "Provide your review as JSON with:\n"
        "{\n"
        '  "verdict": "approve" or "suggest_improvements",\n'
        '  "strengths": ["what the plan does well"],\n'
        '  "concerns": ["potential issues or gaps"],\n'
        '  "suggestions": ["specific improvements"]\n'
        "}"
    )
    
    review_text, review_usage = openai_client.responses_text_with_usage(
        model=settings.OPENAI_MODEL,
        system=_system_prompt_review(),
        user=review_prompt,
        max_tokens=4000,
        temperature=0.3
    )
    openai_in += int(review_usage.get("input_tokens") or 0)
    openai_out += int(review_usage.get("output_tokens") or 0)

    # Parse review
    review = _parse_plan_json(review_text)
    
    # Step 3: Decide if refinement is needed
    verdict = review.get("verdict", "approve")
    suggestions = review.get("suggestions", [])
    concerns = review.get("concerns", [])
    
    if verdict == "suggest_improvements" and (suggestions or concerns):
        if run_id:
            add_progress_event(run_id, "planning", "Claude incorporating ChatGPT's feedback", {})
        
        print("Step 3: Claude incorporating ChatGPT's suggestions...")
        
        refinement_prompt = (
            f"Your initial plan:\n{json.dumps(initial_plan, indent=2)}\n\n"
            f"**ChatGPT Review Feedback:**\n"
            f"Concerns: {json.dumps(concerns, indent=2)}\n"
            f"Suggestions: {json.dumps(suggestions, indent=2)}\n\n"
            "Please refine the plan to address these concerns and incorporate the suggestions.\n"
            + schema_prompt
        )
        
        refined_response = claude_client.messages_create({
            "model": settings.ANTHROPIC_MODEL,
            "system": _system_prompt_claude(),
            "messages": [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": initial_plan_text},
                {"role": "user", "content": refinement_prompt}
            ],
            "max_tokens": 16000,
            "temperature": 1,
            "thinking": {
                "type": "enabled",
                "budget_tokens": 8000
            }
        })
        inp, out, thinking = _extract_claude_usage(refined_response)
        claude_in += inp
        claude_out += out
        claude_thinking += thinking

        refined_plan_text = claude_client.extract_text(refined_response)
        final_plan = _parse_plan_json(refined_plan_text)
        
        # Add review metadata to plan
        final_plan["_review"] = {
            "chatgpt_verdict": verdict,
            "concerns_addressed": concerns,
            "suggestions_incorporated": suggestions
        }
        
        print("✅ Plan refined based on ChatGPT feedback")
    else:
        final_plan = initial_plan
        print("✅ Plan approved by ChatGPT without changes")
    
    # Validate final plan
    if run_id:
        add_progress_event(run_id, "planning", "Validating final plan structure", {})

    final_plan = _validate_and_fix_plan(final_plan)

    # Save planning metrics so dashboard shows stats (Claude + OpenAI calls)
    total_in = claude_in + openai_in
    total_out = claude_out + openai_out + claude_thinking
    if run_id and (total_in or total_out):
        end_time = datetime.now()
        claude_cost = calculate_cost(
            settings.ANTHROPIC_MODEL, claude_in, claude_out + claude_thinking, 0
        )
        openai_cost = calculate_cost(settings.OPENAI_MODEL, openai_in, openai_out, 0)
        plan_metrics = ExecutionMetrics(
            run_id=run_id,
            issue_key=issue.key,
            issue_type="epic",
            start_time=start_time,
            end_time=end_time,
            duration_seconds=(end_time - start_time).total_seconds(),
            success=True,
            status="completed",
            model_used=f"{settings.ANTHROPIC_MODEL}+{settings.OPENAI_MODEL}",
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            thinking_tokens=claude_thinking,
            estimated_cost=claude_cost + openai_cost,
            metadata={"phase": "planning"},
        )
        try:
            save_metrics(plan_metrics)
        except Exception as e:
            print(f"Warning: Could not save planning metrics: {e}")

    return final_plan


def _parse_plan_json(text: str) -> Dict[str, Any]:
    """Parse JSON from model output, handling markdown wrappers and malformed JSON."""
    from .json_repair import try_parse_json, extract_json_from_llm_response, validate_plan_json
    
    # First, try to extract JSON from the response
    json_text = extract_json_from_llm_response(text)
    if not json_text:
        json_text = text
    
    # Try to parse with progressive repair
    result = try_parse_json(json_text, max_repair_attempts=3)
    
    if result is None:
        # Save the problematic text for debugging
        error_file = Path("/tmp/failed_plan_json.txt")
        try:
            error_file.write_text(text, encoding="utf-8")
            print(f"❌ Saved failed JSON to {error_file} for debugging")
        except Exception:
            pass
        
        raise ValueError(
            f"Could not parse JSON from response after multiple repair attempts.\n"
            f"First 500 chars: {text[:500]}\n"
            f"Check /tmp/failed_plan_json.txt for full output"
        )
    
    # Validate plan structure
    is_valid, validation_errors = validate_plan_json(result)
    if not is_valid:
        print(f"⚠️  Plan JSON validation warnings:")
        for error in validation_errors:
            print(f"  - {error}")
    
    return result


def _validate_and_fix_plan(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate plan structure and auto-fix common issues."""
    # Auto-fix old format with top-level subtasks
    if "subtasks" in data and "stories" not in data:
        print("WARNING: Plan has top-level subtasks instead of stories, auto-converting")
        data = {
            "overview": data.get("overview", ""),
            "assumptions": data.get("assumptions", []),
            "risks": data.get("risks", []),
            "acceptance_criteria": data.get("acceptance_criteria", []),
            "stories": [
                {
                    "summary": "Implementation",
                    "description": data.get("overview", "Implement the requirements"),
                    "subtasks": data.get("subtasks", [])
                }
            ],
            "questions": data.get("questions", [])
        }
    elif "stories" not in data:
        raise ValueError("Generated plan must include 'stories' array")
    
    return data


def format_plan_as_jira_comment(plan: Dict[str, Any], is_revision: bool = False) -> str:
    # Human-readable plan for Jira comments (raw JSON stored in database).
    lines: List[str] = []
    if is_revision:
        lines.append(f"{PARENT_PLAN_COMMENT_PREFIX} (revised)")
    else:
        lines.append(PARENT_PLAN_COMMENT_PREFIX)
    lines.append("")
    
    if plan.get("overview"):
        lines.append("h3. Overview")
        lines.append(str(plan["overview"]))
        lines.append("")
    if plan.get("assumptions"):
        lines.append("h3. Assumptions")
        lines.extend([f"- {a}" for a in plan["assumptions"]])
        lines.append("")
    if plan.get("risks"):
        lines.append("h3. Risks")
        lines.extend([f"- {r}" for r in plan["risks"]])
        lines.append("")
    if plan.get("acceptance_criteria"):
        lines.append("h3. Acceptance criteria")
        lines.extend([f"- {c}" for c in plan["acceptance_criteria"]])
        lines.append("")
    if plan.get("stories"):
        lines.append("h3. Stories")
        for i, story in enumerate(plan["stories"], start=1):
            lines.append(f"{i}. *{story.get('summary','Story')}*")
            desc = story.get("description", "").strip()
            if desc:
                lines.append(desc)
            subtasks = story.get("subtasks") or []
            if subtasks:
                lines.append("Sub-tasks:")
                for st in subtasks:
                    lines.append(f"  - {st.get('summary', 'Task')}")
            lines.append("")
    if plan.get("questions"):
        lines.append("h3. Questions / clarifications")
        lines.extend([f"- {q}" for q in plan["questions"]])
        lines.append("")
    return "\n".join(lines)


def build_plan(
    issue: JiraIssue,
    revision_feedback: str = "",
    previous_plan: Optional[Dict[str, Any]] = None,
    run_id: Optional[int] = None,
) -> PlanResult:
    """Generate a plan for the given issue and format it for Jira."""
    plan_data = generate_plan(issue, revision_feedback, previous_plan, run_id)
    is_revision = bool(revision_feedback)
    comment = format_plan_as_jira_comment(plan_data, is_revision=is_revision)
    return PlanResult(comment=comment, plan_data=plan_data)


def save_story_breakdown(story_key: str, subtasks_data: List[Dict[str, Any]]) -> None:
    """
    Save Story breakdown (subtasks) to database as fallback.
    Used when Jira comment fails or is unreliable.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS story_breakdowns (
            story_key TEXT PRIMARY KEY,
            subtasks_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    
    subtasks_json = json.dumps(subtasks_data)
    cursor.execute("""
        INSERT OR REPLACE INTO story_breakdowns (story_key, subtasks_json, created_at)
        VALUES (?, ?, ?)
    """, (story_key, subtasks_json, int(time.time())))
    
    conn.commit()
    conn.close()


def get_story_breakdown(story_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    Retrieve Story breakdown from database.
    Fallback when Jira comment is not found.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT subtasks_json FROM story_breakdowns WHERE story_key = ?
    """, (story_key,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    try:
        return json.loads(row[0])
    except Exception:
        return None
