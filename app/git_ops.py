import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def run(cmd, cwd: Optional[str] = None, env: Optional[dict] = None) -> str:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    res = subprocess.run(cmd, cwd=cwd, env=merged, text=True, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
    return res.stdout.strip()


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def https_repo_url(repo: str, token: str) -> str:
    # repo can be full URL or owner/name
    if repo.startswith("https://"):
        if token:
            # https://x-access-token:<token>@github.com/owner/repo.git
            return repo.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
        return repo
    if token:
        return f"https://x-access-token:{token}@github.com/{repo}.git"
    return f"https://github.com/{repo}.git"


def clean_working_directory(workdir: str) -> None:
    """Clean uncommitted changes in the working directory.
    
    This is needed because automated processes (like npm install) may modify
    files like package-lock.json and tsconfig.json, which would block git
    checkout operations. Since the AI Runner commits all intentional changes,
    any uncommitted changes are safe to discard.
    """
    try:
        # Check if there are any uncommitted changes
        status = run(["git", "status", "--porcelain"], cwd=workdir)
        if status.strip():
            print(f"Cleaning uncommitted changes in {workdir}")
            # Reset all tracked files to HEAD
            run(["git", "reset", "--hard", "HEAD"], cwd=workdir)
            # Remove untracked files and directories
            run(["git", "clean", "-fd"], cwd=workdir)
            print("Working directory cleaned successfully")
    except Exception as e:
        # If git commands fail, log but don't crash - repo might not exist yet
        print(f"Warning: Could not clean working directory: {e}")


def checkout_repo(workdir: str, repo: str, base_branch: str, token: Optional[str] = None) -> None:
    """Checkout or update a repository. If token is None, uses settings."""
    from .config import settings
    _token = token or settings.GH_TOKEN
    
    ensure_dir(workdir)
    repo_url = https_repo_url(repo, _token)
    if not (Path(workdir) / ".git").exists():
        run(["git", "clone", repo_url, "."], cwd=workdir)
    
    # Ensure origin is correct (handles switching from a non-token URL)
    run(["git", "remote", "set-url", "origin", repo_url], cwd=workdir)
    
    # Clean any uncommitted changes before fetching/checking out
    # This handles cases where npm install or other processes modified files
    clean_working_directory(workdir)
    
    run(["git", "fetch", "--all", "--prune"], cwd=workdir)
    run(["git", "checkout", base_branch], cwd=workdir)
    # Explicitly specify remote and branch to avoid ambiguity
    run(["git", "pull", "--ff-only", "origin", base_branch], cwd=workdir)


def create_or_checkout_branch(workdir: str, branch: str) -> None:
    """Create or checkout a branch, cleaning working directory first.
    
    -B recreates local branch pointer; safe because we always push by HEAD later.
    """
    # Clean any uncommitted changes before checkout
    clean_working_directory(workdir)
    run(["git", "checkout", "-B", branch], cwd=workdir)


def make_placeholder_change(workdir: str, issue_key: str, summary: str, note: str) -> str:
    p = Path(workdir) / "AI_PILOT_CHANGELOG.md"
    existing = p.read_text(encoding="utf-8") if p.exists() else "# AI Pilot Changelog\n"
    existing += f"\n- **{issue_key}**: {summary}\n  - {note}\n"
    p.write_text(existing, encoding="utf-8")
    return str(p)


def commit_and_push_if_needed(workdir: str, commit_message: str, token: str) -> Tuple[bool, str]:
    run(["git", "add", "-A"], cwd=workdir)

    # If no changes, don't create an empty commit
    status = run(["git", "status", "--porcelain"], cwd=workdir)
    if not status.strip():
        return False, "No changes detected, skipping commit"

    # Commit
    run(["git", "commit", "-m", commit_message], cwd=workdir)

    # Push (origin already contains token in URL)
    try:
        out = run(["git", "push", "-u", "origin", "HEAD"], cwd=workdir)
        return True, out
    except RuntimeError as e:
        # If push rejected due to non-fast-forward, force push with lease
        if "rejected" in str(e) and "non-fast-forward" in str(e):
            print(f"Push rejected, force pushing with lease: {e}")
            out = run(["git", "push", "--force-with-lease", "-u", "origin", "HEAD"], cwd=workdir)
            return True, out
        raise


def find_existing_pr_url(workdir: str, head: str, token: str) -> Optional[str]:
    try:
        out = run(["gh", "pr", "view", "--head", head, "--json", "url", "-q", ".url"], cwd=workdir, env={"GH_TOKEN": token})
        return out.strip() or None
    except Exception:
        return None


def create_or_update_pr(workdir: str, title: str, body: str, base: str, head: str, token: str) -> str:
    existing = find_existing_pr_url(workdir, head=head, token=token)
    if existing:
        # Optionally update title/body (safe even if unchanged)
        try:
            run(["gh", "pr", "edit", existing, "--title", title, "--body", body], cwd=workdir, env={"GH_TOKEN": token})
        except Exception:
            pass
        return existing

    out = run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--base",
            base,
            "--head",
            head,
        ],
        cwd=workdir,
        env={"GH_TOKEN": token},
    )
    return out.strip()


# Wrapper functions for executor.py compatibility
def create_branch(workdir: str, branch: str) -> None:
    """Create or checkout a branch. Wrapper for create_or_checkout_branch."""
    create_or_checkout_branch(workdir, branch)


def checkout_or_create_story_branch(workdir: str, story_branch: str, base_branch: str) -> None:
    """Checkout Story branch if it exists on remote, otherwise create it from base."""
    # Clean any uncommitted changes before checkout operations
    clean_working_directory(workdir)
    
    # Fetch to ensure we have latest remote state
    run(["git", "fetch", "--all"], cwd=workdir)
    
    # Check if branch exists on remote
    try:
        run(["git", "rev-parse", f"origin/{story_branch}"], cwd=workdir)
        # Branch exists on remote, checkout and pull
        run(["git", "checkout", story_branch], cwd=workdir)
        run(["git", "pull", "--ff-only"], cwd=workdir)
    except RuntimeError:
        # Branch doesn't exist on remote, create from base
        run(["git", "checkout", base_branch], cwd=workdir)
        run(["git", "checkout", "-b", story_branch], cwd=workdir)


def commit_and_push(workdir: str, commit_message: str, token: Optional[str] = None) -> str:
    """Commit and push changes. Wrapper for commit_and_push_if_needed.
    
    Args:
        commit_message: Full commit message (e.g., "OD-5: add form validation")
    """
    from .config import settings
    _token = token or settings.GH_TOKEN
    
    committed, msg = commit_and_push_if_needed(workdir, commit_message, _token)
    return msg


def create_pr(workdir: str, title: str, body: str, base: str, token: Optional[str] = None) -> str:
    """Create a PR using current branch as head. Wrapper for create_or_update_pr."""
    from .config import settings
    _token = token or settings.GH_TOKEN
    
    # Get current branch
    current_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workdir)
    return create_or_update_pr(workdir, title, body, base, current_branch, _token)
