"""
Proactive Type Context Extractor

Before code generation, reads type definitions, interfaces, and classes
that are likely to be needed based on the task description. This prevents
the LLM from guessing property names, function signatures, and class
shapes — the #1 cause of repeat build failures.

Strategy:
  1. Parse the task description for type/interface/class names
  2. Search the repository's src/ tree for matching definitions
  3. Return the exact source text so Claude sees the REAL API surface
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def extract_type_context(
    repo_path: Path,
    task_description: str,
    existing_context_files: Optional[Set[str]] = None,
    max_files: int = 15,
    max_chars_per_file: int = 4000,
) -> str:
    """
    Read type definitions referenced in the task and return their contents.

    Args:
        repo_path: Root of the target repository
        task_description: Jira summary + description
        existing_context_files: Files already included in context (skip these)
        max_files: Maximum extra files to read
        max_chars_per_file: Truncation limit per file

    Returns:
        Formatted context string, or "" if nothing found.
    """
    already = existing_context_files or set()
    desc = task_description

    # 1. Extract likely type/interface/class names from description
    type_names = _extract_type_names(desc)

    # 2. Extract file paths mentioned in description
    mentioned_files = _extract_file_paths(desc)

    # 3. Extract keywords that map to common file patterns
    keywords = _extract_keywords(desc)

    # 4. Search for matching files
    found_files: Dict[str, str] = {}  # path -> reason

    src_root = repo_path / "src"
    if not src_root.exists():
        src_root = repo_path

    # 4a. Mentioned files (highest priority)
    for mf in mentioned_files:
        candidates = [
            repo_path / mf,
            repo_path / "src" / mf,
        ]
        for c in candidates:
            rel = _try_relative(c, repo_path)
            if rel and c.exists() and c.is_file() and rel not in already:
                found_files[rel] = f"Referenced in task: {mf}"
                break

    # 4b. Type name search
    for type_name in type_names:
        if len(found_files) >= max_files:
            break
        matches = _find_type_definition(src_root, type_name, repo_path)
        for fpath, reason in matches:
            if fpath not in already and fpath not in found_files:
                found_files[fpath] = reason
                if len(found_files) >= max_files:
                    break

    # 4c. Keyword-based search
    for kw, patterns in keywords.items():
        if len(found_files) >= max_files:
            break
        for pat in patterns:
            fpath = repo_path / pat
            if fpath.exists() and fpath.is_file():
                rel = _try_relative(fpath, repo_path)
                if rel and rel not in already and rel not in found_files:
                    found_files[rel] = f"Keyword '{kw}' in task"

    if not found_files:
        return ""

    # 5. Build context string
    sections = [
        "**TYPE DEFINITIONS & INTERFACES (auto-detected from task description):**",
        "Read these carefully — use ONLY the properties and signatures defined here.\n",
    ]

    files_read = 0
    for fpath, reason in found_files.items():
        full = repo_path / fpath
        if not full.exists():
            continue
        try:
            content = full.read_text(encoding="utf-8")
            # Extract just type/interface/class blocks if file is large
            if len(content) > max_chars_per_file:
                content = _extract_type_blocks(content, type_names, max_chars_per_file)

            sections.append(f"**{fpath}** ({reason}):")
            sections.append("```typescript")
            sections.append(content[:max_chars_per_file])
            if len(content) > max_chars_per_file:
                sections.append("// ... truncated ...")
            sections.append("```")
            sections.append("")
            files_read += 1
        except Exception:
            continue

    if files_read == 0:
        return ""

    sections.append(
        "**CRITICAL:** The types above are the AUTHORITATIVE source. "
        "Use ONLY the properties, methods, and signatures defined here. "
        "Do NOT invent properties that don't exist in these definitions.\n"
    )
    return "\n".join(sections)


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _extract_type_names(desc: str) -> List[str]:
    """Extract PascalCase identifiers likely to be type/interface/class names."""
    names: List[str] = []
    seen: Set[str] = set()

    # Explicit patterns: "type X", "interface X", "class X"
    for m in re.finditer(r'(?:type|interface|class|model)\s+([A-Z]\w{2,})', desc):
        name = m.group(1)
        if name not in seen:
            names.append(name)
            seen.add(name)

    # PascalCase words (at least 2 uppercase transitions) like MovewareClient, TenantSettings
    for m in re.finditer(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', desc):
        name = m.group(1)
        if name not in seen and name not in ("JavaScript", "TypeScript", "NextAuth"):
            names.append(name)
            seen.add(name)

    # Words ending with common suffixes
    for m in re.finditer(r'\b(\w+(?:Config|Options|Props|Params|Input|Output|Result|Response|Request|Type|Interface|Client|Service|Repository|Factory|Handler|Provider|Context|State|Store|Schema))\b', desc):
        name = m.group(1)
        if name not in seen and name[0].isupper():
            names.append(name)
            seen.add(name)

    return names


def _extract_file_paths(desc: str) -> List[str]:
    """Extract file paths from the task description."""
    paths = []
    for m in re.finditer(r'(?:^|\s)((?:src/|lib/|app/|services/|components/|utils/|types/)?[\w/.-]+\.(?:ts|tsx|js|jsx|prisma|css))', desc):
        paths.append(m.group(1))
    return paths


def _extract_keywords(desc: str) -> Dict[str, List[str]]:
    """Map task keywords to likely file patterns."""
    kw_map: Dict[str, List[str]] = {}
    desc_lower = desc.lower()

    mappings = {
        "moveware": [
            "src/services/moveware.ts", "src/lib/moveware.ts",
            "src/types/moveware.ts", "src/lib/services/moveware.ts",
        ],
        "credential": [
            "src/services/moveware.ts", "src/lib/db/repositories/credential.ts",
            "src/types/moveware.ts",
        ],
        "tenant": [
            "src/lib/db/repositories/tenant.ts", "src/types/tenant.ts",
            "src/services/tenant.ts",
        ],
        "session": [
            "src/lib/auth/session.ts", "src/lib/db/repositories/session.ts",
        ],
        "auth": [
            "src/lib/auth.ts", "src/lib/auth/session.ts",
            "src/middleware.ts",
        ],
        "branding": [
            "src/services/branding.ts", "src/lib/services/brandingService.ts",
        ],
        "factory": [
            "src/services/moveware.ts", "src/lib/moveware.ts",
        ],
        "lru": [
            "src/services/moveware.ts", "src/lib/cache.ts",
        ],
    }

    for kw, files in mappings.items():
        if kw in desc_lower:
            kw_map[kw] = files

    return kw_map


def _find_type_definition(
    search_root: Path,
    type_name: str,
    repo_root: Path,
) -> List[Tuple[str, str]]:
    """Search for a type/interface/class definition in the source tree."""
    results: List[Tuple[str, str]] = []
    pattern = re.compile(
        rf'(?:export\s+)?(?:type|interface|class|enum)\s+{re.escape(type_name)}\b',
        re.MULTILINE,
    )

    # Also search for const X = ... patterns (factory functions, etc.)
    const_pattern = re.compile(
        rf'(?:export\s+)?(?:const|function|async\s+function)\s+\w*{re.escape(type_name)}\w*\b',
        re.IGNORECASE | re.MULTILINE,
    )

    extensions = {".ts", ".tsx", ".js", ".jsx"}

    try:
        for fpath in search_root.rglob("*"):
            if not fpath.is_file() or fpath.suffix not in extensions:
                continue
            if "node_modules" in fpath.parts or ".next" in fpath.parts:
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
                rel = str(fpath.relative_to(repo_root))
                if pattern.search(text):
                    results.append((rel, f"Defines {type_name}"))
                elif const_pattern.search(text):
                    results.append((rel, f"References {type_name}"))
            except Exception:
                continue
            if len(results) >= 5:
                break
    except Exception:
        pass

    return results


def _extract_type_blocks(
    content: str,
    type_names: List[str],
    max_chars: int,
) -> str:
    """Extract type/interface/class blocks from a large file."""
    lines = content.split("\n")
    blocks: List[str] = []
    total = 0

    # Always include imports (first 30 lines or until blank line after imports)
    import_end = 0
    for i, line in enumerate(lines[:50]):
        if line.strip().startswith(("import ", "from ", "export {", "export type {")):
            import_end = i + 1
        elif import_end > 0 and not line.strip():
            break
    if import_end > 0:
        import_block = "\n".join(lines[:import_end])
        blocks.append(import_block)
        total += len(import_block)

    # Find type/interface/class/export blocks
    i = import_end
    while i < len(lines) and total < max_chars:
        line = lines[i]
        # Check if this line starts a relevant block
        is_relevant = False
        for tn in type_names:
            if tn in line:
                is_relevant = True
                break
        if not is_relevant:
            for kw in ("export interface", "export type", "export class", "export enum", "export function", "export const", "export async"):
                if line.strip().startswith(kw):
                    is_relevant = True
                    break

        if is_relevant:
            block_lines = [line]
            brace_count = line.count("{") - line.count("}")
            j = i + 1
            while j < len(lines) and (brace_count > 0 or not block_lines[-1].strip()):
                block_lines.append(lines[j])
                brace_count += lines[j].count("{") - lines[j].count("}")
                j += 1
                if len("\n".join(block_lines)) > max_chars // 3:
                    block_lines.append("  // ... truncated ...")
                    break
            block = "\n".join(block_lines)
            blocks.append(block)
            total += len(block)
            i = j
        else:
            i += 1

    return "\n\n".join(blocks)


def _try_relative(path: Path, root: Path) -> Optional[str]:
    """Return relative path string or None."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return None
