"""
Export Scanner

Scans the repository for module exports and builds a concise export map.
This map is injected into the LLM prompt so it knows what functions, types,
and components are available to import — preventing "has no exported member"
errors at code generation time.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_EXPORT_RE = re.compile(
    r"export\s+(?:async\s+)?(?:function|const|let|var|class|interface|type|enum)\s+(\w+)",
)
_EXPORT_DEFAULT_RE = re.compile(
    r"export\s+default\s+(?:async\s+)?(?:function|class)\s+(\w+)",
)
_EXPORT_BLOCK_RE = re.compile(
    r"export\s*\{([^}]+)\}",
)

_SKIP_DIRS = {
    "node_modules", ".next", ".git", "dist", "build", "__pycache__",
    ".vercel", "coverage", ".turbo",
}

_SCAN_EXTENSIONS = {".ts", ".tsx"}


def build_export_map(
    repo_path: Path,
    alias_base: str = "",
    max_modules: int = 150,
    max_chars: int = 8000,
) -> str:
    """Build a concise export map for the repository.

    Returns a formatted string listing each module and its exports, e.g.:
        @/lib/auth/session → getServerSession, getCurrentUser, type AuthSession
        @/components/layout/CRMLayout → default CRMLayout
        @/lib/prisma → prisma (default)
    """
    modules: Dict[str, List[str]] = {}

    src_dir = repo_path / alias_base if alias_base else repo_path

    if not src_dir.is_dir():
        src_dir = repo_path

    for ext in _SCAN_EXTENSIONS:
        for fpath in src_dir.rglob(f"*{ext}"):
            if any(skip in fpath.parts for skip in _SKIP_DIRS):
                continue
            if fpath.name.startswith("."):
                continue

            # Build the @/ import path
            try:
                rel = fpath.relative_to(src_dir)
            except ValueError:
                continue

            rel_str = str(rel).replace("\\", "/")
            # Strip extension and /index suffix
            module_path = re.sub(r"(/index)?\.(tsx?|jsx?)$", "", rel_str)
            alias_path = f"@/{module_path}"

            exports = _extract_exports_fast(fpath)
            if exports:
                modules[alias_path] = exports

            if len(modules) >= max_modules:
                break
        if len(modules) >= max_modules:
            break

    if not modules:
        return ""

    # Build the output string
    lines = ["**AVAILABLE MODULE EXPORTS (use these exact names when importing):**", ""]

    # Sort by path for readability
    total_chars = 0
    for path in sorted(modules.keys()):
        exports = modules[path]
        export_str = ", ".join(exports)
        line = f"  {path} → {export_str}"
        if total_chars + len(line) > max_chars:
            lines.append(f"  ... ({len(modules) - len(lines) + 2} more modules)")
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)


def _extract_exports_fast(fpath: Path) -> List[str]:
    """Extract export names from a TypeScript/TSX file.
    
    Returns a concise list like: ['getSession', 'type AuthSession', 'default CRMLayout']
    """
    try:
        content = fpath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    exports: List[str] = []
    seen: Set[str] = set()

    # Named exports: export function/const/class/interface/type/enum Name
    for m in _EXPORT_RE.finditer(content):
        name = m.group(1)
        if name not in seen:
            # Check if it's a type/interface
            prefix_match = re.search(
                rf"export\s+(?:interface|type)\s+{re.escape(name)}\b",
                content,
            )
            if prefix_match:
                exports.append(f"type {name}")
            else:
                exports.append(name)
            seen.add(name)

    # Default exports: export default function/class Name
    for m in _EXPORT_DEFAULT_RE.finditer(content):
        name = m.group(1)
        if name not in seen:
            exports.append(f"default {name}")
            seen.add(name)

    # Re-exports: export { A, B, C }
    for m in _EXPORT_BLOCK_RE.finditer(content):
        block = m.group(1)
        for item in block.split(","):
            item = item.strip()
            if " as " in item:
                item = item.split(" as ")[1].strip()
            if item.startswith("type "):
                item = item[5:].strip()
                if item and item not in seen:
                    exports.append(f"type {item}")
                    seen.add(item)
            elif item and item not in seen:
                exports.append(item)
                seen.add(item)

    # Anonymous default: export default (no function/class name)
    if "export default" in content and "default" not in " ".join(exports):
        # Get filename as the likely component name
        name = fpath.stem
        if name != "index":
            exports.append(f"default {name}")

    return exports
