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

        # Build a list of ALL scope boundaries (named functions, arrow callbacks,
        # describe/it/test/beforeEach blocks, etc.)
        scope_ranges = self._build_scope_ranges(content)

        module_level_declarations: dict = {}

        for match in re.finditer(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*[:=]', content):
            name = match.group(1)
            pos = match.start()

            if self._is_inside_scope(pos, scope_ranges):
                continue

            if name in module_level_declarations:
                self.validation_errors.append(
                    f"{path}: Duplicate module-level declaration of '{name}' "
                    f"(lines ~{content[:match.start()].count(chr(10))+1} and "
                    f"~{content[:module_level_declarations[name]].count(chr(10))+1})"
                )
            else:
                module_level_declarations[name] = match.start()

        for match in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(', content):
            name = match.group(1)
            if self._is_inside_scope(match.start(), scope_ranges):
                continue
            if name in module_level_declarations:
                self.validation_errors.append(
                    f"{path}: Duplicate declaration of function '{name}'"
                )
            else:
                module_level_declarations[name] = match.start()

        for match in re.finditer(r'(?:export\s+)?class\s+(\w+)', content):
            name = match.group(1)
            if self._is_inside_scope(match.start(), scope_ranges):
                continue
            if name in module_level_declarations:
                self.validation_errors.append(
                    f"{path}: Duplicate declaration of class '{name}'"
                )
            else:
                module_level_declarations[name] = match.start()

    @staticmethod
    def _build_scope_ranges(content: str) -> list:
        """
        Build a list of (start, end) ranges for ALL scope-creating constructs:
        named functions, arrow function callbacks (describe/it/test/beforeEach etc.),
        and any `=> {` arrow function body.
        """
        ranges = []

        # Named function declarations: function name(...) {
        # Handles: function, async function, export function, export default function,
        # export default async function
        for m in re.finditer(
            r'(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+\w+\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*\{',
            content,
        ):
            end = FixValidator._find_matching_brace(content, m.end() - 1)
            if end > m.start():
                ranges.append((m.start(), end))

        # Arrow function bodies: (...) => { or arg => {
        # Covers describe(() => {, it(() => {, test(() => {, beforeEach(() => {, etc.
        for m in re.finditer(r'=>\s*\{', content):
            brace_pos = content.index('{', m.start())
            end = FixValidator._find_matching_brace(content, brace_pos)
            if end > m.start():
                ranges.append((m.start(), end))

        ranges.sort(key=lambda r: r[0])
        return ranges

    @staticmethod
    def _find_matching_brace(content: str, open_pos: int) -> int:
        """Find the position of the matching closing brace, skipping strings and comments."""
        if open_pos >= len(content) or content[open_pos] != '{':
            return open_pos
        depth = 1
        i = open_pos + 1
        in_string = False
        string_char = None
        while i < len(content) and depth > 0:
            ch = content[i]
            if in_string:
                if ch == string_char and content[i - 1] != '\\':
                    in_string = False
                i += 1
                continue
            if ch in ('"', "'", '`'):
                in_string = True
                string_char = ch
                i += 1
                continue
            if content[i:i + 2] == '//':
                while i < len(content) and content[i] != '\n':
                    i += 1
                continue
            if content[i:i + 2] == '/*':
                i += 2
                while i < len(content) - 1 and content[i:i + 2] != '*/':
                    i += 1
                i += 2
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            i += 1
        return i

    @staticmethod
    def _is_inside_scope(pos: int, ranges: list) -> bool:
        """Check if a position falls inside any of the scope ranges."""
        for start, end in ranges:
            if start < pos < end:
                return True
            if start > pos:
                break
        return False

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
        """Validate that imports match available exports and resolve to real files."""
        
        imports = self._extract_imports(content)
        
        # Collect all file paths being created/updated in this fix batch
        fix_file_paths = set()
        for file_op in all_files:
            fp = file_op.get("path", "")
            if fp:
                fix_file_paths.add(self._normalize_path(fp))
        
        for import_item in imports:
            source_path = import_item["from"]
            imported_names = import_item["names"]
            
            # Skip node_modules / external package imports
            if not source_path.startswith('.') and not source_path.startswith('@/'):
                continue
            
            # Resolve the import path to an actual file path
            resolved_path = self._resolve_import_path(path, source_path)
            
            if not resolved_path:
                continue
            
            # Check if any file matching this import exists on disk (with extensions)
            file_exists_on_disk = self._find_file_on_disk(resolved_path)
            
            # Check if the file is being created/updated in this fix batch
            file_in_fix = self._normalize_path(resolved_path) in fix_file_paths
            if not file_in_fix:
                # Also check with common extensions
                for ext in ['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx']:
                    if self._normalize_path(resolved_path + ext) in fix_file_paths:
                        file_in_fix = True
                        resolved_path = resolved_path + ext
                        break
            
            # If the module doesn't exist anywhere, this fix will cause a build error
            if not file_exists_on_disk and not file_in_fix:
                self.validation_errors.append(
                    f"{path}: Imports from '{source_path}' but this module does not exist "
                    f"(not on disk, not in this fix). This will cause a 'Module not found' error."
                )
                continue
            
            # Now check that specific named imports are actually exported
            source_file_content = None
            for file_op in all_files:
                if self._normalize_path(file_op.get("path", "")) == self._normalize_path(resolved_path):
                    source_file_content = file_op.get("content", "")
                    break
            
            if not source_file_content and file_exists_on_disk:
                try:
                    source_file_content = file_exists_on_disk.read_text(encoding="utf-8")
                except Exception:
                    pass
            
            if source_file_content:
                exports = self._extract_exports(source_file_content)
                
                for name in imported_names:
                    if name not in exports and "default" not in import_item:
                        self.validation_errors.append(
                            f"{path}: Imports '{name}' from '{source_path}' but it's not exported"
                        )
    
    def _find_file_on_disk(self, resolved_path: str) -> "Path | None":
        """Check if a resolved import path matches any file on disk, trying common extensions."""
        # Try the path as-is and with common extensions
        candidates = [resolved_path]
        for ext in ['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx', '/index.js']:
            candidates.append(resolved_path + ext)
        
        # Also try without src/ prefix if it has one, and with src/ if it doesn't
        alt_paths = []
        for c in list(candidates):
            if c.startswith('src/'):
                alt_paths.append(c[4:])  # strip src/
            else:
                alt_paths.append('src/' + c)
            # Also try app/ prefix for Next.js
            if not c.startswith('app/'):
                alt_paths.append('app/' + c)
        candidates.extend(alt_paths)
        
        for candidate in candidates:
            full_path = self.repo_path / candidate
            if full_path.exists() and full_path.is_file():
                return full_path
        
        return None
    
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
        
        # export const/let/var/function/class/async function/type/interface/enum NAME
        for match in re.finditer(
            r'export\s+(?:declare\s+)?(?:const|let|var|function|class|async\s+function|type|interface|enum)\s+(\w+)',
            content
        ):
            exports.add(match.group(1))
        
        # export { foo, bar }
        for match in re.finditer(r'export\s+\{([^}]+)\}', content):
            names_str = match.group(1)
            for name in names_str.split(','):
                name = name.strip()
                # Handle 'type X' prefix
                if name.startswith('type '):
                    name = name[5:].strip()
                if ' as ' in name:
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
        
        Returns the base path without extension — _find_file_on_disk will try extensions.
        """
        if import_path.startswith('@/'):
            # @/ can map to src/ or root depending on tsconfig
            # Return the raw path without prefix; _find_file_on_disk tries both
            return import_path[2:]  # strip @/ → "lib/auth/session"
        
        if import_path.startswith('.'):
            importing_dir = str(Path(importing_file).parent)
            try:
                resolved = str((Path(importing_dir) / import_path))
                # Normalize .. etc
                resolved = str(Path(resolved))
                return resolved.replace('\\', '/')
            except Exception:
                return ""
        
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
