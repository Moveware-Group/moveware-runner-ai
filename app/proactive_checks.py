"""
Proactive Dependency Management and Health Checks

Runs checks BEFORE build to catch common issues early.
Prevents wasted time and AI attempts on preventable errors.
"""
import json
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any


def run_proactive_checks(repo_path: Path) -> Tuple[List[str], List[str]]:
    """
    Run proactive checks before build to catch common issues.
    
    Args:
        repo_path: Path to repository
    
    Returns:
        (fixes_applied, warnings) - List of fixes that were applied and any warnings
    """
    fixes_applied = []
    warnings = []
    
    package_json_path = repo_path / "package.json"
    if not package_json_path.exists():
        return fixes_applied, warnings
    
    # Check 1: Missing peer dependencies
    peer_deps_fix = check_and_install_peer_dependencies(repo_path)
    if peer_deps_fix:
        fixes_applied.append(peer_deps_fix)
    
    # Check 2: Outdated @types packages
    types_fix = check_and_update_types_packages(repo_path)
    if types_fix:
        fixes_applied.append(types_fix)
    
    # Check 3: Prisma client out of sync
    prisma_fix = check_and_run_prisma_generate(repo_path)
    if prisma_fix:
        fixes_applied.append(prisma_fix)
    
    # Check 4: Lock file out of sync with package.json
    lockfile_fix = check_lockfile_sync(repo_path)
    if lockfile_fix:
        fixes_applied.append(lockfile_fix)
    
    # Check 5: Missing essential config files
    config_warnings = check_essential_config_files(repo_path)
    warnings.extend(config_warnings)
    
    # Check 6: Security vulnerabilities (non-blocking)
    vuln_warning = check_security_vulnerabilities(repo_path)
    if vuln_warning:
        warnings.append(vuln_warning)
    
    # Check 7: Environment file setup
    env_warning = check_environment_files(repo_path)
    if env_warning:
        warnings.append(env_warning)
    
    return fixes_applied, warnings


def check_and_install_peer_dependencies(repo_path: Path) -> str:
    """Check for missing peer dependencies and install them."""
    try:
        # Run npm install to detect peer dependency warnings
        result = subprocess.run(
            ["npm", "install", "--dry-run", "--no-audit"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        output = result.stdout + result.stderr
        
        # Parse peer dependency warnings
        # Pattern: "WARN EPEERINV ... requires a peer of X@Y but none is installed"
        import re
        peer_deps = re.findall(r"requires a peer of ([^\s@]+)@([^\s]+) but none", output)
        
        if peer_deps:
            packages_to_install = []
            for pkg, version in peer_deps[:5]:  # Limit to 5 to avoid long installs
                # Simplify version (e.g., "^17.0.0" -> "17")
                major_version = version.split('.')[0].replace('^', '').replace('~', '')
                packages_to_install.append(f"{pkg}@{major_version}")
            
            if packages_to_install:
                # Install peer dependencies
                install_result = subprocess.run(
                    ["npm", "install", "--save-dev"] + packages_to_install + ["--no-audit", "--prefer-offline"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                if install_result.returncode == 0:
                    return f"Installed peer dependencies: {', '.join(packages_to_install)}"
    except Exception as e:
        print(f"Warning: Peer dependency check failed: {e}")
    
    return ""


def check_and_update_types_packages(repo_path: Path) -> str:
    """Check for outdated @types packages and update them."""
    try:
        package_json = repo_path / "package.json"
        with open(package_json) as f:
            pkg = json.load(f)
        
        dev_deps = pkg.get("devDependencies", {})
        types_packages = [name for name in dev_deps.keys() if name.startswith("@types/")]
        
        if not types_packages:
            return ""
        
        # Check which @types packages are outdated
        outdated_result = subprocess.run(
            ["npm", "outdated", "--json"] + types_packages,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        try:
            outdated_data = json.loads(outdated_result.stdout or "{}")
            outdated_types = [
                f"{name}@latest" 
                for name in types_packages 
                if name in outdated_data
            ]
            
            if outdated_types:
                # Update outdated @types packages
                update_result = subprocess.run(
                    ["npm", "install", "--save-dev"] + outdated_types + ["--no-audit"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if update_result.returncode == 0:
                    return f"Updated @types packages: {', '.join([p.split('@')[0] for p in outdated_types])}"
        except json.JSONDecodeError:
            pass
    except Exception as e:
        print(f"Warning: Types packages check failed: {e}")
    
    return ""


def check_and_run_prisma_generate(repo_path: Path) -> str:
    """Check if Prisma client needs to be regenerated."""
    prisma_schema = repo_path / "prisma" / "schema.prisma"
    if not prisma_schema.exists():
        return ""
    
    node_modules_prisma = repo_path / "node_modules" / ".prisma" / "client"
    
    # Check if Prisma client needs regeneration
    needs_generate = False
    
    if not node_modules_prisma.exists():
        needs_generate = True
    else:
        # Check if schema is newer than generated client
        try:
            schema_mtime = prisma_schema.stat().st_mtime
            client_index = node_modules_prisma / "index.js"
            
            if not client_index.exists():
                needs_generate = True
            else:
                client_mtime = client_index.stat().st_mtime
                if schema_mtime > client_mtime:
                    needs_generate = True
        except Exception:
            needs_generate = True
    
    if needs_generate:
        try:
            result = subprocess.run(
                ["npx", "prisma", "generate"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                return "Ran prisma generate (schema was modified)"
        except Exception as e:
            print(f"Warning: Prisma generate failed: {e}")
    
    return ""


def check_lockfile_sync(repo_path: Path) -> str:
    """Check if package-lock.json is in sync with package.json."""
    package_json = repo_path / "package.json"
    package_lock = repo_path / "package-lock.json"
    
    if not package_json.exists() or not package_lock.exists():
        return ""
    
    try:
        pkg_mtime = package_json.stat().st_mtime
        lock_mtime = package_lock.stat().st_mtime
        
        # If package.json is newer than lock file, update it
        if pkg_mtime > lock_mtime:
            result = subprocess.run(
                ["npm", "install", "--package-lock-only", "--no-audit"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return "Updated package-lock.json (package.json was modified)"
    except Exception as e:
        print(f"Warning: Lock file sync check failed: {e}")
    
    return ""


def check_essential_config_files(repo_path: Path) -> List[str]:
    """Check for missing essential configuration files."""
    warnings = []
    
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return warnings
    
    try:
        with open(package_json) as f:
            pkg = json.load(f)
        
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        
        # Check for Next.js project missing next.config.js
        if "next" in deps:
            next_config = repo_path / "next.config.js"
            next_config_mjs = repo_path / "next.config.mjs"
            if not next_config.exists() and not next_config_mjs.exists():
                warnings.append("Next.js project missing next.config.js")
        
        # Check for Tailwind project missing tailwind.config.js
        if "tailwindcss" in deps:
            tailwind_config = repo_path / "tailwind.config.js"
            tailwind_config_ts = repo_path / "tailwind.config.ts"
            if not tailwind_config.exists() and not tailwind_config_ts.exists():
                warnings.append("Tailwind CSS project missing tailwind.config.js")
        
        # Check for TypeScript project missing tsconfig.json
        if "typescript" in deps:
            tsconfig = repo_path / "tsconfig.json"
            if not tsconfig.exists():
                warnings.append("TypeScript project missing tsconfig.json")
        
        # Check for ESLint project missing config
        if "eslint" in deps:
            eslint_configs = [
                repo_path / ".eslintrc",
                repo_path / ".eslintrc.json",
                repo_path / ".eslintrc.js",
                repo_path / "eslint.config.js"
            ]
            if not any(c.exists() for c in eslint_configs):
                warnings.append("ESLint installed but no config file found")
    except Exception as e:
        print(f"Warning: Config file check failed: {e}")
    
    return warnings


def check_security_vulnerabilities(repo_path: Path) -> str:
    """Check for known security vulnerabilities (non-blocking)."""
    try:
        result = subprocess.run(
            ["npm", "audit", "--audit-level=high", "--json"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        try:
            audit_data = json.loads(result.stdout or "{}")
            metadata = audit_data.get("metadata", {})
            vulnerabilities = metadata.get("vulnerabilities", {})
            
            high = vulnerabilities.get("high", 0)
            critical = vulnerabilities.get("critical", 0)
            
            if high > 0 or critical > 0:
                return f"Security audit: {critical} critical, {high} high vulnerabilities (run 'npm audit fix' to address)"
        except json.JSONDecodeError:
            pass
    except Exception:
        pass
    
    return ""


def check_environment_files(repo_path: Path) -> str:
    """Check environment file setup."""
    env_example = repo_path / ".env.example"
    env_file = repo_path / ".env"
    
    if env_example.exists() and not env_file.exists():
        # Parse required variables from .env.example
        try:
            with open(env_example) as f:
                lines = f.readlines()
            
            required_vars = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    var_name = line.split('=')[0].strip()
                    if var_name:
                        required_vars.append(var_name)
            
            if required_vars:
                return f".env file missing (copy from .env.example and set: {', '.join(required_vars[:3])}...)"
        except Exception:
            pass
    
    return ""


def format_proactive_check_results(fixes: List[str], warnings: List[str]) -> str:
    """Format proactive check results for display."""
    if not fixes and not warnings:
        return ""
    
    lines = ["\n**🔧 PROACTIVE CHECKS:**\n"]
    
    if fixes:
        lines.append("**Auto-fixes applied:**")
        for fix in fixes:
            lines.append(f"  ✅ {fix}")
        lines.append("")
    
    if warnings:
        lines.append("**Warnings:**")
        for warning in warnings:
            lines.append(f"  ⚠️  {warning}")
        lines.append("")
    
    return "\n".join(lines)
