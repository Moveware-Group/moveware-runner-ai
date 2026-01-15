import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.db import append_event, claim_next_run, finish_run, mark_run_failed
from app.git_ops import (
    checkout_repo,
    commit_and_push_if_needed,
    create_branch,
    create_or_get_pr,
    make_markdown_change,
)
from app.jira import JiraClient


@dataclass
class IssueContext:
    key: str
    summary: str
    description: str
    comments: str


def _host() -> str:
    return socket.gethostname()


def _issue_to_ctx(issue_json: Dict) -> IssueContext:
    fields = issue_json.get("fields", {})
    summary = fields.get("summary", "")
    description = ""
    # Jira Cloud description is usually ADF JSON; for pilot we keep it simple
    desc = fields.get("description")
    if isinstance(desc, str):
        description = desc
    elif desc is None:
        description = ""
    else:
        # ADF or nested format
        description = json.dumps(desc)[:4000]

    comments_bits = []
    comm = fields.get("comment", {}).get("comments", []) if isinstance(fields.get("comment"), dict) else []
    for c in comm[-5:]:
        author = (c.get("author", {}) or {}).get("displayName", "")
        body = c.get("body")
        if isinstance(body, str):
            body_text = body
        else:
            body_text = json.dumps(body)[:2000]
        comments_bits.append(f"- {author}: {body_text}")
    comments = "\n".join(comments_bits)

    return IssueContext(key=issue_json.get("key", ""), summary=summary, description=description, comments=comments)


def _jira() -> JiraClient:
    return JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def _process_run(run_id: int, issue_key: str) -> Tuple[str, str]:
    jira = _jira()

    issue = jira.get_issue(issue_key)
    ctx = _issue_to_ctx(issue)

    append_event(run_id, "jira.issue_loaded", {"issue_key": issue_key, "summary": ctx.summary})

    # Workdir per issue
    workdir = str(Path(settings.work_root) / issue_key)
    branch = f"ai/{issue_key}"

    # Git operations
    checkout_repo(
        workdir=workdir,
        repo_https=settings.github_repo_https,
        base_branch=settings.github_base_branch,
        token=settings.github_token,
    )
    create_branch(workdir, branch)

    # Pilot implementation: write a deterministic change
    make_markdown_change(workdir, issue_key, ctx.summary)

    pushed = commit_and_push_if_needed(workdir, issue_key)
    append_event(run_id, "git.pushed", {"pushed": pushed, "branch": branch})

    pr_url = ""
    if pushed:
        title = f"{issue_key}: {ctx.summary}".strip()
        body = (
            f"Automated change for {issue_key}.\n\n"
            f"Summary: {ctx.summary}\n\n"
            "This PR was created by the Moveware AI Runner pilot."
        )
        pr_url = create_or_get_pr(
            workdir=workdir,
            title=title,
            body=body,
            base=settings.github_base_branch,
            head=branch,
            token=settings.github_token,
        )
        append_event(run_id, "github.pr_created", {"pr_url": pr_url})

    # Jira updates
    comment_lines = [
        "AI Runner has completed initial implementation and raised a PR for review.",
        f"Branch: `{branch}`",
    ]
    if pr_url:
        comment_lines.append(f"PR: {pr_url}")
    comment_lines.append("\nNext steps: Please review the PR and either approve/merge, or comment on the ticket with required changes and re-assign to the AI Runner.")

    jira.add_comment(issue_key, "\n".join(comment_lines))

    # Move to In Testing (transition name configurable)
    try:
        jira.transition(issue_key, settings.jira_transition_in_testing)
    except Exception as e:
        append_event(run_id, "jira.transition_failed", {"target": settings.jira_transition_in_testing, "error": str(e)})
        # Non-fatal: status schemes vary

    # Assign back to Leigh
    try:
        jira.assign(issue_key, settings.jira_assignee_leigh_account_id)
    except Exception as e:
        append_event(run_id, "jira.assign_failed", {"assignee": "Leigh", "error": str(e)})

    return branch, pr_url


def worker_loop() -> None:
    worker_id = f"{_host()}:{os.getpid()}"
    poll_s = settings.worker_poll_seconds

    while True:
        run = claim_next_run(worker_id)
        if not run:
            time.sleep(poll_s)
            continue

        run_id, issue_key = run
        append_event(run_id, "worker.claimed", {"worker_id": worker_id, "issue_key": issue_key})

        try:
            branch, pr_url = _process_run(run_id, issue_key)
            finish_run(run_id, branch=branch, pr_url=pr_url)
        except Exception as e:
            mark_run_failed(run_id, str(e))


if __name__ == "__main__":
    worker_loop()
