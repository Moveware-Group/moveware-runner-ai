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


_RESOLVE_EXTENSIONS = [".ts", ".tsx", "/index.ts", "/index.tsx", ".js", "/index.js"]

_COMPONENT_PATH_SEGMENTS = {"components/", "app/", "pages/", "views/", "layouts/", "screens/"}

# All import patterns in one pass
_IMPORT_RE = re.compile(
    r"import\s+"
    r"(?:type\s+)?"        # optional top-level 'type' modifier
    r"(?:"
    r"  \{([^}]+)\}"       # group 1: named imports { A, B, type C }
    r"  |(\w+)"            # group 2: default import  Foo
    r")"
    r"\s+from\s+['\"](@/[^'\"]+)['\"]",  # group 3: module path
    re.VERBOSE,
)


def resolve_all_missing_imports(
    repo_path: Path,
    changed_files: Optional[List[str]] = None,
) -> List[str]:
    """
    Scan source files for @/ imports that don't resolve, create stubs for them,
    then repeat until no new missing imports are found (handles transitive imports).

    Returns:
        List of created stub file paths (relative to repo_path).
    """
    if not (repo_path / "tsconfig.json").exists():
        return []

    all_created: List[str] = []
    max_rounds = 5

    for round_num in range(1, max_rounds + 1):
        files_to_scan = _get_files_to_scan(repo_path, changed_files if round_num == 1 else None)
        missing = _find_missing_imports(repo_path, files_to_scan)

        if not missing:
            break

        created_this_round = _create_stubs(repo_path, missing)
        if not created_this_round:
            break

        all_created.extend(created_this_round)
        print(f"  📦 Import resolver round {round_num}: created {len(created_this_round)} stub(s)")
        for stub in created_this_round:
            print(f"    → {stub}")

    return all_created


def _get_files_to_scan(repo_path: Path, changed_files: Optional[List[str]] = None) -> List[Path]:
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
    rel_path = alias_path.replace("@/", "", 1)

    for ext in _RESOLVE_EXTENSIONS:
        candidate = repo_path / (rel_path + ext)
        if candidate.exists():
            return candidate

    direct = repo_path / rel_path
    if direct.exists() and direct.is_file():
        return direct

    return None


def _clean_symbol(raw: str) -> Tuple[str, str]:
    """
    Clean a symbol from an import statement.
    Handles: 'Foo', 'type Foo', 'Foo as Bar'
    Returns (kind, clean_name) where kind is 'type' or 'named'.
    """
    raw = raw.strip()
    if raw.startswith("type "):
        raw = raw[5:].strip()
        kind = "type"
    else:
        kind = "named"

    # Handle 'as' alias — use the local name (before 'as')
    if " as " in raw:
        raw = raw.split(" as ")[0].strip()

    return kind, raw


def _find_missing_imports(repo_path: Path, files: List[Path]) -> Dict[str, Set[Tuple[str, str]]]:
    """
    Scan files for @/ imports and identify which ones don't resolve.

    Returns:
        Dict mapping alias_path -> set of (export_kind, symbol_name)
        export_kind is 'named', 'default', or 'type'
    """
    missing: Dict[str, Set[Tuple[str, str]]] = {}

    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        for m in _IMPORT_RE.finditer(content):
            named_group = m.group(1)   # { A, B, type C }
            default_group = m.group(2) # Foo
            alias_path = m.group(3)    # @/lib/foo

            if _resolve_import(repo_path, alias_path) is not None:
                continue

            if alias_path not in missing:
                missing[alias_path] = set()

            if named_group:
                # Check if this is `import type { ... }` (all symbols are types)
                is_type_only_import = "import type {" in m.group(0) or "import type{" in m.group(0)
                for sym in named_group.split(","):
                    kind, name = _clean_symbol(sym)
                    if is_type_only_import:
                        kind = "type"
                    if name:
                        missing[alias_path].add((kind, name))
            elif default_group:
                # Check it's not 'import type Foo from ...' (already handled by top-level type)
                # If the regex matched with the optional 'type' prefix, this is a type-only default
                full_match = m.group(0)
                if "import type " in full_match and "import type {" not in full_match:
                    missing[alias_path].add(("type", default_group))
                else:
                    missing[alias_path].add(("default", default_group))

    return missing


def _is_component_path(rel_path: str) -> bool:
    for segment in _COMPONENT_PATH_SEGMENTS:
        if segment in rel_path:
            return True
    basename = rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path
    return basename[0].isupper() if basename else False


def _create_stubs(
    repo_path: Path,
    missing: Dict[str, Set[Tuple[str, str]]],
) -> List[str]:
    """Create stub files for missing imports. Returns list of created file paths."""
    created = []

    for alias_path, exports in missing.items():
        rel_path = alias_path.replace("@/", "", 1)
        is_component = _is_component_path(rel_path)

        ext = ".tsx" if is_component else ".ts"
        target_file = rel_path + ext
        target_path = repo_path / target_file

        if target_path.exists():
            continue

        lines: List[str] = []

        if is_component:
            lines.append("'use client';")
            lines.append("")

        named_exports = [(kind, name) for kind, name in exports if kind == "named"]
        type_exports = [(kind, name) for kind, name in exports if kind == "type"]
        default_exports = [(kind, name) for kind, name in exports if kind == "default"]

        # Type exports → export as empty interfaces
        for _, name in sorted(type_exports, key=lambda x: x[1]):
            # eslint-disable to avoid unused-variable warnings
            lines.append(f"export interface {name} {{ [key: string]: any }}")
            lines.append("")

        # Named exports — use simple variable assignments (ESLint-safe)
        for _, name in sorted(named_exports, key=lambda x: x[1]):
            if is_component and name[0:1].isupper():
                lines.append(f"export function {name}(props: any) {{")
                lines.append(f'  return <div data-stub="{name}">{{/* stub */}}</div>;')
                lines.append("}")
            else:
                # Use /* eslint-disable */ for generated stubs to avoid parser issues
                lines.append(f"// eslint-disable-next-line @typescript-eslint/no-explicit-any")
                lines.append(f"export const {name}: any = undefined;")
            lines.append("")

        # Default export — ALSO add a named export with the same name for compatibility
        for _, name in default_exports:
            if is_component:
                lines.append(f"export default function {name}(props: any) {{")
                lines.append(f'  return <div data-stub="{name}">{{/* stub */}}</div>;')
                lines.append("}")
                # Also export as named so both `import X` and `import { X }` work
                lines.append(f"export {{ {name} }};")
            else:
                lines.append(f"export default function {name}(...args: any[]) {{")
                lines.append("  return undefined as any;")
                lines.append("}")
                lines.append(f"export {{ {name} }};")
            lines.append("")

        if not lines or all(line == "" or line.startswith("'use client'") for line in lines):
            comp_name = rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path
            if is_component:
                lines = [
                    "'use client';",
                    "",
                    f"export default function {comp_name}(props: any) {{",
                    f'  return <div data-stub="{comp_name}">{{/* stub */}}</div>;',
                    "}",
                    f"export {{ {comp_name} }};",
                    "",
                ]
            else:
                lines = [
                    "// eslint-disable-next-line @typescript-eslint/no-explicit-any",
                    f"const _default: any = undefined;",
                    "export default _default;",
                    "",
                ]

        # Add eslint-disable at top of non-component stubs to prevent parser issues
        if not is_component and lines and not lines[0].startswith("/* eslint"):
            lines.insert(0, "/* eslint-disable */")
            lines.insert(1, "")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(target_file)

    return created
