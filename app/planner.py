from __future__ import annotations

import json
from typing import Any, Dict, List

from .config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_BASE_URL,
    PARENT_PLAN_COMMENT_PREFIX,
)
from .llm_openai import OpenAIClient
from .models import JiraIssue


def _system_prompt() -> str:
    return (
        "You are an expert software technical planner. "
        "Produce a safe, incremental implementation plan for the Jira ticket. "
        "The output MUST be valid JSON matching the schema exactly."
    )


def _user_prompt(issue: JiraIssue) -> str:
    return (
        f"Jira issue key: {issue.key}\n"
        f"Summary: {issue.summary}\n\n"
        "Description:\n"
        f"{issue.description}\n\n"
        "Repo context is limited in the pilot. If you need more information, add 'questions' in the plan."
    )


PLAN_SCHEMA_HINT = {
    "plan_version": "v1",
    "overview": "Short overview of approach",
    "assumptions": ["..."],
    "risks": ["..."],
    "acceptance_criteria": ["..."],
    "subtasks": [
        {
            "summary": "Short subtask title",
            "description": "What to change and why",
            "labels": ["optional"],
        }
    ],
    "questions": ["Optional questions needing clarification"],
}


def generate_plan(issue: JiraIssue) -> Dict[str, Any]:
    client = OpenAIClient(OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    prompt = (
        "Return JSON only. Do not wrap in markdown.\n"
        "Schema example:\n"
        + json.dumps(PLAN_SCHEMA_HINT, indent=2)
    )

    text = client.responses_text(
        model=OPENAI_MODEL,
        system=_system_prompt(),
        user=_user_prompt(issue) + "\n\n" + prompt,
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
    return data


def format_plan_as_jira_comment(plan: Dict[str, Any]) -> str:
    # Keep it readable in Jira and include a machine-parseable prefix.
    lines: List[str] = []
    lines.append(f"{PARENT_PLAN_COMMENT_PREFIX} {plan.get('plan_version','v1')}")
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
    if plan.get("subtasks"):
        lines.append("h3. Proposed sub-tasks")
        for i, st in enumerate(plan["subtasks"], start=1):
            lines.append(f"{i}. *{st.get('summary','Sub-task')}*")
            desc = st.get("description", "").strip()
            if desc:
                lines.append(desc)
            labels = st.get("labels") or []
            if labels:
                lines.append(f"Labels: {', '.join(labels)}")
            lines.append("")
    if plan.get("questions"):
        lines.append("h3. Questions / clarifications")
        lines.extend([f"- {q}" for q in plan["questions"]])
        lines.append("")
    lines.append("----")
    lines.append("{code:json}")
    lines.append(json.dumps(plan, indent=2))
    lines.append("{code}")
    return "\n".join(lines)
