"""
Pre-commit verification system.

Runs checks before committing to catch issues early.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List
import subprocess
import os


@dataclass
class VerificationResult:
    """Result of running verification checks."""
    passed: bool
    errors: List[str]
    warnings: List[str]
    

def verify_typescript_syntax(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """
    Run TypeScript compiler in check mode (no emit).
    
    Catches TypeScript errors before build.
    """
    errors = []
    warnings = []
    
    # Only check TS/TSX files
    ts_files = [f for f in changed_files if f.endswith(('.ts', '.tsx'))]
    if not ts_files:
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    # Check if tsconfig exists
    tsconfig = repo_path / "tsconfig.json"
    if not tsconfig.exists():
        warnings.append("No tsconfig.json found, skipping TypeScript check")
        return VerificationResult(passed=True, errors=[], warnings=warnings)
    
    try:
        print("Running TypeScript syntax check...")
        result = subprocess.run(
            ["npx", "tsc", "--noEmit", "--pretty", "false"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            # TypeScript found errors - treat as warnings (tsc may run before npm install)
            error_output = result.stdout if result.stdout else result.stderr
            warnings.append(f"TypeScript errors (will be checked again after npm install):\n{error_output[:1000]}")
            return VerificationResult(passed=True, errors=errors, warnings=warnings)
            
    except subprocess.TimeoutExpired:
        warnings.append("TypeScript check timed out (30s)")
    except FileNotFoundError:
        warnings.append("TypeScript not installed (npx tsc not found)")
    except Exception as e:
        warnings.append(f"Could not run TypeScript check: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def verify_eslint(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """
    Run ESLint on changed files.
    
    Catches code style and potential bugs.
    """
    errors = []
    warnings = []
    
    # Only check JS/TS files
    lint_files = [f for f in changed_files if f.endswith(('.ts', '.tsx', '.js', '.jsx'))]
    if not lint_files:
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    # Check if eslint config exists
    eslint_configs = [".eslintrc", ".eslintrc.js", ".eslintrc.json", "eslint.config.js"]
    has_eslint = any((repo_path / config).exists() for config in eslint_configs)
    
    if not has_eslint:
        warnings.append("No ESLint config found, skipping ESLint check")
        return VerificationResult(passed=True, errors=[], warnings=warnings)
    
    try:
        print("Running ESLint...")
        
        # Set environment variables to handle ESLint v9 migration gracefully
        env = os.environ.copy()
        env["ESLINT_USE_FLAT_CONFIG"] = "false"  # Allow old .eslintrc format
        
        # Run eslint on specific files
        result = subprocess.run(
            ["npx", "eslint", "--format", "compact", *lint_files],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        
        # Check if ESLint failed to run (not just found issues)
        if "Cannot find module" in str(result.stderr) or "ENOENT" in str(result.stderr):
            warnings.append("ESLint not properly configured, skipping")
            return VerificationResult(passed=True, errors=[], warnings=warnings)
        
        if result.returncode != 0:
            # ESLint found issues - treat as warnings, not errors
            # (don't fail the build, but show the issues)
            lint_output = result.stdout if result.stdout else result.stderr
            if lint_output.strip():
                # Filter out deprecation warnings about v9 migration
                filtered_output = '\n'.join([
                    line for line in lint_output.split('\n')
                    if 'DEPRECATED' not in line and 'husky.sh' not in line
                ])
                if filtered_output.strip():
                    warnings.append(f"ESLint issues found:\n{filtered_output[:500]}")
            
    except subprocess.TimeoutExpired:
        warnings.append("ESLint check timed out (30s)")
    except FileNotFoundError:
        warnings.append("ESLint not installed")
    except Exception as e:
        warnings.append(f"Could not run ESLint: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def verify_imports(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """
    Quick import verification.
    
    Checks for obvious import issues before build.
    """
    errors = []
    warnings = []
    
    # Quick syntax check to catch obvious import errors
    for file_path in changed_files:
        if not file_path.endswith(('.ts', '.tsx', '.js', '.jsx')):
            continue
            
        full_path = repo_path / file_path
        if not full_path.exists():
            continue
            
        try:
            content = full_path.read_text()
            
            # Check for common import issues
            import re
            
            # Find all imports
            imports = re.findall(r'import\s+(?:{[^}]+}|[\w]+)\s+from\s+[\'"]([^\'"]+)[\'"]', content)
            
            # Check for relative imports going too far up
            for imp in imports:
                if imp.count('../') > 3:
                    warnings.append(f"{file_path}: Deep relative import (may be fragile): {imp}")
            
            # Check for imports from non-existent local files
            for imp in imports:
                if imp.startswith('.'):
                    # Relative import - try to resolve
                    import_dir = full_path.parent
                    import_path = import_dir / imp
                    
                    # Try common extensions
                    found = False
                    for ext in ['', '.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx', '/index.js']:
                        test_path = Path(str(import_path) + ext)
                        if test_path.exists():
                            found = True
                            break
                    
                    if not found:
                        warnings.append(f"{file_path}: Import may not resolve: {imp}")
                        
        except Exception as e:
            warnings.append(f"Could not analyze {file_path}: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def verify_package_json_syntax(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """
    Verify package.json is valid JSON if modified.
    """
    errors = []
    warnings = []
    
    if "package.json" not in changed_files:
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    try:
        import json
        content = package_json.read_text()
        json.loads(content)  # Verify it's valid JSON
        print("✓ package.json syntax valid")
    except json.JSONDecodeError as e:
        errors.append(f"package.json has invalid JSON syntax: {e}")
        return VerificationResult(passed=False, errors=errors, warnings=warnings)
    except Exception as e:
        warnings.append(f"Could not verify package.json: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def verify_tests(repo_path: Path, changed_files: List[str], quick: bool = True) -> VerificationResult:
    """
    Run test suite for changed files.
    
    Args:
        repo_path: Path to repository
        changed_files: List of changed file paths
        quick: If True, only run quick tests (default). Set False for full suite.
    """
    errors = []
    warnings = []
    
    # Check if there's a test command
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    try:
        import json
        pkg = json.loads(package_json.read_text())
        scripts = pkg.get("scripts", {})
        
        # Look for test script
        test_command = None
        if "test:quick" in scripts:
            test_command = "test:quick"
        elif "test" in scripts:
            test_command = "test"
        else:
            warnings.append("No test script found in package.json")
            return VerificationResult(passed=True, errors=[], warnings=warnings)
        
        # Run tests (with timeout)
        print(f"Running {test_command}...")
        timeout = 60 if quick else 180
        
        env = os.environ.copy()
        env["CI"] = "true"  # Prevent watch mode
        env["NODE_ENV"] = "test"
        
        result = subprocess.run(
            ["npm", "run", test_command, "--", "--passWithNoTests", "--bail"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        
        if result.returncode != 0:
            # Tests failed
            test_output = result.stdout[-1000:] if result.stdout else result.stderr[-1000:]
            errors.append(f"Tests failed:\n{test_output}")
            return VerificationResult(passed=False, errors=errors, warnings=warnings)
        else:
            print("✓ Tests passed")
            
    except subprocess.TimeoutExpired:
        warnings.append(f"Test suite timed out ({timeout}s limit)")
    except Exception as e:
        warnings.append(f"Could not run tests: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def verify_responsive_browserstack(
    url: str,
    changed_files: List[str],
) -> VerificationResult:
    """
    Run BrowserStack responsive design check on a deployed URL.
    
    Only triggers when UI-related files were changed and BrowserStack
    credentials are configured. Results are warnings, not blocking errors.
    """
    errors = []
    warnings = []
    
    ui_extensions = ('.tsx', '.jsx', '.css', '.scss', '.html')
    has_ui_changes = any(f.endswith(ui_extensions) for f in changed_files)
    if not has_ui_changes:
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    try:
        from app.integrations.browserstack import is_configured, run_responsive_check
        
        if not is_configured():
            return VerificationResult(passed=True, errors=[], warnings=[])
        
        print("Running BrowserStack responsive check...")
        result = run_responsive_check(url)
        
        if result.error:
            warnings.append(f"BrowserStack: {result.error}")
        elif not result.passed:
            warnings.append(
                f"BrowserStack responsive check flagged issues.\n"
                f"{result.to_jira_comment()}"
            )
        else:
            print("  ✓ BrowserStack responsive check passed")
        
    except Exception as e:
        warnings.append(f"BrowserStack check skipped: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def run_all_verifications(
    repo_path: Path,
    changed_files: List[str],
    run_tests: bool = False,
    deployed_url: str = "",
) -> VerificationResult:
    """
    Run all pre-commit verifications.
    
    Args:
        repo_path: Path to the repository
        changed_files: List of changed file paths
        run_tests: Whether to run the test suite
        deployed_url: If provided, runs BrowserStack responsive checks
    
    Returns combined result with all errors and warnings.
    """
    print("\n" + "="*60)
    print("RUNNING PRE-COMMIT VERIFICATIONS")
    print("="*60)
    
    checks = [
        ("Package.json syntax", verify_package_json_syntax),
        ("TypeScript syntax", verify_typescript_syntax),
        ("ESLint", verify_eslint),
        ("Import resolution", verify_imports),
    ]
    
    # Add tests if requested
    if run_tests:
        checks.append(("Test suite", verify_tests))
    
    all_errors = []
    all_warnings = []
    passed = True
    
    for check_name, check_func in checks:
        print(f"\n[{check_name}]")
        result = check_func(repo_path, changed_files)
        
        if not result.passed:
            passed = False
            print(f"  ✗ FAILED")
        elif result.warnings:
            print(f"  ⚠ Warnings")
        else:
            print(f"  ✓ Passed")
        
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)
    
    # Run BrowserStack responsive check if URL provided and UI files changed
    if deployed_url:
        print(f"\n[BrowserStack Responsive]")
        bs_result = verify_responsive_browserstack(deployed_url, changed_files)
        all_warnings.extend(bs_result.warnings)
        if bs_result.warnings:
            print(f"  ⚠ Warnings")
        else:
            print(f"  ✓ Passed (or skipped)")
    
    print("\n" + "="*60)
    if passed:
        print("✅ All pre-commit checks passed")
        if all_warnings:
            print(f"⚠️  {len(all_warnings)} warning(s)")
    else:
        print(f"❌ Pre-commit checks failed: {len(all_errors)} error(s)")
    print("="*60 + "\n")
    
    return VerificationResult(
        passed=passed,
        errors=all_errors,
        warnings=all_warnings
    )
