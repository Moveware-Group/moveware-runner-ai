"""
Playwright visual regression testing for the AI orchestrator.

Captures screenshots of key pages before and after AI-driven changes,
then compares them pixel-by-pixel to detect unintended visual regressions.

Uses Playwright's Python bindings (playwright-python) running headless Chromium.
No external service required — baselines are stored locally per-run and compared
in-memory. Regressions feed into the LLM self-heal loop like build errors.

Prerequisites on the runner host:
  - pip install playwright
  - python -m playwright install chromium

Config (all optional — sensible defaults):
  VISUAL_TEST_ENABLED=true           (default: true for UI changes)
  VISUAL_TEST_THRESHOLD=0.2          (max % pixel diff before flagging, default 0.2)
  VISUAL_TEST_VIEWPORT=1280x720      (default viewport)
  VISUAL_TEST_TIMEOUT=30             (page load timeout in seconds)
  VISUAL_TEST_DEV_SERVER_PORT=3000   (local dev server port for screenshots)
"""
from __future__ import annotations

import os
import subprocess
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Tuple


@dataclass
class PageDiff:
    """Result of comparing a single page before/after."""
    page_name: str
    url_path: str
    diff_percent: float = 0.0
    passed: bool = True
    baseline_path: str = ""
    current_path: str = ""
    diff_path: str = ""
    error: Optional[str] = None


@dataclass
class VisualTestResult:
    """Aggregated visual regression test results."""
    total_pages: int = 0
    passed: int = 0
    failed: int = 0
    regressions: List[PageDiff] = field(default_factory=list)
    threshold: float = 0.2
    error: Optional[str] = None

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.error is None

    def to_prompt_context(self) -> str:
        """Format regressions for the LLM self-healing loop."""
        if self.error:
            return f"**Visual Regression Tests:** Could not run — {self.error}"
        if self.all_passed:
            return ""

        parts = [
            f"**Visual Regression Tests FAILED:** {self.failed} of {self.total_pages} pages have visual regressions (threshold: {self.threshold}%)",
        ]

        for r in self.regressions[:5]:
            parts.append(f"\n**REGRESSION: {r.page_name} ({r.url_path})**")
            parts.append(f"- Pixel difference: {r.diff_percent:.2f}% (threshold: {self.threshold}%)")
            if r.error:
                parts.append(f"- Error: {r.error}")

        parts.append(
            "\n**Fix the visual regressions by correcting styles, layout, or component "
            "changes that caused the page to look different from before your changes. "
            "Common causes: missing CSS classes, changed spacing/padding, removed elements, "
            "incorrect Tailwind classes, or z-index issues.**"
        )

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.error:
            return f"**Visual Tests:** {self.error}"

        icon = "PASS" if self.all_passed else "WARN"
        lines = [
            f"**Visual Regression Tests [{icon}]:** {self.passed}/{self.total_pages} pages unchanged",
        ]

        if self.regressions:
            lines.append("\n**Visual changes detected:**")
            for r in self.regressions[:10]:
                status = "REGRESSION" if not r.passed else "OK"
                lines.append(f"- [{status}] {r.page_name} ({r.url_path}): {r.diff_percent:.2f}% diff")
                if r.error:
                    lines.append(f"  Error: {r.error}")

        return "\n".join(lines)


def _get_config() -> dict:
    """Read visual testing config from environment."""
    viewport_str = os.getenv("VISUAL_TEST_VIEWPORT", "1280x720")
    try:
        w, h = viewport_str.lower().split("x")
        width, height = int(w), int(h)
    except (ValueError, AttributeError):
        width, height = 1280, 720

    return {
        "enabled": os.getenv("VISUAL_TEST_ENABLED", "true").lower() in ("true", "1", "yes"),
        "threshold": float(os.getenv("VISUAL_TEST_THRESHOLD", "0.2")),
        "viewport_width": width,
        "viewport_height": height,
        "timeout_seconds": int(os.getenv("VISUAL_TEST_TIMEOUT", "30")),
        "dev_server_port": int(os.getenv("VISUAL_TEST_DEV_SERVER_PORT", "3000")),
    }


def is_enabled() -> bool:
    """Check if visual testing is enabled."""
    return _get_config()["enabled"]


def has_ui_changes(changed_files: List[str]) -> bool:
    """Determine if changed files include UI-related files worth screenshot-testing."""
    ui_extensions = ('.tsx', '.jsx', '.css', '.scss', '.sass', '.less',
                     '.html', '.svg', '.module.css', '.module.scss')
    ui_directories = ('components', 'pages', 'app', 'styles', 'layouts', 'views', 'ui')

    for f in changed_files:
        if any(f.endswith(ext) for ext in ui_extensions):
            return True
        parts = Path(f).parts
        if any(d in parts for d in ui_directories):
            if f.endswith(('.ts', '.tsx', '.js', '.jsx')):
                return True
    return False


def detect_routes(repo_path: Path) -> List[Tuple[str, str]]:
    """
    Auto-detect pages/routes to screenshot from a Next.js App Router project.

    Returns list of (page_name, url_path) tuples.
    Falls back to a default set if detection fails.
    """
    routes: List[Tuple[str, str]] = []

    # Next.js App Router: scan app/ directory for page.tsx files
    app_dir = repo_path / "src" / "app"
    if not app_dir.exists():
        app_dir = repo_path / "app"

    if app_dir.exists():
        for page_file in app_dir.rglob("page.tsx"):
            rel = page_file.parent.relative_to(app_dir)
            route_parts = [p for p in rel.parts if not p.startswith("(")]
            url_path = "/" + "/".join(route_parts) if route_parts else "/"
            # Skip dynamic routes like [id] — can't screenshot without real data
            if "[" in url_path:
                continue
            name = url_path if url_path != "/" else "Home"
            routes.append((name, url_path))

        for page_file in app_dir.rglob("page.jsx"):
            rel = page_file.parent.relative_to(app_dir)
            route_parts = [p for p in rel.parts if not p.startswith("(")]
            url_path = "/" + "/".join(route_parts) if route_parts else "/"
            if "[" in url_path:
                continue
            name = url_path if url_path != "/" else "Home"
            if (name, url_path) not in routes:
                routes.append((name, url_path))

    # Next.js Pages Router: scan pages/ directory
    pages_dir = repo_path / "src" / "pages"
    if not pages_dir.exists():
        pages_dir = repo_path / "pages"

    if pages_dir.exists() and not routes:
        for page_file in pages_dir.rglob("*.tsx"):
            if page_file.name.startswith("_") or page_file.name.startswith("["):
                continue
            if page_file.parent.name == "api":
                continue
            rel = page_file.relative_to(pages_dir)
            stem = rel.with_suffix("")
            url_path = "/" + str(stem).replace("\\", "/").replace("index", "").rstrip("/")
            if not url_path:
                url_path = "/"
            name = url_path if url_path != "/" else "Home"
            routes.append((name, url_path))

    if not routes:
        routes = [("Home", "/")]

    return routes


def _ensure_playwright_installed() -> bool:
    """Check playwright is available; install chromium if needed."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("Visual testing: playwright not installed (pip install playwright)")
        return False

    try:
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "--with-deps", "chromium"],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Visual testing: could not install chromium: {e}")
        return False


def _start_dev_server(repo_path: Path, port: int) -> Optional[subprocess.Popen]:
    """Start a Next.js dev/preview server and wait for it to be ready."""
    pkg_path = repo_path / "package.json"
    if not pkg_path.exists():
        return None

    import json as _json
    try:
        pkg = _json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    scripts = pkg.get("scripts", {})

    # Prefer 'start' (production) if .next exists, otherwise 'dev'
    next_dir = repo_path / ".next"
    if next_dir.exists() and "start" in scripts:
        cmd = ["npx", "next", "start", "-p", str(port)]
    elif "dev" in scripts:
        cmd = ["npx", "next", "dev", "-p", str(port)]
    else:
        return None

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["NODE_ENV"] = "production" if "start" in " ".join(cmd) else "development"

    try:
        proc = subprocess.Popen(
            cmd, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True,
        )
    except Exception as e:
        print(f"Visual testing: could not start dev server: {e}")
        return None

    # Wait up to 30s for the server to respond
    import urllib.request
    import urllib.error
    base_url = f"http://localhost:{port}"
    for _ in range(60):
        time.sleep(0.5)
        if proc.poll() is not None:
            print(f"Visual testing: dev server exited early (code {proc.returncode})")
            return None
        try:
            urllib.request.urlopen(base_url, timeout=2)
            return proc
        except (urllib.error.URLError, ConnectionError, OSError):
            continue

    print("Visual testing: dev server did not become ready in 30s")
    proc.terminate()
    return None


def _stop_dev_server(proc: Optional[subprocess.Popen]) -> None:
    """Gracefully stop the dev server."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _compare_images(img1_path: Path, img2_path: Path, diff_path: Path) -> float:
    """
    Compare two PNG images pixel-by-pixel. Returns diff percentage (0-100).
    Uses raw pixel comparison — no external image library needed beyond Playwright.
    Falls back to file-size heuristic if pixel comparison isn't possible.
    """
    try:
        from PIL import Image

        im1 = Image.open(img1_path).convert("RGBA")
        im2 = Image.open(img2_path).convert("RGBA")

        # Resize to common dimensions if different
        if im1.size != im2.size:
            common_w = max(im1.width, im2.width)
            common_h = max(im1.height, im2.height)
            im1 = im1.resize((common_w, common_h))
            im2 = im2.resize((common_w, common_h))

        pixels1 = list(im1.getdata())
        pixels2 = list(im2.getdata())
        total = len(pixels1)
        if total == 0:
            return 0.0

        diff_count = 0
        diff_pixels = []
        for p1, p2 in zip(pixels1, pixels2):
            if p1 != p2:
                diff_count += 1
                # Red highlight for diff image
                diff_pixels.append((255, 0, 0, 255))
            else:
                diff_pixels.append((p1[0], p1[1], p1[2], 80))

        # Write diff image
        diff_img = Image.new("RGBA", im1.size)
        diff_img.putdata(diff_pixels)
        diff_img.save(diff_path)

        return (diff_count / total) * 100.0

    except ImportError:
        # No PIL — compare raw file bytes as fallback
        b1 = img1_path.read_bytes()
        b2 = img2_path.read_bytes()
        if b1 == b2:
            return 0.0
        # Rough heuristic: byte-level difference ratio
        min_len = min(len(b1), len(b2))
        max_len = max(len(b1), len(b2))
        if max_len == 0:
            return 0.0
        diffs = sum(1 for a, b in zip(b1[:min_len], b2[:min_len]) if a != b)
        diffs += max_len - min_len
        return min((diffs / max_len) * 100.0, 100.0)


def capture_screenshots(
    repo_path: Path,
    routes: List[Tuple[str, str]],
    output_dir: Path,
    port: int = 3000,
    viewport_width: int = 1280,
    viewport_height: int = 720,
    timeout_ms: int = 30000,
) -> List[PageDiff]:
    """
    Capture full-page screenshots for each route.

    Returns list of PageDiff with paths filled in (used later for comparison).
    """
    results: List[PageDiff] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [PageDiff(
            page_name="all", url_path="/",
            error="playwright not installed (pip install playwright)",
        )]

    base_url = f"http://localhost:{port}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                device_scale_factor=1,
            )
            page = context.new_page()

            for name, url_path in routes:
                diff = PageDiff(page_name=name, url_path=url_path)
                safe_name = name.replace("/", "_").replace(" ", "_").strip("_") or "home"
                screenshot_path = output_dir / f"{safe_name}.png"

                try:
                    full_url = f"{base_url}{url_path}"
                    page.goto(full_url, wait_until="networkidle", timeout=timeout_ms)
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    diff.baseline_path = str(screenshot_path)
                except Exception as e:
                    diff.error = f"Could not capture {url_path}: {e}"

                results.append(diff)

            browser.close()

    except Exception as e:
        results.append(PageDiff(page_name="all", url_path="/", error=str(e)))

    return results


def _ensure_gitignore(repo_path: Path) -> None:
    """Add visual testing temp dirs to the target repo's .gitignore."""
    gitignore = repo_path / ".gitignore"
    entries = [".visual-current/", ".visual-diffs/"]

    existing = ""
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")

    additions = [e for e in entries if e not in existing]
    if not additions:
        return

    with open(gitignore, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n# Visual regression test artifacts (runner-generated)\n")
        for entry in additions:
            f.write(f"{entry}\n")


def run_visual_tests(
    repo_path: Path,
    changed_files: Optional[List[str]] = None,
    run_id: Optional[int] = None,
) -> VisualTestResult:
    """
    Full visual regression test pipeline:
      1. Detect routes to test
      2. Start dev server
      3. Capture "current" screenshots (code already has AI changes applied + built)
      4. Compare against baselines (stored from previous successful run)
      5. Report regressions

    Baselines are stored in <repo>/.visual-baselines/ and committed with the repo.
    On the first run (no baselines), all pages pass and baselines are created.
    """
    config = _get_config()
    result = VisualTestResult(threshold=config["threshold"])

    if not config["enabled"]:
        result.error = "Visual testing disabled"
        return result

    if changed_files and not has_ui_changes(changed_files):
        result.error = "No UI changes detected — skipping visual tests"
        return result

    if not _ensure_playwright_installed():
        result.error = "Playwright not available (pip install playwright && python -m playwright install chromium)"
        return result

    routes = detect_routes(repo_path)
    result.total_pages = len(routes)

    _ensure_gitignore(repo_path)

    port = config["dev_server_port"]
    baseline_dir = repo_path / ".visual-baselines"
    current_dir = repo_path / ".visual-current"
    diff_dir = repo_path / ".visual-diffs"

    # Clean previous run artifacts
    for d in (current_dir, diff_dir):
        if d.exists():
            shutil.rmtree(d)

    # Start dev server
    server_proc = _start_dev_server(repo_path, port)
    if server_proc is None:
        result.error = "Could not start dev server for visual testing"
        return result

    try:
        # Capture current screenshots
        print(f"Visual testing: capturing {len(routes)} pages...")
        current_shots = capture_screenshots(
            repo_path, routes, current_dir,
            port=port,
            viewport_width=config["viewport_width"],
            viewport_height=config["viewport_height"],
            timeout_ms=config["timeout_seconds"] * 1000,
        )

        first_run = not baseline_dir.exists()
        if first_run:
            baseline_dir.mkdir(parents=True, exist_ok=True)

        for shot in current_shots:
            if shot.error:
                result.regressions.append(shot)
                result.failed += 1
                continue

            safe_name = shot.page_name.replace("/", "_").replace(" ", "_").strip("_") or "home"
            current_file = current_dir / f"{safe_name}.png"
            baseline_file = baseline_dir / f"{safe_name}.png"

            if not current_file.exists():
                shot.error = f"Screenshot not captured for {shot.page_name}"
                result.regressions.append(shot)
                result.failed += 1
                continue

            if first_run or not baseline_file.exists():
                # No baseline — accept current as baseline
                shutil.copy2(current_file, baseline_file)
                shot.passed = True
                result.passed += 1
                print(f"  ✓ {shot.page_name}: baseline created")
                continue

            # Compare
            diff_dir.mkdir(parents=True, exist_ok=True)
            diff_file = diff_dir / f"{safe_name}_diff.png"

            diff_pct = _compare_images(baseline_file, current_file, diff_file)
            shot.diff_percent = round(diff_pct, 4)
            shot.baseline_path = str(baseline_file)
            shot.current_path = str(current_file)
            shot.diff_path = str(diff_file)

            if diff_pct > config["threshold"]:
                shot.passed = False
                result.failed += 1
                result.regressions.append(shot)
                print(f"  ✗ {shot.page_name}: {diff_pct:.2f}% diff (threshold {config['threshold']}%)")
            else:
                shot.passed = True
                result.passed += 1
                print(f"  ✓ {shot.page_name}: {diff_pct:.2f}% diff (OK)")

    finally:
        _stop_dev_server(server_proc)

    # If all passed (and not first run), update baselines to current
    if result.all_passed and not first_run:
        for shot in current_shots:
            if shot.error:
                continue
            safe_name = shot.page_name.replace("/", "_").replace(" ", "_").strip("_") or "home"
            current_file = current_dir / f"{safe_name}.png"
            baseline_file = baseline_dir / f"{safe_name}.png"
            if current_file.exists():
                shutil.copy2(current_file, baseline_file)

    return result
