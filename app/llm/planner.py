from typing import Optional


def build_task_prompt(issue_key: str, summary: str, description: str, comments: str) -> str:
    """Builds a task prompt for a code-generating model.

    In production, you would include repo context (tree, relevant files) and guardrails.
    """
    return (
        f"Jira issue: {issue_key}\n"
        f"Summary: {summary}\n\n"
        f"Description:\n{description}\n\n"
        f"Recent comments:\n{comments}\n\n"
        "Deliverables:\n"
        "1) A short plan.\n"
        "2) A unified diff patch for the repository.\n"
        "Only output JSON with keys: plan, patch." 
    )


def extract_json_or_none(text: str) -> Optional[dict]:
    """Very small helper for pilots.

    Production: use a strict JSON parser with schema validation.
    """
    import json

    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        return None
