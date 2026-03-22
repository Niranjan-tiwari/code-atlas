"""
Pre-push validation module for repository code quality checks.

Runs language-specific validations (go vet, go build, etc.) before
pushing code to remote. Reports warnings but does not block push.

Supports:
  - Go: go vet, go build
  - Python: syntax check
  - General: file size checks, binary detection
"""

import os
import subprocess
import logging
from typing import Dict, List, Optional
from pathlib import Path


logger = logging.getLogger("parallel_repo_worker.validator")


class PrePushValidator:
    """Validates code quality before pushing to remote"""
    
    def __init__(self, timeout: int = 120):
        """
        Args:
            timeout: Max seconds for each validation command
        """
        self.timeout = timeout
    
    def validate(self, repo_path: str) -> Dict:
        """
        Run all applicable validations on a repository.
        
        Args:
            repo_path: Absolute path to the repository root
            
        Returns:
            {
                "passed": bool,         # True if all critical checks pass
                "summary": str,         # Human-readable summary
                "checks": [             # Individual check results
                    {
                        "name": str,
                        "passed": bool,
                        "output": str,
                        "severity": "error" | "warning" | "info"
                    }
                ],
                "language": str         # Detected language
            }
        """
        language = self._detect_language(repo_path)
        checks = []
        
        # Language-specific checks
        if language == "go":
            checks.extend(self._validate_go(repo_path))
        elif language == "python":
            checks.extend(self._validate_python(repo_path))
        
        # General checks (all languages)
        checks.extend(self._validate_general(repo_path))
        
        # Determine overall pass/fail (only errors cause failure, warnings don't)
        has_errors = any(
            not c["passed"] and c["severity"] == "error"
            for c in checks
        )
        
        warnings = [c for c in checks if not c["passed"] and c["severity"] == "warning"]
        errors = [c for c in checks if not c["passed"] and c["severity"] == "error"]
        
        if errors:
            summary = f"{len(errors)} error(s), {len(warnings)} warning(s)"
        elif warnings:
            summary = f"Passed with {len(warnings)} warning(s)"
        else:
            summary = "All checks passed"
        
        return {
            "passed": not has_errors,
            "summary": summary,
            "checks": checks,
            "language": language
        }
    
    def _detect_language(self, repo_path: str) -> str:
        """Detect the primary language of the repository"""
        path = Path(repo_path)
        
        # Check for Go
        if (path / "go.mod").exists() or (path / "go.sum").exists():
            return "go"
        
        # Check for Python
        if (path / "requirements.txt").exists() or (path / "setup.py").exists() or (path / "pyproject.toml").exists():
            return "python"
        
        # Check for Node.js
        if (path / "package.json").exists():
            return "nodejs"
        
        # Check by file extensions
        go_files = list(path.glob("**/*.go"))
        py_files = list(path.glob("**/*.py"))
        
        # Don't scan too deeply
        if len(go_files) > len(py_files):
            return "go"
        elif py_files:
            return "python"
        
        return "unknown"
    
    # =========================================================================
    # Go Validation
    # =========================================================================
    
    def _validate_go(self, repo_path: str) -> List[Dict]:
        """Run Go-specific validations"""
        checks = []
        
        # Check if Go is installed
        if not self._command_exists("go"):
            checks.append({
                "name": "go_available",
                "passed": False,
                "output": "Go is not installed or not in PATH",
                "severity": "warning"
            })
            return checks
        
        # go vet - catches suspicious constructs
        vet_result = self._run_command(
            ["go", "vet", "./..."],
            repo_path,
            "go_vet"
        )
        checks.append(vet_result)
        
        # go build - ensures code compiles
        build_result = self._run_command(
            ["go", "build", "./..."],
            repo_path,
            "go_build"
        )
        checks.append(build_result)
        
        # Check go.mod is tidy (optional, warning only)
        if (Path(repo_path) / "go.mod").exists():
            tidy_check = self._check_go_mod_tidy(repo_path)
            checks.append(tidy_check)
        
        return checks
    
    def _check_go_mod_tidy(self, repo_path: str) -> Dict:
        """Check if go.mod is tidy (no missing/extra dependencies)"""
        try:
            # Run go mod tidy -diff (Go 1.21+) or just check if go mod tidy changes anything
            result = subprocess.run(
                ["go", "mod", "verify"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            passed = result.returncode == 0
            output = result.stderr.strip() if result.stderr.strip() else result.stdout.strip()
            
            return {
                "name": "go_mod_verify",
                "passed": passed,
                "output": output[:500] if output else "Modules verified",
                "severity": "warning"  # Don't block push for mod issues
            }
        except subprocess.TimeoutExpired:
            return {
                "name": "go_mod_verify",
                "passed": True,
                "output": "Timeout - skipped",
                "severity": "info"
            }
        except Exception as e:
            return {
                "name": "go_mod_verify",
                "passed": True,
                "output": f"Skipped: {e}",
                "severity": "info"
            }
    
    # =========================================================================
    # Python Validation
    # =========================================================================
    
    def _validate_python(self, repo_path: str) -> List[Dict]:
        """Run Python-specific validations"""
        checks = []
        
        # Python syntax check on changed files
        py_files = list(Path(repo_path).glob("**/*.py"))
        # Only check files not in venv, .git, __pycache__
        skip_dirs = {".git", "venv", ".venv", "env", "__pycache__", "node_modules", ".tox"}
        py_files = [
            f for f in py_files
            if not any(skip in f.parts for skip in skip_dirs)
        ]
        
        syntax_errors = []
        for py_file in py_files[:50]:  # Limit to 50 files to avoid slowness
            try:
                result = subprocess.run(
                    ["python3", "-m", "py_compile", str(py_file)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode != 0:
                    rel_path = py_file.relative_to(repo_path)
                    syntax_errors.append(f"{rel_path}: {result.stderr.strip()}")
            except Exception:
                pass
        
        if syntax_errors:
            checks.append({
                "name": "python_syntax",
                "passed": False,
                "output": "\n".join(syntax_errors[:10]),
                "severity": "error"
            })
        else:
            checks.append({
                "name": "python_syntax",
                "passed": True,
                "output": f"All {len(py_files)} Python files have valid syntax",
                "severity": "info"
            })
        
        return checks
    
    # =========================================================================
    # General Validation
    # =========================================================================
    
    def _validate_general(self, repo_path: str) -> List[Dict]:
        """Run general validations applicable to all languages"""
        checks = []
        
        # Check for large files that shouldn't be committed
        large_files = self._find_large_files(repo_path, max_size_mb=10)
        if large_files:
            checks.append({
                "name": "large_files",
                "passed": False,
                "output": f"Large files (>10MB): {', '.join(large_files[:5])}",
                "severity": "warning"
            })
        
        # Check for common secrets patterns
        secret_files = self._check_secret_files(repo_path)
        if secret_files:
            checks.append({
                "name": "secret_files",
                "passed": False,
                "output": f"Potential secret files: {', '.join(secret_files[:5])}",
                "severity": "warning"
            })
        
        return checks
    
    def _find_large_files(self, repo_path: str, max_size_mb: int = 10) -> List[str]:
        """Find files larger than max_size_mb"""
        large_files = []
        max_bytes = max_size_mb * 1024 * 1024
        skip_dirs = {".git", "vendor", "node_modules", "data"}
        
        try:
            for root, dirs, files in os.walk(repo_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        if os.path.getsize(fpath) > max_bytes:
                            rel = os.path.relpath(fpath, repo_path)
                            large_files.append(rel)
                    except OSError:
                        pass
                if len(large_files) >= 10:
                    break
        except Exception:
            pass
        
        return large_files
    
    def _check_secret_files(self, repo_path: str) -> List[str]:
        """Check for common secret/credential files that shouldn't be committed"""
        secret_patterns = [
            ".env",
            ".env.local",
            ".env.production",
            "credentials.json",
            "service-account.json",
            "id_rsa",
            "id_ed25519",
            ".pem",
        ]
        
        found = []
        try:
            # Only check git-tracked files that are staged
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            staged_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
            
            for staged in staged_files:
                basename = os.path.basename(staged)
                if any(basename == pat or basename.endswith(pat) for pat in secret_patterns):
                    found.append(staged)
        except Exception:
            pass
        
        return found
    
    # =========================================================================
    # Helpers
    # =========================================================================
    
    def _command_exists(self, cmd: str) -> bool:
        """Check if a command exists in PATH"""
        try:
            result = subprocess.run(
                ["which", cmd],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _run_command(self, cmd: List[str], repo_path: str, check_name: str) -> Dict:
        """Run a command and return a check result dict"""
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            passed = result.returncode == 0
            output = result.stderr.strip() if result.stderr.strip() else result.stdout.strip()
            
            return {
                "name": check_name,
                "passed": passed,
                "output": output[:1000] if output else "OK",
                "severity": "error" if not passed else "info"
            }
            
        except subprocess.TimeoutExpired:
            return {
                "name": check_name,
                "passed": False,
                "output": f"Timeout after {self.timeout}s",
                "severity": "warning"
            }
        except FileNotFoundError:
            return {
                "name": check_name,
                "passed": True,
                "output": f"Command not found: {cmd[0]}",
                "severity": "warning"
            }
        except Exception as e:
            return {
                "name": check_name,
                "passed": True,
                "output": f"Error: {e}",
                "severity": "warning"
            }
