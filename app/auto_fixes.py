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
        auto_fix_missing_export,
        auto_fix_prisma_schema_mismatch,
        auto_fix_missing_npm_package,
        auto_fix_eslint_config_package,
        auto_fix_prettier_formatting,
        auto_fix_prisma_model_missing,
        auto_fix_prisma_generate,
        auto_fix_prisma_import_type,
        auto_fix_env_type_missing,
        auto_fix_type_conversion,
        auto_fix_missing_typescript_types,
        auto_fix_outdated_lockfile,
        auto_fix_port_in_use,
        auto_fix_missing_gitignore_entries,
        auto_fix_circular_dependency,
        auto_fix_missing_tailwind_config,
        auto_fix_nextjs_image_domains,
        auto_fix_cors_configuration,
    ]
    
    for auto_fix_func in auto_fixes:
        try:
            success, description = auto_fix_func(error_msg, repo_path, is_node_project)
            if success:
                print(f"✅ Auto-fix applied: {description}")
                return True, description
        except Exception as e:
            print(f"Warning: Auto-fix {auto_fix_func.__name__} failed: {e}")
            continue
    
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
                # Found case mismatch — fix the import in the importing file
                importing_match = re.search(r'\./([^\s:]+\.(?:ts|tsx|js|jsx)):', error_msg)
                if importing_match:
                    imp_file = repo_path / importing_match.group(1)
                    if imp_file.exists():
                        imp_content = imp_file.read_text(encoding="utf-8")
                        new_imp = imp_content.replace(missing_symbol, exp_name)
                        if new_imp != imp_content:
                            imp_file.write_text(new_imp, encoding="utf-8")
                            return True, f"Fixed import: {missing_symbol} → {exp_name} (case mismatch)"

    except Exception as e:
        print(f"auto_fix_missing_export failed: {e}")

    return False, ""


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

                new_content = "\n".join(lines)
                file_path.write_text(new_content, encoding="utf-8")
                removed_preview = removed[0].strip()[:60]
                return True, f"Removed invalid '{invalid_prop}' from {model_name} query in {file_rel} ({removed_preview})"

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
    Fix 'Duplicate module-level declaration' in validate.ts by renaming
    the 2nd and later declarations to unique names (result2, response2, etc.)
    and updating usages after each renamed declaration.
    """
    if not is_node_project:
        return False, ""
    if "Duplicate module-level declaration" not in error_msg:
        return False, ""
    if "validate.ts" not in error_msg:
        return False, ""

    match = re.search(r"(src/[^\s]+validate\.ts)", error_msg)
    path_candidates = [match.group(1)] if match else []
    for m in re.findall(r"src/[^\s(]+\.ts", error_msg):
        if "validate" in m:
            path_candidates.append(m)
    path_candidates = list(set(path_candidates))

    for rel_path in path_candidates:
        fp = repo_path / rel_path
        if not fp.exists():
            continue
        try:
            content = fp.read_text(encoding="utf-8")
            lines = content.split("\n")
            # Variables that often get duplicated
            for var_name in ["result", "response", "parsed", "validated"]:
                decl_pattern = re.compile(
                    r"^\s*(const|let)\s+" + re.escape(var_name) + r"\s*[=:]",
                    re.MULTILINE,
                )
                decl_matches = list(decl_pattern.finditer(content))
                if len(decl_matches) < 2:
                    continue
                # Map character offset to line number
                def offset_to_line(offset: int) -> int:
                    return content[:offset].count("\n")

                new_lines = lines[:]
                changed = False
                for i, decl in enumerate(decl_matches):
                    if i == 0:
                        continue
                    new_name = f"{var_name}{i + 1}"
                    decl_line = offset_to_line(decl.start())
                    # Replace declaration on that line
                    line_content = new_lines[decl_line]
                    new_line, n = re.subn(
                        r"\b(const|let)\s+" + re.escape(var_name) + r"(\s*[=:])",
                        r"\1 " + new_name + r"\2",
                        line_content,
                        count=1,
                    )
                    if n > 0:
                        new_lines[decl_line] = new_line
                        changed = True
                        # Replace usages of var_name on subsequent lines until next declaration of var_name
                        usage_pattern = re.compile(
                            r"\b" + re.escape(var_name) + r"\b(?!\d)"
                        )
                        for j in range(decl_line + 1, len(new_lines)):
                            if decl_pattern.search(new_lines[j]):
                                break
                            new_lines[j], cnt = usage_pattern.subn(new_name, new_lines[j], count=0)
                            if cnt > 0:
                                changed = True
                if changed:
                    fp.write_text("\n".join(new_lines), encoding="utf-8")
                    print(f"Fixed duplicate declarations in {rel_path}")
                    return True, "Renamed duplicate module-level declarations in validate.ts"
        except Exception as e:
            print(f"Duplicate declaration fix failed for {rel_path}: {e}")

    return False, ""
