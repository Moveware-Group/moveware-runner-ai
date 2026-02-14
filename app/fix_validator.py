"""
Fix Validation System

Validates AI-generated fixes BEFORE applying them to catch common mistakes.
Prevents cascading failures where each fix introduces new errors.
"""
import re
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any


class FixValidator:
    """Validates fixes before they're applied to the codebase."""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.validation_errors: List[str] = []
        self.validation_warnings: List[str] = []
    
    def validate_fix(self, fix_payload: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
        """
        Validate a fix payload before applying it.
        
        Args:
            fix_payload: The AI's fix response (files array)
        
        Returns:
            (is_valid, errors, warnings)
        """
        self.validation_errors = []
        self.validation_warnings = []
        
        files = fix_payload.get("files", [])
        
        if not files:
            self.validation_errors.append("No files in fix payload")
            return False, self.validation_errors, self.validation_warnings
        
        # Run all validation checks
        for file_op in files:
            path = file_op.get("path", "")
            action = file_op.get("action", "update")
            content = file_op.get("content", "")
            
            if not path:
                self.validation_errors.append("File operation missing path")
                continue
            
            if action in ("create", "update"):
                if not content:
                    self.validation_errors.append(f"{path}: Empty content")
                    continue
                
                # Validate TypeScript/JavaScript files
                if path.endswith((".ts", ".tsx", ".js", ".jsx")):
                    self._validate_typescript_file(path, content)
                
                # Validate imports/exports consistency
                if path.endswith((".ts", ".tsx", ".js", ".jsx")):
                    self._validate_imports_exports(path, content, files)
                
                # Check for regression (only for updates, not new files)
                if action == "update":
                    self._check_for_regression(path, content)
        
        is_valid = len(self.validation_errors) == 0
        return is_valid, self.validation_errors, self.validation_warnings
    
    def _check_for_regression(self, path: str, new_content: str) -> None:
        """
        Check if the update removes existing functionality.
        
        Detects:
        - Removed functions/components
        - Removed exports
        - Significant code deletion (>30% of file)
        """
        file_path = self.repo_path / path
        
        if not file_path.exists():
            # New file, no regression possible
            return
        
        try:
            old_content = file_path.read_text(encoding="utf-8")
        except Exception:
            # Can't read old file, skip regression check
            return
        
        # Extract exported functions/components from old content
        old_exports = self._extract_exports(old_content)
        new_exports = self._extract_exports(new_content)
        
        # Check for removed exports
        removed_exports = old_exports - new_exports
        
        if removed_exports:
            self.validation_warnings.append(
                f"{path}: REGRESSION WARNING - Removed exports: {', '.join(sorted(removed_exports))}\n"
                f"  These exports may be used by other files. Verify this is intentional."
            )
        
        # Check for significant code deletion
        old_lines = [l.strip() for l in old_content.split('\n') if l.strip() and not l.strip().startswith('//')]
        new_lines = [l.strip() for l in new_content.split('\n') if l.strip() and not l.strip().startswith('//')]
        
        deletion_ratio = 1 - (len(new_lines) / max(len(old_lines), 1))
        
        if deletion_ratio > 0.3 and len(old_lines) > 20:  # >30% deleted and file had substance
            self.validation_warnings.append(
                f"{path}: REGRESSION WARNING - Significant code deletion detected\n"
                f"  Old: {len(old_lines)} lines, New: {len(new_lines)} lines ({deletion_ratio*100:.0f}% deleted)\n"
                f"  Verify existing functionality is preserved."
            )
    
    def _extract_exports(self, content: str) -> Set[str]:
        """Extract exported function/component names from content."""
        exports = set()
        
        # export function/const/class NAME
        for pattern in [
            r'export\s+(?:async\s+)?function\s+(\w+)',
            r'export\s+const\s+(\w+)\s*[:=]',
            r'export\s+class\s+(\w+)',
        ]:
            for match in re.finditer(pattern, content):
                exports.add(match.group(1))
        
        # export { name1, name2 }
        for match in re.finditer(r'export\s*\{([^}]+)\}', content):
            exports_block = match.group(1)
            for name in re.findall(r'(\w+)(?:\s+as\s+\w+)?', exports_block):
                if name not in ('from', 'as'):  # Filter out keywords
                    exports.add(name)
        
        return exports
    
    def _validate_typescript_file(self, path: str, content: str) -> None:
        """Validate TypeScript/JavaScript file for common issues."""
        
        # Check 1: Duplicate declarations
        self._check_duplicate_declarations(path, content)
        
        # Check 2: Syntax errors (basic checks)
        self._check_basic_syntax(path, content)
        
        # Check 3: Missing semicolons/braces
        self._check_balanced_braces(path, content)
    
    def _check_duplicate_declarations(self, path: str, content: str) -> None:
        """Check for duplicate const/let/var/function/class declarations at same scope."""
        
        # Extract function/class boundaries to understand scope
        function_ranges = []
        for match in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*\{', content):
            start = match.end()
            # Find matching closing brace (simplified - doesn't handle nested functions perfectly)
            brace_count = 1
            pos = start
            while pos < len(content) and brace_count > 0:
                if content[pos] == '{':
                    brace_count += 1
                elif content[pos] == '}':
                    brace_count -= 1
                pos += 1
            function_ranges.append((match.start(), pos, match.group(1)))
        
        # Check declarations at module level (outside functions) and top-level exports
        # These MUST be unique
        module_level_declarations = {}
        
        # const/let/var declarations
        for match in re.finditer(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*[:=]', content):
            name = match.group(1)
            pos = match.start()
            
            # Check if this is inside a function
            in_function = False
            for func_start, func_end, func_name in function_ranges:
                if func_start < pos < func_end:
                    in_function = True
                    break
            
            # Only check module-level declarations for duplicates
            # (same variable name is OK in different function scopes)
            if not in_function:
                if name in module_level_declarations:
                    self.validation_errors.append(
                        f"{path}: Duplicate module-level declaration of '{name}' "
                        f"(lines ~{content[:match.start()].count(chr(10))+1} and "
                        f"~{content[:module_level_declarations[name]].count(chr(10))+1})"
                    )
                else:
                    module_level_declarations[name] = match.start()
        
        # function declarations (always module-level)
        for match in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(', content):
            name = match.group(1)
            if name in module_level_declarations:
                self.validation_errors.append(
                    f"{path}: Duplicate declaration of function '{name}'"
                )
            else:
                module_level_declarations[name] = match.start()
        
        # class declarations (always module-level)
        for match in re.finditer(r'(?:export\s+)?class\s+(\w+)', content):
            name = match.group(1)
            if name in module_level_declarations:
                self.validation_errors.append(
                    f"{path}: Duplicate declaration of class '{name}'"
                )
            else:
                module_level_declarations[name] = match.start()
    
    def _check_basic_syntax(self, path: str, content: str) -> None:
        """Check for basic syntax errors."""
        
        # Check for common syntax errors
        if content.count('{') != content.count('}'):
            diff = abs(content.count('{') - content.count('}'))
            self.validation_errors.append(
                f"{path}: Unbalanced braces (difference: {diff})"
            )
        
        if content.count('(') != content.count(')'):
            diff = abs(content.count('(') - content.count(')'))
            self.validation_errors.append(
                f"{path}: Unbalanced parentheses (difference: {diff})"
            )
        
        if content.count('[') != content.count(']'):
            diff = abs(content.count('[') - content.count(']'))
            self.validation_errors.append(
                f"{path}: Unbalanced brackets (difference: {diff})"
            )
        
        # Check for incomplete statements
        if re.search(r'export\s+(const|let|var|function|class)\s*$', content, re.MULTILINE):
            self.validation_errors.append(
                f"{path}: Incomplete export statement at end of file"
            )
    
    def _check_balanced_braces(self, path: str, content: str) -> None:
        """Check if braces are properly balanced."""
        
        # Track brace balance while ignoring strings and comments
        balance = 0
        in_string = False
        in_comment = False
        string_char = None
        
        i = 0
        while i < len(content):
            char = content[i]
            
            # Handle strings
            if char in ('"', "'", '`') and not in_comment:
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char and (i == 0 or content[i-1] != '\\'):
                    in_string = False
                    string_char = None
            
            # Handle comments
            elif not in_string:
                if content[i:i+2] == '//':
                    # Skip to end of line
                    while i < len(content) and content[i] != '\n':
                        i += 1
                    continue
                elif content[i:i+2] == '/*':
                    # Skip to end of block comment
                    while i < len(content) - 1 and content[i:i+2] != '*/':
                        i += 1
                    i += 2
                    continue
            
            # Count braces outside strings/comments
            if not in_string and not in_comment:
                if char == '{':
                    balance += 1
                elif char == '}':
                    balance -= 1
                    if balance < 0:
                        self.validation_errors.append(
                            f"{path}: Extra closing brace at position ~{i}"
                        )
                        return
            
            i += 1
        
        if balance != 0:
            self.validation_errors.append(
                f"{path}: Unbalanced braces (balance: {balance})"
            )
    
    def _validate_imports_exports(
        self, 
        path: str, 
        content: str, 
        all_files: List[Dict[str, Any]]
    ) -> None:
        """Validate that imports match available exports."""
        
        # Extract imports from this file
        imports = self._extract_imports(content)
        
        # For each import, check if we're also updating the source file
        for import_item in imports:
            source_path = import_item["from"]
            imported_names = import_item["names"]
            
            # Resolve the import path to an actual file path
            resolved_path = self._resolve_import_path(path, source_path)
            
            if not resolved_path:
                continue  # Can't resolve, skip validation
            
            # Check if we're updating this source file in this fix
            source_file_content = None
            for file_op in all_files:
                if self._normalize_path(file_op.get("path", "")) == self._normalize_path(resolved_path):
                    source_file_content = file_op.get("content", "")
                    break
            
            # If not in fix, try to read from disk
            if not source_file_content:
                source_file_path = self.repo_path / resolved_path
                if source_file_path.exists():
                    try:
                        source_file_content = source_file_path.read_text(encoding="utf-8")
                    except Exception:
                        pass
            
            if source_file_content:
                # Check if imported names are exported
                exports = self._extract_exports(source_file_content)
                
                for name in imported_names:
                    if name not in exports:
                        self.validation_errors.append(
                            f"{path}: Imports '{name}' from '{source_path}' but it's not exported"
                        )
    
    def _extract_imports(self, content: str) -> List[Dict[str, Any]]:
        """Extract import statements from file content."""
        imports = []
        
        # Match: import { foo, bar } from 'path'
        for match in re.finditer(
            r'import\s+\{([^}]+)\}\s+from\s+["\']([^"\']+)["\']',
            content
        ):
            names_str = match.group(1)
            from_path = match.group(2)
            
            # Parse imported names (handle 'type X', 'X as Y', etc.)
            names = []
            for part in names_str.split(','):
                part = part.strip()
                if part.startswith('type '):
                    part = part[5:].strip()
                if ' as ' in part:
                    part = part.split(' as ')[0].strip()
                if part:
                    names.append(part)
            
            imports.append({
                "names": names,
                "from": from_path
            })
        
        # Match: import foo from 'path' (default import)
        for match in re.finditer(
            r'import\s+(\w+)\s+from\s+["\']([^"\']+)["\']',
            content
        ):
            name = match.group(1)
            from_path = match.group(2)
            
            imports.append({
                "names": [name],
                "from": from_path,
                "default": True
            })
        
        return imports
    
    def _extract_exports(self, content: str) -> Set[str]:
        """Extract exported names from file content."""
        exports = set()
        
        # export const/let/var/function/class NAME
        for match in re.finditer(
            r'export\s+(?:const|let|var|function|class|async\s+function)\s+(\w+)',
            content
        ):
            exports.add(match.group(1))
        
        # export { foo, bar }
        for match in re.finditer(r'export\s+\{([^}]+)\}', content):
            names_str = match.group(1)
            for name in names_str.split(','):
                name = name.strip()
                if ' as ' in name:
                    # export { foo as bar } - 'bar' is the exported name
                    name = name.split(' as ')[1].strip()
                if name:
                    exports.add(name)
        
        # export default
        if 'export default' in content:
            exports.add('default')
        
        return exports
    
    def _resolve_import_path(self, importing_file: str, import_path: str) -> str:
        """
        Resolve an import path to an actual file path.
        
        Args:
            importing_file: The file doing the importing (e.g., "src/app/page.tsx")
            import_path: The import path (e.g., "@/lib/auth", "../utils")
        
        Returns:
            Resolved file path or empty string if can't resolve
        """
        # Handle TypeScript path aliases
        if import_path.startswith('@/'):
            # @/ typically maps to src/
            return import_path.replace('@/', 'src/')
        
        # Handle relative imports
        if import_path.startswith('.'):
            # Resolve relative to importing file's directory
            importing_dir = str(Path(importing_file).parent)
            resolved = str((Path(importing_dir) / import_path).resolve())
            # Make relative to repo root
            if resolved.startswith(str(self.repo_path)):
                resolved = resolved[len(str(self.repo_path))+1:]
            return resolved
        
        # Can't resolve node_modules imports
        return ""
    
    def _normalize_path(self, path: str) -> str:
        """Normalize a path for comparison."""
        # Remove common file extensions for comparison
        for ext in ['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx', '/index.js', '/index.jsx']:
            if path.endswith(ext):
                path = path[:-len(ext)]
                break
        
        # Normalize slashes
        return path.replace('\\', '/')


def validate_fix_before_apply(
    fix_payload: Dict[str, Any],
    repo_path: Path
) -> Tuple[bool, List[str], List[str]]:
    """
    Convenience function to validate a fix.
    
    Args:
        fix_payload: The AI's fix response
        repo_path: Path to repository
    
    Returns:
        (is_valid, errors, warnings)
    """
    validator = FixValidator(repo_path)
    return validator.validate_fix(fix_payload)
