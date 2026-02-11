import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# Import GitHub App auth (optional, falls back to PAT)
try:
    from .github_app import get_github_token
    _GITHUB_APP_AVAILABLE = True
except ImportError:
    _GITHUB_APP_AVAILABLE = False
    
    def get_github_token() -> str:
        """Fallback: use GH_TOKEN environment variable."""
        token = os.getenv('GH_TOKEN', '')
        if not token:
            raise ValueError("GH_TOKEN not set")
        return token


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
    """
    Build HTTPS clone URL. Handles:
    - https://github.com/owner/repo[.git]
    - git@github.com:owner/repo[.git]
    - owner/repo
    """
    repo = (repo or "").strip()
    # Normalize SSH format (git@github.com:owner/repo.git) to owner/repo
    if repo.startswith("git@github.com:"):
        repo = repo[len("git@github.com:"):].rstrip("/").rstrip()
        if repo.endswith(".git"):
            repo = repo[:-4]
    # Full HTTPS URL
    elif repo.startswith("https://"):
        if token:
            return repo.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
        return repo
    # Ensure owner/repo (no leading path, no double .git)
    if repo.endswith(".git"):
        repo = repo[:-4]
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
    # Log clone target (owner/repo only, no token) for debugging
    if "@github.com/" in repo_url:
        display = repo_url.split("@github.com/")[-1].replace(".git", "")
    else:
        display = repo.replace("git@github.com:", "").replace(".git", "").strip() or "?"
    print(f"[git_ops] Cloning github.com/{display}")
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


def find_existing_pr_url(workdir: str, head: str, token: Optional[str] = None) -> Optional[str]:
    """Find existing PR by head branch."""
    if not token:
        token = get_github_token()
    
    try:
        out = run(["gh", "pr", "view", "--head", head, "--json", "url", "-q", ".url"], cwd=workdir, env={"GH_TOKEN": token})
        return out.strip() or None
    except Exception:
        return None


def create_or_update_pr(workdir: str, title: str, body: str, base: str, head: str, token: Optional[str] = None) -> str:
    """Create or update a pull request."""
    if not token:
        token = get_github_token()
    
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
        # Explicitly specify remote and branch
        run(["git", "pull", "--ff-only", "origin", story_branch], cwd=workdir)
    except RuntimeError:
        # Branch doesn't exist on remote, create from base
        run(["git", "checkout", base_branch], cwd=workdir)
        run(["git", "checkout", "-b", story_branch], cwd=workdir)


def commit_and_push(workdir: str, commit_message: str, token: Optional[str] = None) -> str:
    """Commit and push changes. Wrapper for commit_and_push_if_needed.
    
    Args:
        commit_message: Full commit message (e.g., "OD-5: add form validation")
    """
    if not token:
        token = get_github_token()
    
    committed, msg = commit_and_push_if_needed(workdir, commit_message, token)
    return msg


def create_pr(workdir: str, title: str, body: str, base: str, token: Optional[str] = None) -> str:
    """Create a PR using current branch as head. Wrapper for create_or_update_pr."""
    if not token:
        token = get_github_token()
    
    # Get current branch
    current_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workdir)
    return create_or_update_pr(workdir, title, body, base, current_branch, token)


def create_rollback_tag(workdir: str, issue_key: str) -> Optional[str]:
    """
    Create a rollback tag before making changes.
    
    This allows easy rollback if the commit causes issues.
    
    Args:
        workdir: Repository working directory
        issue_key: Jira issue key (e.g., "OD-123")
    
    Returns:
        Tag name if created, None if failed
    """
    try:
        # Get current commit SHA
        current_sha = run(["git", "rev-parse", "HEAD"], cwd=workdir)
        
        # Create tag name
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        tag_name = f"rollback/{issue_key.lower()}/{timestamp}"
        
        # Create annotated tag
        run([
            "git", "tag", "-a", tag_name, current_sha,
            "-m", f"Rollback point before {issue_key}"
        ], cwd=workdir)
        
        print(f"✓ Created rollback tag: {tag_name}")
        return tag_name
        
    except Exception as e:
        print(f"Warning: Could not create rollback tag: {e}")
        return None


def rollback_to_tag(workdir: str, tag_name: str, force: bool = False) -> None:
    """
    Rollback to a specific tag.
    
    Args:
        workdir: Repository working directory
        tag_name: Name of the tag to rollback to
        force: If True, hard reset (lose uncommitted changes)
    
    Raises:
        RuntimeError: If rollback fails
    """
    try:
        if force:
            # Hard reset to tag (lose all changes)
            run(["git", "reset", "--hard", tag_name], cwd=workdir)
            print(f"✓ Hard reset to {tag_name}")
        else:
            # Soft reset (keep changes as uncommitted)
            run(["git", "reset", "--soft", tag_name], cwd=workdir)
            print(f"✓ Soft reset to {tag_name} (changes preserved)")
            
    except Exception as e:
        raise RuntimeError(f"Failed to rollback to {tag_name}: {e}")


def list_rollback_tags(workdir: str, issue_key: Optional[str] = None) -> list[str]:
    """
    List available rollback tags.
    
    Args:
        workdir: Repository working directory
        issue_key: Optional filter by issue key
    
    Returns:
        List of rollback tag names
    """
    try:
        pattern = f"rollback/{issue_key.lower()}/*" if issue_key else "rollback/*"
        tags = run(["git", "tag", "-l", pattern], cwd=workdir)
        return [t.strip() for t in tags.split('\n') if t.strip()]
    except Exception as e:
        print(f"Warning: Could not list rollback tags: {e}")
        return []


def delete_rollback_tag(workdir: str, tag_name: str) -> None:
    """
    Delete a rollback tag (cleanup old tags).
    
    Args:
        workdir: Repository working directory
        tag_name: Name of the tag to delete
    """
    try:
        run(["git", "tag", "-d", tag_name], cwd=workdir)
        print(f"✓ Deleted rollback tag: {tag_name}")
    except Exception as e:
        print(f"Warning: Could not delete tag {tag_name}: {e}")
