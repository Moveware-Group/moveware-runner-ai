from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class JiraIssue:
    key: str
    summary: str
    description: str
    issue_type: str
    is_subtask: bool
    status: str
    assignee_account_id: Optional[str]
    parent_key: Optional[str]
    labels: List[str]
    raw: Dict[str, Any]


def parse_issue(issue: Dict[str, Any]) -> JiraIssue:
    fields = issue.get("fields") or {}
    issuetype = fields.get("issuetype") or {}
    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    parent = fields.get("parent") or {}

    desc = fields.get("description")
    # Jira Cloud v3 description is often Atlassian Document Format. Keep as JSON string.
    description_text = ""
    if isinstance(desc, str):
        description_text = desc
    elif desc is not None:
        import json

        description_text = json.dumps(desc, ensure_ascii=False)

    return JiraIssue(
        key=issue.get("key", ""),
        summary=fields.get("summary", ""),
        description=description_text,
        issue_type=issuetype.get("name", ""),
        is_subtask=bool(issuetype.get("subtask")),
        status=status.get("name", ""),
        assignee_account_id=assignee.get("accountId"),
        parent_key=parent.get("key"),
        labels=list(fields.get("labels") or []),
        raw=issue,
    )
