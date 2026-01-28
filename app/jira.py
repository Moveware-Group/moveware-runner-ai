import base64
from typing import Any, Dict, List, Optional

import requests

from .config import settings


class JiraClient:
    def __init__(self, base_url: Optional[str] = None, email: Optional[str] = None, api_token: Optional[str] = None, timeout_s: int = 30):
        # Use settings if not provided
        self.base_url = (base_url or settings.JIRA_BASE_URL).rstrip("/")
        _email = email or settings.JIRA_EMAIL
        _token = api_token or settings.JIRA_API_TOKEN
        token = base64.b64encode(f"{_email}:{_token}".encode("utf-8")).decode("utf-8")
        self._auth_header = f"Basic {token}"
        self.timeout_s = timeout_s

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        r = requests.get(url, headers=self._headers(), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    def add_comment(self, issue_key: str, body_md: str) -> None:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        payload = {"body": body_md}
        r = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout_s)
        r.raise_for_status()

    def assign(self, issue_key: str, account_id: str) -> None:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/assignee"
        r = requests.put(url, headers=self._headers(), json={"accountId": account_id}, timeout=self.timeout_s)
        r.raise_for_status()

    def get_transitions(self, issue_key: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions"
        r = requests.get(url, headers=self._headers(), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json().get("transitions", [])

    def transition(self, issue_key: str, transition_id: str) -> None:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions"
        payload = {"transition": {"id": transition_id}}
        r = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout_s)
        r.raise_for_status()

    def transition_by_name(self, issue_key: str, target_name: str) -> Optional[str]:
        for t in self.get_transitions(issue_key):
            if t.get("name", "").strip().lower() == target_name.strip().lower():
                self.transition(issue_key, t["id"])
                return t["id"]
        return None

    def transition_to_status(self, issue_key: str, status_name: str) -> Optional[str]:
        """Transition an issue to a target *status* name.

        Jira transitions are not always named the same as the destination status.
        This helper matches on the transition's `to.name`.
        """
        target = status_name.strip().lower()
        for t in self.get_transitions(issue_key):
            to_name = (t.get("to") or {}).get("name", "").strip().lower()
            if to_name == target:
                self.transition(issue_key, t["id"])
                return t["id"]
        return None

    def assign_issue(self, issue_key: str, account_id: str) -> None:
        """Alias for assign() method."""
        self.assign(issue_key, account_id)

    def get_comments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get all comments for an issue."""
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        r = requests.get(url, headers=self._headers(), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json().get("comments", [])

    def get_subtasks(self, parent_key: str) -> List[Dict[str, Any]]:
        """Get all subtasks for a parent issue."""
        parent = self.get_issue(parent_key)
        fields = parent.get("fields", {})
        subtasks = fields.get("subtasks", [])
        # Subtasks in the parent response are minimal; fetch full details
        full_subtasks = []
        for st in subtasks:
            st_key = st.get("key")
            if st_key:
                full_subtasks.append(self.get_issue(st_key))
        return full_subtasks

    def create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str = "",
        project_key: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> str:
        """Create a subtask under a parent issue. Returns the new subtask key."""
        # Get parent to extract project
        parent = self.get_issue(parent_key)
        parent_fields = parent.get("fields", {})
        project = parent_fields.get("project", {})
        proj_key = project_key or project.get("key")
        
        if not proj_key:
            raise ValueError(f"Could not determine project for parent {parent_key}")

        # Create subtask
        url = f"{self.base_url}/rest/api/3/issue"
        payload: Dict[str, Any] = {
            "fields": {
                "project": {"key": proj_key},
                "parent": {"key": parent_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": "Sub-task"},
            }
        }
        if labels:
            payload["fields"]["labels"] = labels

        r = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout_s)
        r.raise_for_status()
        result = r.json()
        return result.get("key", "")
