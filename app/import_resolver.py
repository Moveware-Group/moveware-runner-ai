"""
Pre-build Import Resolver

Scans source files for @/ aliased imports that don't resolve to existing files.
Creates minimal stub modules for missing imports so builds can proceed.

Reads tsconfig.json to determine the correct base path for the @/ alias
(e.g., ./src/* vs ./*).
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


_RESOLVE_EXTENSIONS = [".ts", ".tsx", "/index.ts", "/index.tsx", ".js", "/index.js"]

_COMPONENT_PATH_SEGMENTS = {"components/", "app/", "pages/", "views/", "layouts/", "screens/"}

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


def _get_alias_base(repo_path: Path) -> str:
    """
    Read tsconfig.json to determine what @/ maps to.
    Returns the base directory relative to repo_path (e.g., "src" or "").
    """
    for config_name in ["tsconfig.json", "tsconfig.app.json"]:
        config_path = repo_path / config_name
        if not config_path.exists():
            continue
        try:
            raw = config_path.read_text(encoding="utf-8")
            # Strip comments (// and /* ... */) for JSON parsing
            raw = re.sub(r'//.*?$', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.DOTALL)
            config = json.loads(raw)
            paths = config.get("compilerOptions", {}).get("paths", {})
            for key, values in paths.items():
                if key in ("@/*", "@*"):
                    if values and isinstance(values, list):
                        # Value like ["./src/*"] or ["./*"]
                        mapping = values[0].rstrip("*").rstrip("/").lstrip("./")
                        if mapping:
                            print(f"  📂 @/ alias maps to '{mapping}/' (from {config_name})")
                            return mapping
                        else:
                            return ""
        except Exception as e:
            print(f"  Warning: failed to parse {config_name}: {e}")

    # Heuristic: if src/ exists with components or lib, assume @/ -> src/
    if (repo_path / "src").is_dir():
        src_has_code = any(
            (repo_path / "src" / d).is_dir()
            for d in ["components", "lib", "app", "pages"]
        )
        if src_has_code:
            print(f"  📂 @/ alias inferred as 'src/' (src/ directory with code found)")
            return "src"

    return ""


def resolve_all_missing_imports(
    repo_path: Path,
    changed_files: Optional[List[str]] = None,
) -> List[str]:
    """
    Scan source files for @/ imports that don't resolve, create stubs for them,
    then repeat until no new missing imports are found.

    Returns:
        List of created stub file paths (relative to repo_path).
    """
    if not (repo_path / "tsconfig.json").exists():
        return []

    alias_base = _get_alias_base(repo_path)
    all_created: List[str] = []
    max_rounds = 5

    for round_num in range(1, max_rounds + 1):
        files_to_scan = _get_files_to_scan(repo_path, changed_files if round_num == 1 else None)
        missing = _find_missing_imports(repo_path, alias_base, files_to_scan)

        if not missing:
            break

        created_this_round = _create_stubs(repo_path, alias_base, missing)
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


def _resolve_import(repo_path: Path, alias_base: str, alias_path: str) -> Optional[Path]:
    """
    Try to resolve an @/ aliased import to an existing file.
    Respects the alias_base from tsconfig (e.g., 'src').
    """
    rel_path = alias_path.replace("@/", "", 1)

    # Try with alias base first (e.g., src/components/notes/NotesPanel)
    # then without (e.g., components/notes/NotesPanel) as fallback
    bases = []
    if alias_base:
        bases.append(alias_base + "/" + rel_path)
    bases.append(rel_path)

    for base_rel in bases:
        for ext in _RESOLVE_EXTENSIONS:
            candidate = repo_path / (base_rel + ext)
            if candidate.exists():
                return candidate

        direct = repo_path / base_rel
        if direct.exists() and direct.is_file():
            return direct

    return None


def _clean_symbol(raw: str) -> Tuple[str, str]:
    """
    Clean a symbol from an import statement.
    Handles: 'Foo', 'type Foo', 'Foo as Bar'
    Returns (kind, clean_name).
    """
    raw = raw.strip()
    if raw.startswith("type "):
        raw = raw[5:].strip()
        kind = "type"
    else:
        kind = "named"

    if " as " in raw:
        raw = raw.split(" as ")[0].strip()

    return kind, raw


def _find_missing_imports(
    repo_path: Path,
    alias_base: str,
    files: List[Path],
) -> Dict[str, Set[Tuple[str, str]]]:
    """
    Scan files for @/ imports and identify which ones don't resolve.
    """
    missing: Dict[str, Set[Tuple[str, str]]] = {}

    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        for m in _IMPORT_RE.finditer(content):
            named_group = m.group(1)
            default_group = m.group(2)
            alias_path = m.group(3)

            if _resolve_import(repo_path, alias_base, alias_path) is not None:
                continue

            if alias_path not in missing:
                missing[alias_path] = set()

            if named_group:
                is_type_only_import = "import type {" in m.group(0) or "import type{" in m.group(0)
                for sym in named_group.split(","):
                    kind, name = _clean_symbol(sym)
                    if is_type_only_import:
                        kind = "type"
                    if name:
                        missing[alias_path].add((kind, name))
            elif default_group:
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
    alias_base: str,
    missing: Dict[str, Set[Tuple[str, str]]],
) -> List[str]:
    """Create stub files for missing imports. Returns list of created file paths."""
    created = []

    for alias_path, exports in missing.items():
        rel_path = alias_path.replace("@/", "", 1)
        is_component = _is_component_path(rel_path)

        # Apply alias base: @/components/X -> src/components/X
        fs_rel_path = (alias_base + "/" + rel_path) if alias_base else rel_path

        ext = ".tsx" if is_component else ".ts"
        target_file = fs_rel_path + ext
        target_path = repo_path / target_file

        if target_path.exists():
            continue

        lines: List[str] = []

        if is_component:
            lines.append("'use client';")
            lines.append("")
        else:
            lines.append("/* eslint-disable */")
            lines.append("")

        named_exports = [(kind, name) for kind, name in exports if kind == "named"]
        type_exports = [(kind, name) for kind, name in exports if kind == "type"]
        default_exports = [(kind, name) for kind, name in exports if kind == "default"]

        for _, name in sorted(type_exports, key=lambda x: x[1]):
            lines.append(f"export interface {name} {{ [key: string]: any }}")
            lines.append("")

        for _, name in sorted(named_exports, key=lambda x: x[1]):
            if is_component and name[0:1].isupper():
                lines.append(f"export function {name}(props: any) {{")
                lines.append(f'  return <div data-stub="{name}">{{/* stub */}}</div>;')
                lines.append("}")
            else:
                lines.append(f"export const {name}: any = undefined;")
            lines.append("")

        for _, name in default_exports:
            if is_component:
                lines.append(f"export default function {name}(props: any) {{")
                lines.append(f'  return <div data-stub="{name}">{{/* stub */}}</div>;')
                lines.append("}")
                lines.append(f"export {{ {name} }};")
            else:
                lines.append(f"export default function {name}(...args: any[]) {{")
                lines.append("  return undefined as any;")
                lines.append("}")
                lines.append(f"export {{ {name} }};")
            lines.append("")

        if not lines or all(line in ("", "'use client';", "/* eslint-disable */") for line in lines):
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
                    "/* eslint-disable */",
                    "",
                    f"const _default: any = undefined;",
                    "export default _default;",
                    "",
                ]

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(target_file)

    return created
