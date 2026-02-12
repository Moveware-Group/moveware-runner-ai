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
        auto_fix_missing_npm_package,
        auto_fix_eslint_config_package,
        auto_fix_prettier_formatting,
        auto_fix_prisma_generate,
        auto_fix_prisma_import_type,
        auto_fix_env_type_missing,
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
