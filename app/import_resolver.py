"""
Pre-build Import Resolver

Scans source files for @/ aliased imports that don't resolve to existing files.
Creates minimal stub modules for missing imports so builds can proceed.

Runs BEFORE the build, not after failures — prevents cascading "Module not found" errors.
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# Extensions to check when resolving an import path
_RESOLVE_EXTENSIONS = [".ts", ".tsx", "/index.ts", "/index.tsx", ".js", "/index.js"]

# Patterns that indicate a React component (needs .tsx stub with JSX)
_COMPONENT_PATH_SEGMENTS = {"components/", "app/", "pages/", "views/", "layouts/", "screens/"}


def resolve_all_missing_imports(
    repo_path: Path,
    changed_files: Optional[List[str]] = None,
) -> List[str]:
    """
    Scan source files for @/ imports that don't resolve, create stubs for them,
    then repeat until no new missing imports are found (handles transitive imports).

    Args:
        repo_path: Root of the repository (where tsconfig.json lives)
        changed_files: If provided, only scan these files initially.
                       If None, scans all .ts/.tsx files.

    Returns:
        List of created stub file paths (relative to repo_path).
    """
    tsconfig_path = repo_path / "tsconfig.json"
    if not tsconfig_path.exists():
        return []

    all_created: List[str] = []
    max_rounds = 5
    round_num = 0

    while round_num < max_rounds:
        round_num += 1
        files_to_scan = _get_files_to_scan(repo_path, changed_files if round_num == 1 else None)
        missing = _find_missing_imports(repo_path, files_to_scan)

        if not missing:
            break

        created_this_round = _create_stubs(repo_path, missing, files_to_scan)
        if not created_this_round:
            break

        all_created.extend(created_this_round)
        print(f"  📦 Import resolver round {round_num}: created {len(created_this_round)} stub(s)")
        for stub in created_this_round:
            print(f"    → {stub}")

    return all_created


def _get_files_to_scan(repo_path: Path, changed_files: Optional[List[str]] = None) -> List[Path]:
    """Get list of source files to scan for imports."""
    if changed_files:
        return [
            repo_path / f
            for f in changed_files
            if f.endswith((".ts", ".tsx", ".js", ".jsx"))
            and (repo_path / f).exists()
        ]

    result = []
    for pattern in ["**/*.ts", "**/*.tsx"]:
        for f in repo_path.glob(pattern):
            rel = str(f.relative_to(repo_path))
            if "node_modules" in rel or ".next" in rel or "dist/" in rel:
                continue
            result.append(f)
    return result


def _resolve_import(repo_path: Path, alias_path: str) -> Optional[Path]:
    """
    Try to resolve an @/ aliased import to an existing file.
    Returns the resolved Path if found, None if missing.
    """
    rel_path = alias_path.replace("@/", "", 1)

    for ext in _RESOLVE_EXTENSIONS:
        candidate = repo_path / (rel_path + ext)
        if candidate.exists():
            return candidate

    # Also check if path itself exists (e.g., importing a .css file)
    direct = repo_path / rel_path
    if direct.exists() and direct.is_file():
        return direct

    return None


def _find_missing_imports(repo_path: Path, files: List[Path]) -> Dict[str, Set[Tuple[str, str]]]:
    """
    Scan files for @/ imports and identify which ones don't resolve.

    Returns:
        Dict mapping alias_path -> set of (export_kind, symbol_name)
        export_kind is 'named' or 'default'
    """
    # Regex patterns for import statements
    named_import_re = re.compile(
        r"import\s+\{([^}]+)\}\s+from\s+['\"](@/[^'\"]+)['\"]"
    )
    default_import_re = re.compile(
        r"import\s+(\w+)\s+from\s+['\"](@/[^'\"]+)['\"]"
    )
    # Also match: import type { Foo } from '@/...'
    type_import_re = re.compile(
        r"import\s+type\s+\{([^}]+)\}\s+from\s+['\"](@/[^'\"]+)['\"]"
    )

    missing: Dict[str, Set[Tuple[str, str]]] = {}

    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        for m in named_import_re.finditer(content):
            symbols_str, alias_path = m.group(1), m.group(2)
            if _resolve_import(repo_path, alias_path) is None:
                if alias_path not in missing:
                    missing[alias_path] = set()
                for sym in symbols_str.split(","):
                    sym = sym.strip().split(" as ")[0].strip()
                    if sym:
                        missing[alias_path].add(("named", sym))

        for m in default_import_re.finditer(content):
            symbol, alias_path = m.group(1), m.group(2)
            # Skip 'import type X from ...' which the default regex might match
            # Check that it's not preceded by 'type '
            start = m.start()
            prefix = content[max(0, start - 10):start]
            if "type " in prefix:
                continue
            if _resolve_import(repo_path, alias_path) is None:
                if alias_path not in missing:
                    missing[alias_path] = set()
                missing[alias_path].add(("default", symbol))

        for m in type_import_re.finditer(content):
            symbols_str, alias_path = m.group(1), m.group(2)
            if _resolve_import(repo_path, alias_path) is None:
                if alias_path not in missing:
                    missing[alias_path] = set()
                for sym in symbols_str.split(","):
                    sym = sym.strip().split(" as ")[0].strip()
                    if sym:
                        missing[alias_path].add(("type", sym))

    return missing


def _is_component_path(rel_path: str) -> bool:
    """Determine if a path is likely a React component."""
    for segment in _COMPONENT_PATH_SEGMENTS:
        if segment in rel_path:
            return True
    # Also check if the filename starts with uppercase (convention for components)
    basename = rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path
    return basename[0].isupper() if basename else False


def _create_stubs(
    repo_path: Path,
    missing: Dict[str, Set[Tuple[str, str]]],
    existing_files: List[Path],
) -> List[str]:
    """Create stub files for missing imports. Returns list of created file paths."""
    created = []

    for alias_path, exports in missing.items():
        rel_path = alias_path.replace("@/", "", 1)
        is_component = _is_component_path(rel_path)

        ext = ".tsx" if is_component else ".ts"
        target_file = rel_path + ext
        target_path = repo_path / target_file

        # Don't overwrite existing files
        if target_path.exists():
            continue

        lines: List[str] = []

        if is_component:
            lines.append("'use client';")
            lines.append("")

        has_default = any(kind == "default" for kind, _ in exports)
        named_exports = [(kind, name) for kind, name in exports if kind == "named"]
        type_exports = [(kind, name) for kind, name in exports if kind == "type"]
        default_exports = [(kind, name) for kind, name in exports if kind == "default"]

        # Type exports → export as interfaces/types
        for _, name in sorted(type_exports, key=lambda x: x[1]):
            lines.append(f"export interface {name} {{}}")
            lines.append("")

        # Named exports
        for _, name in sorted(named_exports, key=lambda x: x[1]):
            if is_component and name[0:1].isupper():
                lines.append(f"export function {name}(props: any) {{")
                lines.append(f'  return <div data-stub="{name}">{{/* stub */}}</div>;')
                lines.append("}")
            else:
                lines.append(f"export const {name} = undefined as any;")
            lines.append("")

        # Default export
        for _, name in default_exports:
            if is_component:
                lines.append(f"export default function {name}(props: any) {{")
                lines.append(f'  return <div data-stub="{name}">{{/* stub */}}</div>;')
                lines.append("}")
            else:
                lines.append(f"export default function {name}(...args: any[]) {{")
                lines.append("  return undefined as any;")
                lines.append("}")
            lines.append("")

        if not lines or all(line == "" for line in lines):
            # No exports detected — create a minimal placeholder
            if is_component:
                comp_name = rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path
                lines = [
                    "'use client';",
                    "",
                    f"export default function {comp_name}(props: any) {{",
                    f'  return <div data-stub="{comp_name}">{{/* stub */}}</div>;',
                    "}",
                    "",
                ]
            else:
                lines = ["export {};", ""]

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(target_file)

    return created
