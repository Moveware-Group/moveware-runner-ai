"""
Expanded Auto-Fix Library

Automatically fixes common build errors without needing AI intervention.
Each auto-fix is pattern-matched and can be applied instantly.
"""
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def try_all_auto_fixes(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Try all known auto-fixes for the given error.
    
    Args:
        error_msg: The build error message
        repo_path: Path to the repository
        is_node_project: Whether this is a Node.js project
    
    Returns:
        (success, description) - True if fix was applied, with description
    """
    auto_fixes = [
        auto_fix_zod_query_param_coerce,
        auto_fix_duplicate_module_declaration,
        auto_fix_eslint_rule_not_found,
        auto_fix_missing_export,
        auto_fix_prisma_schema_mismatch,
        auto_fix_prisma_null_assignment,
        auto_fix_module_not_found_stub,
        auto_fix_hardcoded_secrets,
        auto_fix_missing_npm_package,
        auto_fix_eslint_config_package,
        auto_fix_prettier_formatting,
        auto_fix_prisma_model_missing,
        auto_fix_prisma_generate,
        auto_fix_prisma_import_type,
        auto_fix_env_type_missing,
        auto_fix_type_conversion,
        auto_fix_index_signature_mismatch,
        auto_fix_missing_typescript_types,
        auto_fix_outdated_lockfile,
        auto_fix_port_in_use,
        auto_fix_missing_gitignore_entries,
        auto_fix_circular_dependency,
        auto_fix_missing_tailwind_config,
        auto_fix_nextjs_image_domains,
        auto_fix_cors_configuration,
        auto_fix_nextjs_route_export,
        auto_fix_import_path_leading_slash,
        auto_fix_component_props_mismatch,
        auto_fix_intrinsic_attributes,
        auto_fix_double_prefix_import,
        auto_fix_phantom_import,
        auto_fix_jsx_no_undef,
    ]
    
    all_applied = []
    for auto_fix_func in auto_fixes:
        try:
            success, description = auto_fix_func(error_msg, repo_path, is_node_project)
            if success:
                print(f"✅ Auto-fix applied: {description}")
                all_applied.append(description)
        except Exception as e:
            print(f"Warning: Auto-fix {auto_fix_func.__name__} failed: {e}")
            continue
    
    if all_applied:
        return True, "; ".join(all_applied)
    return False, ""


def auto_fix_missing_export(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Auto-fix missing export errors by reading the source module and either:
    1. Adding 'export' to an existing declaration, or
    2. Fixing the import to use the correct exported name.

    Handles:
    - "'findSessionByToken' is not exported from '@/lib/db/repositories/session'"
    - "Module '@/lib/...' has no exported member 'X'"
    """
    if not is_node_project:
        return False, ""

    # Pattern: 'symbolName' is not exported from 'modulePath'
    match = re.search(
        r"['\"](\w+)['\"] is not exported from ['\"]([^'\"]+)['\"]",
        error_msg,
    )
    if not match:
        # Pattern: Module "path" has no exported member "symbol"
        match = re.search(
            r"Module ['\"]([^'\"]+)['\"] has no exported member ['\"](\w+)['\"]",
            error_msg,
        )
        if match:
            # Groups are swapped in this pattern
            missing_symbol = match.group(2)
            module_path = match.group(1)
        else:
            return False, ""
    else:
        missing_symbol = match.group(1)
        module_path = match.group(2)

    # Skip @prisma/client errors (handled by prisma_generate)
    if "@prisma/client" in module_path:
        return False, ""

    # Resolve module path to file
    # Handle @/ alias → src/ or root
    resolved_path = module_path
    if resolved_path.startswith("@/"):
        resolved_path = resolved_path[2:]  # strip @/
        # Try src/ prefix first, then root
        candidates = [
            repo_path / "src" / resolved_path,
            repo_path / resolved_path,
        ]
    elif resolved_path.startswith("./") or resolved_path.startswith("../"):
        # Relative path — need the importing file to resolve
        importing_file_match = re.search(r'\./([^\s:]+\.(?:ts|tsx|js|jsx)):', error_msg)
        if importing_file_match:
            importing_dir = (repo_path / importing_file_match.group(1)).parent
            candidates = [importing_dir / resolved_path]
        else:
            return False, ""
    else:
        candidates = [repo_path / resolved_path]

    # Try extensions
    source_file = None
    for candidate in candidates:
        for ext in ['', '.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx']:
            test_path = Path(str(candidate) + ext)
            if test_path.exists() and test_path.is_file():
                source_file = test_path
                break
        if source_file:
            break

    if not source_file:
        return False, ""

    try:
        content = source_file.read_text(encoding="utf-8")

        # Strategy 1: Symbol exists but isn't exported — add 'export'
        # Look for: function symbolName, const symbolName, class symbolName, etc.
        non_exported = re.search(
            rf'^(\s*)(?:async\s+)?(?:function|const|let|var|class|interface|type|enum)\s+{re.escape(missing_symbol)}\b',
            content,
            re.MULTILINE,
        )
        if non_exported:
            indent = non_exported.group(1)
            old_line = non_exported.group(0)
            new_line = old_line.replace(indent, indent + "export ", 1) if indent else "export " + old_line.lstrip()
            new_content = content.replace(old_line, new_line, 1)
            source_file.write_text(new_content, encoding="utf-8")
            rel_path = source_file.relative_to(repo_path)
            return True, f"Added 'export' to {missing_symbol} in {rel_path}"

        # Strategy 2: Symbol doesn't exist — find similar names (case mismatch)
        # Extract all exported names
        exported = re.findall(
            r'export\s+(?:async\s+)?(?:function|const|let|var|class|interface|type|enum)\s+(\w+)',
            content,
        )
        exported += re.findall(r'export\s*\{\s*([^}]+)\}', content)
        all_exports = []
        for e in exported:
            if ',' in e:
                all_exports.extend([x.strip().split(' as ')[0].strip() for x in e.split(',')])
            else:
                all_exports.append(e.strip())

        # Case-insensitive match
        for exp_name in all_exports:
            if exp_name.lower() == missing_symbol.lower() and exp_name != missing_symbol:
                importing_match = re.search(r'\./([^\s:]+\.(?:ts|tsx|js|jsx)):', error_msg)
                if importing_match:
                    imp_file = repo_path / importing_match.group(1)
                    if imp_file.exists():
                        imp_content = imp_file.read_text(encoding="utf-8")
                        new_imp = imp_content.replace(missing_symbol, exp_name)
                        if new_imp != imp_content:
                            imp_file.write_text(new_imp, encoding="utf-8")
                            return True, f"Fixed import: {missing_symbol} → {exp_name} (case mismatch)"

        # Strategy 3: Module has `export default` but import uses named import `{ X }`
        has_default = bool(re.search(
            rf'export\s+default\s+(?:function|class|const)?\s*{re.escape(missing_symbol)}\b',
            content,
        )) or bool(re.search(
            rf'export\s+default\s+(?:function|class)\s+\w+',
            content,
        )) or "export default" in content

        if has_default:
            fixed_count = 0
            # Fix ALL files that use `import { symbol } from 'module'`
            for ts_file in repo_path.rglob("*.tsx"):
                if "node_modules" in str(ts_file) or ".next" in str(ts_file):
                    continue
                try:
                    fc = ts_file.read_text(encoding="utf-8")
                    # Match: import { CRMLayout } from '..path..'  or  import { CRMLayout, Other } from '..path..'
                    # We need to handle both sole named import and mixed
                    pattern = rf"import\s+\{{\s*{re.escape(missing_symbol)}\s*\}}\s+from\s+(['\"][^'\"]+['\"])"
                    m = re.search(pattern, fc)
                    if m:
                        old_import = m.group(0)
                        from_path = m.group(1)
                        new_import = f"import {missing_symbol} from {from_path}"
                        fc = fc.replace(old_import, new_import, 1)
                        ts_file.write_text(fc, encoding="utf-8")
                        fixed_count += 1
                except Exception:
                    continue
            # Also check .ts files
            for ts_file in repo_path.rglob("*.ts"):
                if "node_modules" in str(ts_file) or ".next" in str(ts_file):
                    continue
                try:
                    fc = ts_file.read_text(encoding="utf-8")
                    pattern = rf"import\s+\{{\s*{re.escape(missing_symbol)}\s*\}}\s+from\s+(['\"][^'\"]+['\"])"
                    m = re.search(pattern, fc)
                    if m:
                        old_import = m.group(0)
                        from_path = m.group(1)
                        new_import = f"import {missing_symbol} from {from_path}"
                        fc = fc.replace(old_import, new_import, 1)
                        ts_file.write_text(fc, encoding="utf-8")
                        fixed_count += 1
                except Exception:
                    continue

            if fixed_count > 0:
                rel = source_file.relative_to(repo_path)
                return True, f"Fixed {fixed_count} file(s): {missing_symbol} is default export in {rel}, changed named imports to default"

    except Exception as e:
        print(f"auto_fix_missing_export failed: {e}")

    return False, ""


def auto_fix_intrinsic_attributes(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool,
) -> Tuple[bool, str]:
    """
    Fix: Type '{ prop: any; }' is not assignable to type 'IntrinsicAttributes'.
    This means the component was defined without accepting props.
    Add `props: any` to the component's function signature.
    """
    if not is_node_project:
        return False, ""

    # Pattern: Property 'X' does not exist on type 'IntrinsicAttributes'.
    # preceding line has: <ComponentName prop={...} />
    match = re.search(
        r"not assignable to type ['\"]IntrinsicAttributes['\"].*?"
        r"Property ['\"](\w+)['\"] does not exist",
        error_msg, re.DOTALL,
    )
    if not match:
        return False, ""

    # Find the file and component from the error
    file_match = re.search(
        r"\./([\w/.[\]-]+\.tsx?)[:\(]",
        error_msg,
    )
    if not file_match:
        return False, ""

    error_file = repo_path / file_match.group(1)
    if not error_file.exists():
        return False, ""

    content = error_file.read_text(encoding="utf-8")

    # Find the JSX usage: <ComponentName prop={...} />
    # Extract the component name from error context
    comp_match = re.search(
        r"<(\w+)\s+\w+\s*=",
        error_msg,
    )
    if not comp_match:
        return False, ""

    component_name = comp_match.group(1)

    # Find the component's source file by scanning imports in the error file
    import_match = re.search(
        rf"import\s+(?:\{{[^}}]*\}}|\w+)\s+from\s+['\"]([^'\"]+)['\"]",
        content,
    )

    # Search for the component definition across all likely files
    for pattern in ["**/*.tsx", "**/*.ts"]:
        for f in repo_path.glob(pattern):
            rel = str(f.relative_to(repo_path))
            if "node_modules" in rel or ".next" in rel:
                continue
            try:
                src = f.read_text(encoding="utf-8")
            except Exception:
                continue

            # Match: export default function ComponentName() {
            # or:    export function ComponentName() {
            func_pattern = re.compile(
                rf"(export\s+(?:default\s+)?function\s+{re.escape(component_name)})\s*\(\s*\)",
            )
            m = func_pattern.search(src)
            if m:
                new_src = func_pattern.sub(
                    rf"\1(props: any)",
                    src,
                    count=1,
                )
                if new_src != src:
                    f.write_text(new_src, encoding="utf-8")
                    rel_path = str(f.relative_to(repo_path))
                    return True, f"Added `props: any` to {component_name} in {rel_path}"

            # Match: const ComponentName = () => {
            arrow_pattern = re.compile(
                rf"((?:export\s+)?(?:const|let)\s+{re.escape(component_name)}\s*=\s*)\(\s*\)\s*(?::\s*\w+\s*)?=>",
            )
            m = arrow_pattern.search(src)
            if m:
                new_src = arrow_pattern.sub(
                    lambda ma: ma.group(0).replace("()", "(props: any)", 1),
                    src,
                    count=1,
                )
                if new_src != src:
                    f.write_text(new_src, encoding="utf-8")
                    rel_path = str(f.relative_to(repo_path))
                    return True, f"Added `props: any` to {component_name} in {rel_path}"

    return False, ""


def auto_fix_double_prefix_import(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix '@/src/...' double-prefix imports.
    When tsconfig maps @ to src/, '@/src/foo' resolves to 'src/src/foo' which doesn't exist.
    Fix: replace '@/src/' with '@/'.
    """
    if not is_node_project:
        return False, ""

    match = re.search(
        r"(?:Cannot find module|Module not found: Can't resolve)\s+['\"](@/src/[^'\"\s]+)['\"]",
        error_msg,
        re.IGNORECASE,
    )
    if not match:
        return False, ""

    bad_import = match.group(1)  # e.g. @/src/components/customers/Foo
    good_import = bad_import.replace("@/src/", "@/", 1)

    # Find which file has this import
    file_match = re.search(r'\./([^\s:]+\.tsx?)', error_msg)
    if not file_match:
        return False, ""

    error_file = repo_path / file_match.group(1)
    if not error_file.exists():
        return False, ""

    try:
        content = error_file.read_text(encoding="utf-8")
        if bad_import not in content:
            return False, ""
        new_content = content.replace(bad_import, good_import)
        error_file.write_text(new_content, encoding="utf-8")
        return True, f"Fixed double-prefix import: '{bad_import}' → '{good_import}' in {file_match.group(1)}"
    except Exception:
        return False, ""


def _find_interface_closing_brace(content: str, open_brace_pos: int) -> int:
    """Find the matching closing brace for an interface/type, handling nested braces."""
    depth = 1
    i = open_brace_pos + 1
    in_string = False
    string_char = None
    while i < len(content) and depth > 0:
        ch = content[i]
        if in_string:
            if ch == string_char and (i == 0 or content[i - 1] != '\\'):
                in_string = False
            i += 1
            continue
        if ch in ('"', "'", '`'):
            in_string = True
            string_char = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else -1


def auto_fix_component_props_mismatch(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    When page.tsx passes props that don't exist on a component's Props interface,
    add ALL missing props to the interface in ALL copies of the file.
    """
    if not is_node_project:
        return False, ""

    # Match both ASCII and Unicode quote styles
    match = re.search(
        r"Property\s+['\u2018\u2019](\w+)['\u2018\u2019]\s+does not exist on type\s+['\u2018\u2019](?:IntrinsicAttributes & )?(\w+Props)['\u2018\u2019]",
        error_msg,
    )
    if not match:
        return False, ""

    props_type = match.group(2)
    print(f"  [props-autofix] Matched Props type: {props_type}")

    # Extract ALL props from the type object in the error message
    type_obj_match = re.search(
        r"Type\s+['\u2018]\{([^}]+)\}['\u2019]\s+is not assignable",
        error_msg,
    )
    
    all_passed_props: dict = {}
    if type_obj_match:
        for prop_match in re.finditer(r'(\w+)\s*:\s*([^;]+)', type_obj_match.group(1)):
            all_passed_props[prop_match.group(1)] = prop_match.group(2).strip()
        print(f"  [props-autofix] Parsed {len(all_passed_props)} props from type object")
    
    # Find explicitly named missing props
    explicit_missing = set()
    for m in re.finditer(
        r"Property\s+['\u2018\u2019](\w+)['\u2018\u2019]\s+does not exist on type\s+['\u2018\u2019](?:IntrinsicAttributes & )?"
        + re.escape(props_type),
        error_msg,
    ):
        explicit_missing.add(m.group(1))
    print(f"  [props-autofix] Explicitly missing: {explicit_missing}")

    # Find ALL files that define this Props type (there may be copies in src/ and root)
    import os
    props_files: list = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".next", ".git", "dist", "build")]
        for f in files:
            if f.endswith((".ts", ".tsx")):
                full = Path(root) / f
                try:
                    content = full.read_text(encoding="utf-8", errors="ignore")
                    if re.search(rf"(?:interface|type)\s+{re.escape(props_type)}\s*[{{=]", content):
                        props_files.append((full, content))
                        print(f"  [props-autofix] Found {props_type} in {full.relative_to(repo_path)}")
                except Exception:
                    continue

    if not props_files:
        print(f"  [props-autofix] No files found containing {props_type}")
        return False, ""

    total_modified = 0
    modified_paths = []

    for props_file, props_content in props_files:
        # Find the interface/type opening brace using brace counting (handles nested types)
        iface_match = re.search(
            rf"(?:interface|type)\s+{re.escape(props_type)}\s*(?:=\s*)?\{{",
            props_content,
        )
        if not iface_match:
            print(f"  [props-autofix] Could not find interface opening brace in {props_file.name}")
            continue

        open_brace = iface_match.end() - 1
        close_brace = _find_interface_closing_brace(props_content, open_brace)
        if close_brace < 0:
            print(f"  [props-autofix] Could not find matching closing brace in {props_file.name}")
            continue

        interface_body = props_content[open_brace:close_brace + 1]

        # Determine which props need to be added
        props_to_add = []
        
        for prop_name, prop_type in all_passed_props.items():
            if not re.search(rf"\b{re.escape(prop_name)}\s*[?:]", interface_body):
                props_to_add.append((prop_name, prop_type))
        
        for prop_name in explicit_missing:
            if not any(p[0] == prop_name for p in props_to_add):
                if not re.search(rf"\b{re.escape(prop_name)}\s*[?:]", interface_body):
                    if "hasmore" in prop_name.lower():
                        inferred = "boolean"
                    elif prop_name.startswith("initial"):
                        inferred = "any[]"
                    else:
                        inferred = "any"
                    props_to_add.append((prop_name, inferred))
        
        if not props_to_add:
            print(f"  [props-autofix] No props to add in {props_file.name} (all already present)")
            continue

        # Sanitize prop types — only use types that are already imported/available in the file
        _primitive_types = {"string", "number", "boolean", "any", "unknown", "void", "null", "undefined", "never", "object"}
        _safe_patterns = {"any[]", "string[]", "number[]", "boolean[]", "Record<string, any>", "React.ReactNode"}

        def _sanitize_type(prop_type: str, file_content: str) -> str:
            """Replace unresolvable type references with 'any'."""
            clean = prop_type.strip().rstrip(";")
            if clean in _primitive_types or clean in _safe_patterns:
                return clean
            if clean.endswith("[]"):
                inner = clean[:-2]
                if inner in _primitive_types:
                    return clean
                # Check if the type is imported or declared in this file
                if re.search(rf"\b{re.escape(inner)}\b", file_content[:file_content.find("export") if "export" in file_content else len(file_content)]):
                    return clean
                return "any[]"
            # For complex types, check if the base name is available
            base_type = re.match(r"(\w+)", clean)
            if base_type:
                type_name = base_type.group(1)
                if type_name in _primitive_types:
                    return clean
                if re.search(rf"(?:import|interface|type|class|enum)\s+.*?\b{re.escape(type_name)}\b", file_content):
                    return clean
            return "any"

        # Insert new props just before the closing brace
        new_lines = ""
        for prop_name, prop_type in props_to_add:
            safe_type = _sanitize_type(prop_type, props_content)
            new_lines += f"  {prop_name}?: {safe_type};\n"

        new_content = (
            props_content[:close_brace]
            + new_lines
            + props_content[close_brace:]
        )

        props_file.write_text(new_content, encoding="utf-8")
        rel_path = str(props_file.relative_to(repo_path)).replace("\\", "/")
        modified_paths.append(rel_path)
        total_modified += len(props_to_add)
        print(f"  [props-autofix] Added {len(props_to_add)} props to {rel_path}")

    if total_modified == 0:
        return False, ""

    added_names = list(set(p[0] for p in props_to_add)) if props_to_add else list(explicit_missing)
    names_str = ", ".join(added_names[:5])
    files_str = ", ".join(modified_paths)
    return True, f"Added {total_modified} props ({names_str}) to {props_type} in {files_str}"


def _resolve_local_import(repo_path: Path, import_path: str) -> bool:
    """Check if a local import (@/ or ./) resolves to an existing file."""
    if import_path.startswith("@/"):
        rel = import_path[2:]  # strip @/
        base = repo_path / rel
    elif import_path.startswith("./") or import_path.startswith("../"):
        return True  # relative imports are harder to check, skip
    else:
        return True  # not a local import

    extensions = ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]
    for ext in extensions:
        if (base.parent / (base.name + ext)).exists():
            return True
    # Also check src/ prefix since @/ can map to src/
    src_base = repo_path / "src" / rel
    for ext in extensions:
        if (src_base.parent / (src_base.name + ext)).exists():
            return True
    return False


def auto_fix_phantom_import(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Remove import lines that reference non-existent local modules.
    When triggered, proactively scans ALL imports in the affected file(s)
    and removes any that don't resolve — prevents cascading Module not found errors.
    """
    if not is_node_project:
        return False, ""

    # Match: Cannot find module '@/path/to/Module' in a specific file
    match = re.search(
        r"(?:Cannot find module|Module not found: Can't resolve)\s+['\"](@/[^'\"\s]+|\.{1,2}/[^'\"\s]+)['\"]",
        error_msg,
        re.IGNORECASE,
    )
    if not match:
        return False, ""

    # Find which file has this import
    file_match = re.search(r'\./([^\s:]+\.tsx?)', error_msg)
    if not file_match:
        return False, ""

    error_file = repo_path / file_match.group(1)
    if not error_file.exists():
        return False, ""

    all_removed = []
    files_fixed = []

    # Also check the same filename under src/ (duplicate file issue)
    candidate_files = [error_file]
    src_variant = repo_path / "src" / file_match.group(1)
    if src_variant.exists() and src_variant != error_file:
        candidate_files.append(src_variant)
    nosrc_variant = repo_path / file_match.group(1).replace("src/", "", 1) if "src/" in file_match.group(1) else None
    if nosrc_variant and nosrc_variant.exists() and nosrc_variant not in candidate_files:
        candidate_files.append(nosrc_variant)

    for target_file in candidate_files:
        try:
            content = target_file.read_text(encoding="utf-8")
            lines = content.split('\n')
            new_lines = []
            removed_in_file = []

            removed_symbols = set()
            for line in lines:
                # Extract import path from this line
                imp_match = re.search(r"""(?:from|import)\s+['"](@/[^'"]+|\.{1,2}/[^'"]+)['"]""", line)
                if imp_match:
                    imp_path = imp_match.group(1)
                    if not _resolve_local_import(repo_path, imp_path):
                        removed_in_file.append(imp_path)
                        # Extract imported symbol names to remove JSX usage
                        sym_match = re.search(r'import\s+\{([^}]+)\}', line)
                        if sym_match:
                            for sym in sym_match.group(1).split(','):
                                removed_symbols.add(sym.strip().split(' as ')[-1].strip())
                        # Default import
                        def_match = re.search(r'import\s+(\w+)\s+from', line)
                        if def_match:
                            removed_symbols.add(def_match.group(1))
                        continue
                new_lines.append(line)

            # Remove JSX usage of removed components: <ComponentName ...> and </ComponentName>
            if removed_symbols:
                filtered = []
                for line in new_lines:
                    skip = False
                    for sym in removed_symbols:
                        if re.search(rf'</?{re.escape(sym)}[\s/>]', line):
                            skip = True
                            break
                    if not skip:
                        filtered.append(line)
                    else:
                        # Replace with empty fragment to preserve structure
                        stripped = line.lstrip()
                        if stripped.startswith('</'):
                            continue  # closing tag, just remove
                        indent = line[:len(line) - len(stripped)]
                        filtered.append(f"{indent}{{/* removed: {stripped.strip()} */}}")
                new_lines = filtered

            if removed_in_file:
                target_file.write_text('\n'.join(new_lines), encoding="utf-8")
                rel_path = target_file.relative_to(repo_path)
                files_fixed.append(str(rel_path))
                all_removed.extend(removed_in_file)
        except Exception:
            continue

    if all_removed:
        summary = f"Removed {len(all_removed)} phantom import(s) ({', '.join(all_removed[:3])}) from {', '.join(files_fixed)}"
        return True, summary
    return False, ""


def auto_fix_import_path_leading_slash(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix 'Module not found: Can't resolve \'/lib/...\'' by replacing leading-slash
    imports with @/lib/... (Next.js/Webpack treat /lib as absolute filesystem path).
    """
    if not is_node_project:
        return False, ""
    match = re.search(
        r"Module not found(?::\s*Error)?:?\s*Can't resolve\s+['\"](/lib/[^'\"\s]+)['\"]",
        error_msg,
        re.IGNORECASE,
    )
    if not match:
        return False, ""
    bad_path = match.group(1)  # e.g. /lib/api/tenant-credentials
    correct_path = "@" + bad_path  # @/lib/api/tenant-credentials

    # Find the file with the bad import (./app/..., /app/..., or app/...)
    file_match = re.search(
        r'(?:\./|/)((?:app|src|lib|components)/[^\s:]+\.(?:ts|tsx|js|jsx))(?::\d|$|\s)',
        error_msg,
    )
    if not file_match:
        return False, ""
    rel_path = file_match.group(1)
    fp = repo_path / rel_path
    if not fp.exists():
        return False, ""

    content = fp.read_text(encoding="utf-8")
    # Replace both quoted forms
    old1 = f"'{bad_path}'"
    old2 = f'"{bad_path}"'
    new1 = f"'{correct_path}'"
    new2 = f'"{correct_path}"'
    if old1 in content:
        content = content.replace(old1, new1, 1)
    elif old2 in content:
        content = content.replace(old2, new2, 1)
    else:
        return False, ""

    fp.write_text(content, encoding="utf-8")
    return True, f"Fixed import path {bad_path} → {correct_path} in {rel_path}"


def auto_fix_prisma_schema_mismatch(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Auto-fix Prisma schema mismatch errors by removing invalid
    relations/fields from include/select/where clauses.

    Handles:
    - "Object literal may only specify known properties, and 'tenant'
       does not exist in type 'SessionInclude<DefaultArgs>'"
    """
    if not is_node_project:
        return False, ""

    # Pattern: 'propertyName' does not exist in type 'ModelInclude/Select/Where/Create/Update'
    match = re.search(
        r"['\"](\w+)['\"] does not exist in type ['\"](\w+?)(?:Include|Select|Where|CreateInput|UpdateInput)",
        error_msg,
    )
    if not match:
        # Alternate pattern from "Object literal may only specify known properties"
        match = re.search(
            r"Object literal may only specify known properties,? and ['\"](\w+)['\"] does not exist in type ['\"](\w+?)(?:Include|Select|Where|Create|Update)",
            error_msg,
        )
    if not match:
        return False, ""

    invalid_prop = match.group(1)
    model_name = match.group(2)

    # Find the file with the error
    file_match = re.search(r'\./([^\s:]+\.(?:ts|tsx|js|jsx)):(\d+)', error_msg)
    if not file_match:
        # Try src/ prefix pattern
        file_match = re.search(r'(src/[^\s:]+\.(?:ts|tsx|js|jsx)):(\d+)', error_msg)
    if not file_match:
        return False, ""

    file_rel = file_match.group(1)
    error_line = int(file_match.group(2))
    file_path = repo_path / file_rel

    if not file_path.exists():
        return False, ""

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        if error_line < 1 or error_line > len(lines):
            return False, ""

        # Find the line with the invalid property and remove it
        # Look around the error line for the property
        search_start = max(0, error_line - 3)
        search_end = min(len(lines), error_line + 3)

        for i in range(search_start, search_end):
            line = lines[i]
            stripped = line.strip()

            # Match: "invalid_prop: { ... }" or "invalid_prop: true" or "invalid_prop: { select: ... }"
            prop_pattern = rf'^\s*{re.escape(invalid_prop)}\s*:\s*'
            if re.match(prop_pattern, stripped):
                # Check if this is a multi-line block (e.g., tenant: { select: { ... } })
                if '{' in stripped:
                    # Count braces to find the end of the block
                    brace_count = stripped.count('{') - stripped.count('}')
                    end_i = i
                    while brace_count > 0 and end_i + 1 < len(lines):
                        end_i += 1
                        brace_count += lines[end_i].count('{') - lines[end_i].count('}')
                    # Remove lines i through end_i
                    removed = lines[i:end_i + 1]
                    del lines[i:end_i + 1]
                else:
                    # Single-line property
                    removed = [lines[i]]
                    del lines[i]

                # Clean up trailing comma on the preceding line if needed
                if i > 0 and i <= len(lines):
                    prev = lines[i - 1].rstrip()
                    if prev.endswith(',') and (i >= len(lines) or lines[i].strip().startswith('}')):
                        lines[i - 1] = prev[:-1] + "\n" if prev.endswith(',\n') else prev[:-1]

                # Also remove downstream references to this property (e.g. account.refreshTokenEncrypted)
                # that would cause "Property 'X' does not exist on type" errors
                downstream_removed = 0
                new_content = "\n".join(lines)
                downstream_pattern = re.compile(
                    rf'(?:^.*?\b\w+\.{re.escape(invalid_prop)}\b.*$)',
                    re.MULTILINE,
                )
                for dm in downstream_pattern.finditer(new_content):
                    line_text = dm.group(0).strip()
                    if line_text.startswith("//") or line_text.startswith("*"):
                        continue
                    downstream_removed += 1

                if downstream_removed > 0:
                    new_content = downstream_pattern.sub(
                        lambda m: f"// AUTO-REMOVED: {m.group(0).strip()}  // '{invalid_prop}' not in {model_name} schema"
                        if not m.group(0).strip().startswith("//") and not m.group(0).strip().startswith("*")
                        else m.group(0),
                        new_content,
                    )
                    print(f"  Also commented out {downstream_removed} downstream reference(s) to '{invalid_prop}'")

                file_path.write_text(new_content, encoding="utf-8")
                removed_preview = removed[0].strip()[:60]
                desc = f"Removed invalid '{invalid_prop}' from {model_name} query in {file_rel} ({removed_preview})"
                if downstream_removed > 0:
                    desc += f" + {downstream_removed} downstream ref(s)"
                return True, desc

    except Exception as e:
        print(f"auto_fix_prisma_schema_mismatch failed: {e}")

    return False, ""


def auto_fix_missing_npm_package(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Auto-install missing npm packages."""
    if not is_node_project:
        return False, ""
    
    match = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", error_msg)
    if not match:
        return False, ""
    
    missing_pkg = match.group(1).strip()
    
    # Only try for package names (no path separators, no file extensions)
    if "/" in missing_pkg or "\\" in missing_pkg or missing_pkg.endswith((".ts", ".tsx", ".js", ".jsx")):
        return False, ""
    
    # Determine if dev dependency
    is_dev_dep = any(pkg in missing_pkg for pkg in [
        "eslint", "prettier", "typescript", "postcss", "autoprefixer", "tailwind",
        "@types/", "jest", "vitest", "playwright"
    ])
    
    install_flag = "--save-dev" if is_dev_dep else "--save"
    
    result = subprocess.run(
        ["npm", "install", install_flag, missing_pkg, "--no-audit", "--prefer-offline"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60
    )
    
    if result.returncode == 0:
        return True, f"Installed missing package: {missing_pkg}"
    
    return False, ""


def auto_fix_eslint_config_package(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Auto-install missing ESLint config packages."""
    if not is_node_project:
        return False, ""
    
    match = re.search(r"Cannot find module ['\"]eslint-config-([^'\"]+)['\"]", error_msg)
    if not match:
        return False, ""
    
    config_pkg = f"eslint-config-{match.group(1).strip()}"
    
    result = subprocess.run(
        ["npm", "install", "--save-dev", config_pkg, "--no-audit", "--prefer-offline"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60
    )
    
    if result.returncode == 0:
        return True, f"Installed ESLint config: {config_pkg}"
    
    return False, ""


def auto_fix_prettier_formatting(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Auto-fix Prettier formatting errors."""
    if not is_node_project or "prettier/prettier" not in error_msg:
        return False, ""
    
    # Extract files from error
    prettier_files = set()
    for m in re.findall(r'src/[^\s:]+\.(?:ts|tsx|js|jsx|css|json)', error_msg):
        prettier_files.add(m)
    
    if not prettier_files:
        prettier_files = ["src"]  # Format entire src directory
    
    prettier_files = [f for f in prettier_files if (repo_path / f).exists()]
    if not prettier_files:
        return False, ""
    
    result = subprocess.run(
        ["npx", "prettier", "--write"] + list(prettier_files),
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30
    )
    
    if result.returncode == 0:
        return True, f"Fixed Prettier formatting in {len(prettier_files)} file(s)"
    
    return False, ""


def auto_fix_prisma_model_missing(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Auto-fix Prisma model missing from client error.
    
    Detects when code tries to access db.modelName but model doesn't exist in Prisma schema.
    Runs `npx prisma generate` to regenerate client from schema.
    """
    if not is_node_project:
        return False, ""
    
    # Check for the specific error pattern
    match = re.search(
        r"Property ['\"](\w+)['\"] does not exist on type ['\"]PrismaClient",
        error_msg
    )
    if not match:
        return False, ""
    
    missing_model = match.group(1)
    print(f"Detected missing Prisma model: {missing_model}")
    
    prisma_schema = repo_path / "prisma" / "schema.prisma"
    if not prisma_schema.exists():
        print("No prisma/schema.prisma found - cannot auto-fix")
        return False, ""
    
    try:
        # Read schema to check if model exists
        schema_content = prisma_schema.read_text(encoding="utf-8")
        
        # Extract all model names from schema (case-sensitive)
        # Prisma models: "model ModelName {"
        models = re.findall(r'^model\s+(\w+)\s*\{', schema_content, re.MULTILINE)
        
        # Convert to Prisma client accessor names (camelCase)
        # ModelName → modelName, User → user, TenantSettings → tenantSettings
        def to_camel_case(name: str) -> str:
            if not name:
                return name
            return name[0].lower() + name[1:]
        
        model_accessors = [to_camel_case(m) for m in models]
        
        # Check if the missing model exists in schema
        if missing_model in model_accessors:
            # Model exists but client might be outdated
            print(f"Model '{missing_model}' exists in schema - running prisma generate")
        else:
            # Model doesn't exist - check for similar names
            similar = [m for m in model_accessors if missing_model.lower() in m.lower() or m.lower() in missing_model.lower()]
            if similar:
                print(f"Model '{missing_model}' not found. Similar models: {', '.join(similar)}")
                print("Attempting prisma generate in case schema was updated...")
            else:
                print(f"Model '{missing_model}' not found in schema. Available: {', '.join(model_accessors[:10])}")
                print("Attempting prisma generate anyway...")
        
        # Run prisma generate to regenerate client
        result = subprocess.run(
            ["npx", "prisma", "generate"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            return True, f"Ran prisma generate (missing model: {missing_model})"
        else:
            print(f"prisma generate failed: {result.stderr}")
            return False, ""
    
    except Exception as e:
        print(f"Auto-fix failed: {e}")
        return False, ""


def auto_fix_prisma_generate(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Auto-run prisma generate when Prisma types are missing."""
    if not is_node_project:
        return False, ""
    
    prisma_schema = repo_path / "prisma" / "schema.prisma"
    if not prisma_schema.exists():
        return False, ""
    
    # Check if error is about missing Prisma models
    if not re.search(r"@prisma/client['\"].*?has no exported member", error_msg):
        return False, ""
    
    result = subprocess.run(
        ["npx", "prisma", "generate"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60
    )
    
    if result.returncode == 0:
        return True, "Ran prisma generate to update client types"
    
    return False, ""


def auto_fix_prisma_import_type(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Fix Prisma imported with 'import type' but used as value."""
    if not is_node_project:
        return False, ""
    
    if "cannot be used as a value because it was imported using 'import type'" not in error_msg:
        return False, ""
    if "Prisma" not in error_msg:
        return False, ""
    
    # Find files with the problematic import
    prisma_files = list(set(re.findall(r'src/[^\s:]+\.(?:ts|tsx)', error_msg)))
    
    fixed_count = 0
    for rel_path in prisma_files:
        file_path = repo_path / rel_path
        if not file_path.exists():
            continue
        
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # Change: import type { X, Prisma, Y } from '@prisma/client'
            # To: import { type X, Prisma, type Y } from '@prisma/client'
            def fix_import(m):
                imports = [s.strip() for s in m.group(1).split(",")]
                if "Prisma" not in imports:
                    return m.group(0)
                new_imports = [f"type {x}" if x != "Prisma" else "Prisma" for x in imports]
                return f"import {{ {', '.join(new_imports)} }} from {m.group(2)}"
            
            new_content, count = re.subn(
                r"import type\s*\{\s*([^}]+)\}\s*from\s*(['\"]@prisma/client['\"])",
                fix_import,
                content
            )
            
            if count > 0:
                file_path.write_text(new_content, encoding="utf-8")
                fixed_count += 1
        except Exception:
            continue
    
    if fixed_count > 0:
        return True, f"Fixed Prisma import type in {fixed_count} file(s)"
    
    return False, ""


def auto_fix_env_type_missing(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Auto-add missing environment variable types."""
    if not is_node_project:
        return False, ""
    
    match = re.search(r"Property ['\"]([A-Z_]+)['\"] does not exist on type", error_msg)
    if not match:
        return False, ""
    
    missing_var = match.group(1)
    
    # Find env schema file
    env_files = [
        "src/env.ts", "src/env.mjs", "src/lib/env.ts",
        "src/lib/env.mjs", "lib/env.ts"
    ]
    
    env_file_path = None
    for candidate in env_files:
        if (repo_path / candidate).exists():
            env_file_path = repo_path / candidate
            break
    
    if not env_file_path:
        return False, ""
    
    try:
        content = env_file_path.read_text(encoding="utf-8")
        
        # Add to env object
        pattern = r"(const env\s*(?::\s*\{[^}]*\})?\s*=\s*\{[^}]*?)(\n\s*\})"
        
        def add_property(m):
            existing = m.group(1)
            closing = m.group(2)
            if not existing.rstrip().endswith(','):
                existing += ','
            new_prop = f"\n  {missing_var}: process.env.{missing_var}!"
            return existing + new_prop + closing
        
        new_content, count = re.subn(pattern, add_property, content, count=1)
        
        if count > 0:
            env_file_path.write_text(new_content, encoding="utf-8")
            return True, f"Added {missing_var} to env schema"
    except Exception:
        pass
    
    return False, ""


def auto_fix_type_conversion(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Auto-fix common type conversion errors (number → string, string → number).
    
    Examples:
    - Argument of type 'number' is not assignable to parameter of type 'string'
    - Type 'string' is not assignable to type 'number'
    """
    if not is_node_project:
        return False, ""
    
    # Pattern 1: Type 'X' is not assignable to type 'Y'
    # Pattern 2: Argument of type 'X' is not assignable to parameter of type 'Y'
    match = re.search(
        r"(?:Argument of type|Type) ['\"]?(\w+)['\"]? is not assignable to (?:parameter of type|type) ['\"]?(\w+)['\"]?",
        error_msg,
        re.IGNORECASE
    )
    if not match:
        return False, ""
    
    from_type = match.group(1).lower()
    to_type = match.group(2).lower()
    
    # Only handle simple type conversions: number ↔ string
    conversion_map = {
        ("number", "string"): "String(VALUE)",
        ("string", "number"): "Number(VALUE)",
    }
    
    conversion = conversion_map.get((from_type, to_type))
    if not conversion:
        return False, ""
    
    # Extract file path and line number from error
    file_match = re.search(r'\./([^\s:]+\.(?:ts|tsx|js|jsx)):(\d+):', error_msg)
    if not file_match:
        return False, ""
    
    file_path_rel = file_match.group(1)
    line_num = int(file_match.group(2))
    
    file_path = repo_path / file_path_rel
    if not file_path.exists():
        return False, ""
    
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if line_num < 1 or line_num > len(lines):
            return False, ""
        
        # Get the problematic line (1-indexed)
        error_line = lines[line_num - 1]
        
        # Try to identify the variable/expression on this line
        # Common patterns: env.VAR_NAME, variable, function(arg)
        # For env vars specifically: env.JWT_EXPIRES_IN, env.PORT, etc.
        var_patterns = [
            r'\benv\.([A-Z_]+)\b',  # env.VAR_NAME
            r'\b([a-z]\w+)\b',      # variableName (last one on line)
        ]
        
        for pattern in var_patterns:
            matches = list(re.finditer(pattern, error_line))
            if not matches:
                continue
            
            # Get the last match on the line (likely the problematic one)
            last_match = matches[-1]
            var_name = last_match.group(0)
            
            # Apply conversion
            if from_type == "number" and to_type == "string":
                new_expr = f"String({var_name})"
            elif from_type == "string" and to_type == "number":
                new_expr = f"Number({var_name})"
            else:
                continue
            
            # Replace the variable with the converted expression
            new_line = error_line[:last_match.start()] + new_expr + error_line[last_match.end():]
            lines[line_num - 1] = new_line
            
            # Write back
            file_path.write_text("".join(lines), encoding="utf-8")
            
            return True, f"Converted {var_name} from {from_type} to {to_type} in {file_path_rel}:{line_num}"
    
    except Exception as e:
        print(f"Type conversion auto-fix failed: {e}")
    
    return False, ""


def auto_fix_index_signature_mismatch(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix 'Index signature for type string is missing in type X'
    or 'Type X is not assignable to type Record<string, unknown>'.

    These happen when a typed object is passed to a function expecting
    Record<string, unknown>. Fix by casting at the call site.
    """
    if not is_node_project:
        return False, ""

    # Match the index-signature variant
    m = re.search(
        r"Argument of type ['\"](\w+)['\"] is not assignable to parameter of type ['\"]Record<string,\s*unknown>['\"]",
        error_msg,
    )
    if not m:
        m = re.search(
            r"Index signature for type ['\"]string['\"] is missing in type ['\"](\w+)['\"]",
            error_msg,
        )
    if not m:
        return False, ""

    offending_type = m.group(1)

    # Find file and line
    file_match = re.search(r'\./([^\s:]+\.(?:ts|tsx)):(\d+):(\d+)', error_msg)
    if not file_match:
        file_match = re.search(r'(src/[^\s:]+\.(?:ts|tsx)):(\d+):(\d+)', error_msg)
    if not file_match:
        return False, ""

    file_rel = file_match.group(1)
    line_num = int(file_match.group(2))
    col_num = int(file_match.group(3))
    file_path = repo_path / file_rel

    if not file_path.exists():
        return False, ""

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        if line_num < 1 or line_num > len(lines):
            return False, ""

        error_line = lines[line_num - 1]

        # Find the identifier at or near the column — the argument being passed
        # Common pattern: someFunction(customer, ctx) where 'customer' is the problem
        # col_num points to the start of the offending argument
        before_col = error_line[:col_num - 1] if col_num > 1 else ""
        from_col = error_line[col_num - 1:]
        ident_match = re.match(r'(\w+)', from_col)
        if not ident_match:
            return False, ""

        var_name = ident_match.group(1)
        cast_expr = f"{var_name} as Record<string, unknown>"

        # Replace: only the bare identifier at that position
        new_line = before_col + cast_expr + from_col[len(var_name):]
        lines[line_num - 1] = new_line
        file_path.write_text("".join(lines), encoding="utf-8")
        return True, f"Cast {var_name} as Record<string, unknown> in {file_rel}:{line_num} (was {offending_type})"
    except Exception as e:
        print(f"auto_fix_index_signature_mismatch failed: {e}")

    return False, ""


def auto_fix_missing_typescript_types(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Auto-install missing @types packages."""
    if not is_node_project:
        return False, ""
    
    # Pattern: "Could not find a declaration file for module 'react'"
    match = re.search(r"Could not find a declaration file for module ['\"]([^'\"]+)['\"]", error_msg)
    if not match:
        return False, ""
    
    module_name = match.group(1).strip()
    types_pkg = f"@types/{module_name}"
    
    result = subprocess.run(
        ["npm", "install", "--save-dev", types_pkg, "--no-audit", "--prefer-offline"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60
    )
    
    if result.returncode == 0:
        return True, f"Installed TypeScript types: {types_pkg}"
    
    return False, ""


def auto_fix_outdated_lockfile(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Update package-lock.json when package.json changed."""
    if not is_node_project:
        return False, ""
    
    if "lock file" not in error_msg.lower() and "package-lock" not in error_msg.lower():
        return False, ""
    
    result = subprocess.run(
        ["npm", "install", "--package-lock-only", "--no-audit"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30
    )
    
    if result.returncode == 0:
        return True, "Updated package-lock.json"
    
    return False, ""


def auto_fix_port_in_use(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Kill process using the port."""
    if not is_node_project:
        return False, ""
    
    match = re.search(r"port (\d+) is already in use", error_msg, re.IGNORECASE)
    if not match:
        return False, ""
    
    port = match.group(1)
    
    try:
        # Try to kill process on that port (Linux/Mac)
        subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            timeout=5
        )
        subprocess.run(
            ["kill", "-9", f"$(lsof -ti :{port})"],
            shell=True,
            timeout=5
        )
        return True, f"Killed process on port {port}"
    except Exception:
        pass
    
    return False, ""


def auto_fix_missing_gitignore_entries(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Add common missing .gitignore entries."""
    if not is_node_project:
        return False, ""
    
    gitignore_path = repo_path / ".gitignore"
    if not gitignore_path.exists():
        return False, ""
    
    # Check if build output is committed (common mistake)
    if ".next" in error_msg or "dist" in error_msg:
        try:
            content = gitignore_path.read_text(encoding="utf-8")
            entries_to_add = []
            
            if ".next" not in content:
                entries_to_add.append(".next/")
            if "node_modules" not in content:
                entries_to_add.append("node_modules/")
            if "dist" not in content and "dist/" not in content:
                entries_to_add.append("dist/")
            
            if entries_to_add:
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    f.write("\n# Auto-added by AI Runner\n")
                    for entry in entries_to_add:
                        f.write(f"{entry}\n")
                
                return True, f"Added {len(entries_to_add)} entries to .gitignore"
        except Exception:
            pass
    
    return False, ""


def auto_fix_circular_dependency(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Detect and suggest fix for circular dependencies."""
    if "circular dependency" not in error_msg.lower():
        return False, ""
    
    # Extract file paths from circular dependency error
    files = re.findall(r'["\']([^"\']+\.(?:ts|tsx|js|jsx))["\']', error_msg)
    
    if files:
        print(f"⚠️ Circular dependency detected: {' -> '.join(files[:3])}")
        print("Manual intervention needed: refactor to remove circular dependency")
    
    return False, ""  # Can't auto-fix circular deps


def auto_fix_missing_tailwind_config(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Create missing tailwind.config.js if needed."""
    if not is_node_project:
        return False, ""
    
    if "tailwind" not in error_msg.lower():
        return False, ""
    
    tailwind_config = repo_path / "tailwind.config.js"
    if tailwind_config.exists():
        return False, ""
    
    # Check if tailwindcss is installed
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return False, ""
    
    try:
        import json
        with open(package_json) as f:
            pkg = json.load(f)
        
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "tailwindcss" not in deps:
            return False, ""
        
        # Create basic tailwind config
        config_content = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
"""
        tailwind_config.write_text(config_content, encoding="utf-8")
        return True, "Created tailwind.config.js"
    except Exception:
        pass
    
    return False, ""


def auto_fix_nextjs_image_domains(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Add image domain to Next.js config when needed."""
    if not is_node_project:
        return False, ""
    
    match = re.search(r"Invalid src prop.*?hostname ['\"]([^'\"]+)['\"]", error_msg)
    if not match:
        return False, ""
    
    hostname = match.group(1)
    next_config = repo_path / "next.config.js"
    
    if not next_config.exists():
        return False, ""
    
    try:
        content = next_config.read_text(encoding="utf-8")
        
        # Add hostname to remotePatterns or domains
        if "remotePatterns" in content:
            # Modern Next.js config with remotePatterns
            pattern = r"(remotePatterns\s*:\s*\[)"
            new_entry = f"\n      {{ protocol: 'https', hostname: '{hostname}' }},"
            new_content, count = re.subn(pattern, r"\1" + new_entry, content, count=1)
        else:
            # Legacy domains array
            pattern = r"(domains\s*:\s*\[)"
            new_entry = f"\n      '{hostname}',"
            new_content, count = re.subn(pattern, r"\1" + new_entry, content, count=1)
        
        if count > 0:
            next_config.write_text(new_content, encoding="utf-8")
            return True, f"Added image domain: {hostname}"
    except Exception:
        pass
    
    return False, ""


def auto_fix_cors_configuration(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """Suggest CORS fix (can't auto-apply without knowing allowed origins)."""
    if "cors" not in error_msg.lower() and "cross-origin" not in error_msg.lower():
        return False, ""
    
    print("⚠️ CORS error detected. Manual configuration needed in API routes or middleware.")
    print("Add: res.setHeader('Access-Control-Allow-Origin', 'YOUR_DOMAIN')")
    
    return False, ""  # Can't auto-fix without knowing allowed origins


def auto_fix_zod_query_param_coerce(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix Zod schema in API routes: query params are strings, so use z.coerce.number()
    for numeric fields to fix TS2345 'string | undefined' is not assignable to 'number'.
    """
    if not is_node_project:
        return False, ""
    if "TS2345" not in error_msg or "is not assignable" not in error_msg:
        return False, ""
    if "ZodType" not in error_msg and "ZodObject" not in error_msg:
        return False, ""
    if "number" not in error_msg and "limit" not in error_msg:
        return False, ""

    # Find route files mentioned in the error (e.g. route.ts(15,24))
    route_files = list(set(re.findall(r"(src/[^\s(]+route\.ts)", error_msg)))
    if not route_files:
        return False, ""

    fixed_any = False
    for rel_path in route_files:
        fp = repo_path / rel_path
        if not fp.exists():
            continue
        try:
            content = fp.read_text(encoding="utf-8")
            # Replace z.number() with z.coerce.number() for query params (URL params are strings)
            new_content, n = re.subn(r"\bz\.number\(\)", "z.coerce.number()", content)
            if n > 0:
                fp.write_text(new_content, encoding="utf-8")
                print(f"Fixed Zod number coercion in {rel_path} ({n} replacement(s))")
                fixed_any = True
        except Exception as e:
            print(f"Zod coerce fix failed for {rel_path}: {e}")
    return fixed_any, "Zod query param: use z.coerce.number() for numeric fields" if fixed_any else (False, "")


def auto_fix_duplicate_module_declaration(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix 'Duplicate module-level declaration' in two ways:
    1. For test files: if declarations are inside describe/it/test callbacks,
       the code is actually correct — skip (the validator was wrong).
    2. For genuine module-level duplicates: rename 2nd+ to unique names.
    """
    if not is_node_project:
        return False, ""
    if "Duplicate module-level declaration" not in error_msg:
        return False, ""

    # Extract ALL .ts/.tsx files mentioned — support src/, app/, and bare paths
    path_candidates = list(set(re.findall(
        r'((?:src|app|lib|components|pages|utils|hooks|services|types|config)[/\\][^\s:(]+\.(?:ts|tsx))',
        error_msg,
    )))
    if not path_candidates:
        path_candidates = list(set(re.findall(r'([^\s:(]+\.(?:ts|tsx))', error_msg)))

    dup_names = set(re.findall(r"Duplicate module-level declaration of ['\"](\w+)['\"]", error_msg))
    if not dup_names:
        dup_names = {"result", "response", "parsed", "validated", "body", "data", "error", "req", "res"}

    fixed_files = []
    for rel_path in path_candidates:
        fp = repo_path / rel_path
        if not fp.exists():
            continue
        try:
            content = fp.read_text(encoding="utf-8")
            is_test_file = any(p in rel_path for p in ("__tests__", ".test.", ".spec."))

            # For test files, check if duplicates are inside arrow function callbacks
            # (describe/it/test/beforeEach). If so, they're properly scoped and this
            # is a validator false-positive — skip the file.
            if is_test_file:
                from .fix_validator import FixValidator
                scope_ranges = FixValidator._build_scope_ranges(content)
                all_inside_scope = True
                for var_name in dup_names:
                    decl_pattern = re.compile(
                        r"^\s*(const|let)\s+" + re.escape(var_name) + r"\s*[=:]",
                        re.MULTILINE,
                    )
                    decl_matches = list(decl_pattern.finditer(content))
                    if len(decl_matches) < 2:
                        continue
                    # Check if ALL declarations (except possibly the first) are inside scopes
                    for dm in decl_matches[1:]:
                        if not FixValidator._is_inside_scope(dm.start(), scope_ranges):
                            all_inside_scope = False
                            break
                    if not all_inside_scope:
                        break
                if all_inside_scope:
                    print(f"  Skipping {rel_path}: declarations are properly scoped inside test callbacks")
                    continue

            lines = content.split("\n")
            file_changed = False

            for var_name in dup_names:
                decl_pattern = re.compile(
                    r"^\s*(const|let)\s+" + re.escape(var_name) + r"\s*[=:]",
                    re.MULTILINE,
                )
                decl_matches = list(decl_pattern.finditer(content))
                if len(decl_matches) < 2:
                    continue

                def offset_to_line(offset: int) -> int:
                    return content[:offset].count("\n")

                new_lines = lines[:]
                for i, decl in enumerate(decl_matches):
                    if i == 0:
                        continue
                    new_name = f"{var_name}{i + 1}"
                    decl_line = offset_to_line(decl.start())
                    line_content = new_lines[decl_line]
                    new_line, n = re.subn(
                        r"\b(const|let)\s+" + re.escape(var_name) + r"(\s*[=:])",
                        r"\1 " + new_name + r"\2",
                        line_content,
                        count=1,
                    )
                    if n > 0:
                        new_lines[decl_line] = new_line
                        file_changed = True
                        usage_pattern = re.compile(
                            r"\b" + re.escape(var_name) + r"\b(?!\d)"
                        )
                        for j in range(decl_line + 1, len(new_lines)):
                            if decl_pattern.search(new_lines[j]):
                                break
                            new_lines[j], cnt = usage_pattern.subn(new_name, new_lines[j], count=0)

                if file_changed:
                    lines = new_lines
                    content = "\n".join(lines)

            if file_changed:
                fp.write_text("\n".join(lines), encoding="utf-8")
                fixed_files.append(rel_path)
                print(f"Fixed duplicate declarations in {rel_path}")

        except Exception as e:
            print(f"Duplicate declaration fix failed for {rel_path}: {e}")

    if fixed_files:
        return True, f"Renamed duplicate module-level declarations in {', '.join(fixed_files)}"
    return False, ""


def auto_fix_eslint_rule_not_found(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix 'Definition for rule X was not found' by disabling the rule
    in the ESLint config or adding an inline disable comment.
    """
    if not is_node_project:
        return False, ""

    m = re.search(r"Definition for rule ['\"]([^'\"]+)['\"] was not found", error_msg)
    if not m:
        return False, ""

    missing_rule = m.group(1)

    # Try to add rule to ESLint config as "off"
    eslint_configs = [
        ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml",
        ".eslintrc.yaml", ".eslintrc",
        "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
    ]
    for config_name in eslint_configs:
        config_path = repo_path / config_name
        if not config_path.exists():
            continue

        try:
            content = config_path.read_text(encoding="utf-8")

            if config_name.endswith(".json") or config_name == ".eslintrc":
                import json
                try:
                    cfg = json.loads(content)
                except json.JSONDecodeError:
                    continue
                if "rules" not in cfg:
                    cfg["rules"] = {}
                cfg["rules"][missing_rule] = "off"
                config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
                return True, f"Disabled missing ESLint rule '{missing_rule}' in {config_name}"

            elif config_name.endswith((".js", ".cjs", ".mjs")):
                # JS/flat config — inject into rules object
                if '"rules"' in content or "'rules'" in content or "rules:" in content or "rules :" in content:
                    new_content = re.sub(
                        r'(rules\s*:\s*\{)',
                        rf'\1\n    "{missing_rule}": "off",',
                        content,
                        count=1,
                    )
                    if new_content != content:
                        config_path.write_text(new_content, encoding="utf-8")
                        return True, f"Disabled missing ESLint rule '{missing_rule}' in {config_name}"
        except Exception as e:
            print(f"ESLint rule fix failed for {config_name}: {e}")
            continue

    # Fallback: add eslint-disable comment to the specific file
    file_match = re.search(r'\./([^\s:]+\.tsx?)', error_msg)
    if file_match:
        error_file = repo_path / file_match.group(1)
        if error_file.exists():
            try:
                file_content = error_file.read_text(encoding="utf-8")
                disable_comment = f"/* eslint-disable {missing_rule} */\n"
                if disable_comment.strip() not in file_content:
                    error_file.write_text(disable_comment + file_content, encoding="utf-8")
                    return True, f"Added eslint-disable for '{missing_rule}' in {file_match.group(1)}"
            except Exception:
                pass

    return False, ""


def auto_fix_nextjs_route_export(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix Next.js route files that export non-handler constants (like VALID_JOB_STATUSES).
    Next.js App Router route files may only export: GET, HEAD, OPTIONS, POST, PUT, DELETE,
    PATCH, config, generateStaticParams, revalidate, dynamic, dynamicParams,
    fetchCache, runtime, preferredRegion, maxDuration.
    Any other exported const triggers TS2344.
    """
    if not is_node_project:
        return False, ""
    if "does not satisfy the constraint" not in error_msg or "index signature" not in error_msg.lower():
        return False, ""

    route_match = re.search(
        r"(?:types/|app/)([^\s:(]+route\.ts)",
        error_msg,
    )
    if not route_match:
        return False, ""

    raw_path = route_match.group(0)
    if "types/app/" in raw_path:
        rel_path = raw_path.split("types/")[1]
    elif raw_path.startswith("app/"):
        rel_path = raw_path
    else:
        rel_path = "app/" + raw_path

    fp = repo_path / rel_path
    if not fp.exists():
        return False, ""

    VALID_HANDLER_EXPORTS = {
        "GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH",
        "config", "generateStaticParams", "revalidate", "dynamic",
        "dynamicParams", "fetchCache", "runtime", "preferredRegion", "maxDuration",
    }

    try:
        content = fp.read_text(encoding="utf-8")
        lines = content.split("\n")
        changed = False

        new_lines = []
        for line in lines:
            m = re.match(r'^(export\s+)(const|let|var)\s+(\w+)', line)
            if m:
                name = m.group(3)
                if name not in VALID_HANDLER_EXPORTS:
                    new_line = line.replace(m.group(1), "", 1)
                    new_lines.append(new_line)
                    changed = True
                    print(f"  Removed export from '{name}' in {rel_path}")
                    continue
            new_lines.append(line)

        if changed:
            fp.write_text("\n".join(new_lines), encoding="utf-8")
            return True, f"Removed non-handler exports from Next.js route file {rel_path}"
    except Exception as e:
        print(f"Next.js route export fix failed for {rel_path}: {e}")

    return False, ""


def auto_fix_jsx_no_undef(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool
) -> Tuple[bool, str]:
    """
    Fix 'X' is not defined. react/jsx-no-undef by replacing the undefined
    component usage with a placeholder div or removing the JSX entirely.
    This prevents cascading errors when a component import was removed
    (phantom import) but JSX usage remains.
    """
    if not is_node_project:
        return False, ""

    match = re.search(
        r'\./([^\s:]+\.tsx?)\s*\n\s*\d+:\d+\s+Error:\s+[\'"]?(\w+)[\'"]?\s+is not defined',
        error_msg,
    )
    if not match:
        # Simpler inline pattern
        match = re.search(
            r'\./([^\s:]+\.tsx?).*?[\'"](\w+)[\'"]\s+is not defined',
            error_msg,
        )
    if not match:
        return False, ""

    file_path = repo_path / match.group(1)
    undef_component = match.group(2)

    if not file_path.exists():
        return False, ""

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split('\n')
        new_lines = []
        removed = False

        in_undef_block = 0
        for line in lines:
            # Self-closing: <Component ... />
            if re.search(rf'<{re.escape(undef_component)}\b[^>]*/>', line):
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}{{/* removed undefined: {undef_component} */}}")
                removed = True
                continue
            # Opening tag: <Component ...>  (not a self-closing or line with closing tag)
            if re.search(rf'<{re.escape(undef_component)}[\s>]', line) and not re.search(rf'</{re.escape(undef_component)}>', line):
                in_undef_block += 1
                removed = True
                continue
            # Closing tag: </Component>
            if re.search(rf'</{re.escape(undef_component)}>', line):
                if in_undef_block > 0:
                    in_undef_block -= 1
                removed = True
                continue
            if in_undef_block > 0:
                continue
            new_lines.append(line)

        if removed:
            file_path.write_text('\n'.join(new_lines), encoding="utf-8")
            return True, f"Removed undefined component '{undef_component}' usage from {match.group(1)}"
    except Exception:
        pass

    return False, ""


def auto_fix_prisma_null_assignment(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool,
) -> Tuple[bool, str]:
    """
    Auto-fix Prisma where-clause null assignments.

    Prisma strict types don't accept `null` directly in where clauses.
    Converts `field: null` or `field: { equals: null }` to proper Prisma
    null-check syntax using `{ isSet: false }`.
    """
    if not is_node_project:
        return False, ""

    match = re.search(
        r"['\"]?null['\"]? is not assignable to type ['\"]string \| (?:StringFilter|FieldRef)<",
        error_msg,
    )
    if not match:
        return False, ""

    file_match = re.search(r'\./([^\s:]+\.(?:ts|tsx)):(\d+)', error_msg)
    if not file_match:
        file_match = re.search(r'(src/[^\s:]+\.(?:ts|tsx)):(\d+)', error_msg)
    if not file_match:
        return False, ""

    file_rel = file_match.group(1)
    error_line = int(file_match.group(2))
    fp = repo_path / file_rel

    if not fp.exists():
        return False, ""

    try:
        content = fp.read_text(encoding="utf-8")
        lines = content.split("\n")
        if error_line < 1 or error_line > len(lines):
            return False, ""

        line_text = lines[error_line - 1]

        # Pattern 1: `userId: { equals: null }` → `userId: { isSet: false }`
        new_line = re.sub(
            r'(\w+)\s*:\s*\{\s*equals\s*:\s*null\s*\}',
            r'\1: { isSet: false }',
            line_text,
        )
        if new_line != line_text:
            lines[error_line - 1] = new_line
            fp.write_text("\n".join(lines), encoding="utf-8")
            return True, f"Fixed Prisma null filter (equals:null → isSet:false) in {file_rel}:{error_line}"

        # Pattern 2: `userId: null` → `userId: { isSet: false }`
        new_line = re.sub(
            r'(\w+)\s*:\s*null\b',
            r'\1: { isSet: false }',
            line_text,
        )
        if new_line != line_text:
            lines[error_line - 1] = new_line
            fp.write_text("\n".join(lines), encoding="utf-8")
            return True, f"Fixed Prisma null filter (null → isSet:false) in {file_rel}:{error_line}"

    except Exception as e:
        print(f"auto_fix_prisma_null_assignment failed: {e}")

    return False, ""


def auto_fix_module_not_found_stub(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool,
) -> Tuple[bool, str]:
    """
    Auto-fix "Module not found: Can't resolve '@/lib/...'" errors by
    delegating to the import resolver which scans all source files and creates stubs.
    """
    if not is_node_project:
        return False, ""

    # Check if error contains missing @/ module references
    matches = re.findall(
        r"(?:Module not found: Can't resolve|Cannot find module)\s+'(@/[^']+)'",
        error_msg,
    )
    if not matches:
        return False, ""

    print(f"  [stub-debug] Found {len(set(matches))} missing @/ modules in error: {list(set(matches))[:5]}")

    try:
        from .import_resolver import resolve_all_missing_imports
        created = resolve_all_missing_imports(repo_path)
        if created:
            return True, f"Created stub module(s): {', '.join(created)}"
        else:
            print(f"  [stub-debug] Import resolver found no missing imports to stub (files may already exist)")
    except Exception as e:
        print(f"  [stub-debug] Import resolver failed: {e}")
        import traceback
        traceback.print_exc()

    return False, ""


def auto_fix_hardcoded_secrets(
    error_msg: str,
    repo_path: Path,
    is_node_project: bool,
) -> Tuple[bool, str]:
    """
    Auto-fix hardcoded secret/API key warnings from the security scanner.

    Replaces obvious placeholder secrets with process.env references.
    """
    if not is_node_project:
        return False, ""

    match = re.search(
        r'\[CRITICAL\]\s+([^\s:]+\.(?:ts|tsx|js)):(\d+)\s+.*?Hardcoded Secret',
        error_msg,
    )
    if not match:
        return False, ""

    file_rel = match.group(1)
    fp = repo_path / file_rel

    if not fp.exists():
        return False, ""

    try:
        content = fp.read_text(encoding="utf-8")
        original = content

        # Replace hardcoded secret patterns with env var references
        content = re.sub(
            r"""((?:api[_-]?key|secret|token|password|auth[_-]?secret|credential|encryption[_-]?key)\s*[:=]\s*)(['"])([A-Za-z0-9_\-/.+=]{8,})\2""",
            lambda m: f'{m.group(1)}process.env.{_env_var_name(m.group(0))} || ""',
            content,
            flags=re.IGNORECASE,
        )

        if content != original:
            fp.write_text(content, encoding="utf-8")
            return True, f"Replaced hardcoded secrets with env var references in {file_rel}"

    except Exception as e:
        print(f"auto_fix_hardcoded_secrets failed: {e}")

    return False, ""


def _env_var_name(context: str) -> str:
    """Derive an env var name from the context of a hardcoded secret."""
    ctx = context.lower()
    if "encryption" in ctx:
        return "ENCRYPTION_KEY"
    if "refresh" in ctx:
        return "REFRESH_TOKEN_SECRET"
    if "access" in ctx:
        return "ACCESS_TOKEN_SECRET"
    if "api" in ctx:
        return "API_SECRET_KEY"
    if "auth" in ctx:
        return "AUTH_SECRET"
    return "SECRET_KEY"
