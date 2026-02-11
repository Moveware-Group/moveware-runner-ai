from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .config import settings, PARENT_PLAN_COMMENT_PREFIX
from .llm_openai import OpenAIClient
from .llm_anthropic import AnthropicClient
from .models import JiraIssue
from .db import add_progress_event


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
    
    initial_plan_text = claude_client.extract_text(response)
    
    # Parse initial plan
    if run_id:
        add_progress_event(run_id, "planning", "Parsing Claude's initial plan", {})
    
    initial_plan = _parse_plan_json(initial_plan_text)
    
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
    
    review_text = openai_client.responses_text(
        model=settings.OPENAI_MODEL,
        system=_system_prompt_review(),
        user=review_prompt,
        max_tokens=4000,
        temperature=0.3
    )
    
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
    
    return final_plan


def _parse_plan_json(text: str) -> Dict[str, Any]:
    """Parse JSON from model output, handling markdown wrappers."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        
        # Try to find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"Could not parse JSON from response: {text[:200]}")
        return json.loads(text[start : end + 1])


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
