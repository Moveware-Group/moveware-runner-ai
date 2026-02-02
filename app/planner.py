from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from .config import settings, PARENT_PLAN_COMMENT_PREFIX
from .llm_openai import OpenAIClient
from .models import JiraIssue


@dataclass
class PlanResult:
    """Result of plan generation."""
    comment: str
    plan_data: Dict[str, Any]


def _system_prompt() -> str:
    return (
        "You are an expert software technical planner. "
        "Break down the Epic into user-facing Stories. Each Story should be a cohesive feature slice. "
        "Within each Story, define technical sub-tasks (commits). "
        "Each Story will have ONE pull request containing all its sub-tasks. "
        "Only mark a sub-task as 'independent: true' if it's infrastructure/build config that should have its own PR. "
        "The output MUST be valid JSON matching the schema exactly."
    )


def _user_prompt(issue: JiraIssue, revision_feedback: str = "") -> str:
    base = (
        f"Jira issue key: {issue.key}\n"
        f"Summary: {issue.summary}\n\n"
        "Description:\n"
        f"{issue.description}\n\n"
        "Repo context is limited in the pilot. If you need more information, add 'questions' in the plan."
    )
    
    if revision_feedback:
        base += (
            "\n\n---\n\n"
            "REVISION REQUEST:\n"
            "The plan has been reviewed and the following changes are requested:\n\n"
            f"{revision_feedback}\n\n"
            "Please revise the plan to address this feedback."
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


def generate_plan(issue: JiraIssue, revision_feedback: str = "") -> Dict[str, Any]:
    client = OpenAIClient(settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    prompt = (
        "Return JSON only. Do not wrap in markdown.\n"
        "CRITICAL: Must include 'stories' array (NOT 'subtasks' at top level).\n"
        "Each story must have nested 'subtasks' array.\n"
        "Schema example:\n"
        + json.dumps(PLAN_SCHEMA_HINT, indent=2)
    )

    text = client.responses_text(
        model=settings.OPENAI_MODEL,
        system=_system_prompt(),
        user=_user_prompt(issue, revision_feedback) + "\n\n" + prompt,
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to recover if model included extra text
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    
    # Validate and auto-fix if needed
    if "subtasks" in data and "stories" not in data:
        # OpenAI returned old format with top-level subtasks, convert to stories format
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
    # Keep it readable in Jira and include a machine-parseable prefix with raw JSON.
    lines: List[str] = []
    if is_revision:
        lines.append(f"{PARENT_PLAN_COMMENT_PREFIX} (revised)")
    else:
        lines.append(PARENT_PLAN_COMMENT_PREFIX)
    lines.append("")
    
    # Include raw JSON for machine parsing
    lines.append("{code:json}")
    lines.append(json.dumps(plan, indent=2))
    lines.append("{code}")
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


def build_plan(issue: JiraIssue, revision_feedback: str = "") -> PlanResult:
    """Generate a plan for the given issue and format it for Jira."""
    plan_data = generate_plan(issue, revision_feedback)
    is_revision = bool(revision_feedback)
    comment = format_plan_as_jira_comment(plan_data, is_revision=is_revision)
    return PlanResult(comment=comment, plan_data=plan_data)
