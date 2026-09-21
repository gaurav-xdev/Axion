"""Software Engineering Agent.
Provides real deterministic software engineering workflows:
1. AST parsing and syntax tree inspection
2. Import and dependency analysis
3. Security linting (eval/exec, dangerous subprocess, hardcoded secrets, shell injection)
4. Sandboxed test execution and assertion verification
5. Self-correcting debugging loop
"""

import ast
from datetime import datetime, timezone
import os
from pathlib import Path
import py_compile
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.observability.logger import logger
from packages.tools.filesystem import resolve_sandboxed_path


class CodeInspectionReport(BaseModel):
    file_path: str
    syntax_valid: bool
    ast_parsed: bool
    imports: List[str] = Field(default_factory=list)
    classes: List[str] = Field(default_factory=list)
    functions: List[str] = Field(default_factory=list)
    syntax_errors: List[str] = Field(default_factory=list)
    security_findings: List[str] = Field(default_factory=list)
    has_critical_defects: bool = False


class TestExecutionReport(BaseModel):
    test_target: str
    passed: bool
    returncode: int
    output: str
    duration_ms: int


class SoftwareEngineeringAgent:
    """Rigorous engineering agent implementing static analysis, test execution, and debugging."""

    def inspect_code_string(self, code_str: str, file_name: str = "module.py") -> CodeInspectionReport:
        """Parses AST, maps symbols, and inspects for syntax errors and security anti-patterns."""
        syntax_errors: List[str] = []
        security_findings: List[str] = []
        imports: List[str] = []
        classes: List[str] = []
        functions: List[str] = []
        ast_parsed = False
        parsed_tree = None

        # 1. Syntax Parsing
        try:
            parsed_tree = ast.parse(code_str, filename=file_name)
            ast_parsed = True
        except SyntaxError as syn_err:
            syntax_errors.append(f"SyntaxError at line {syn_err.lineno}: {syn_err.msg}")
        except Exception as ex:
            syntax_errors.append(f"Parse failure: {str(ex)}")

        # 2. AST Visitor Inspection
        if parsed_tree:
            for node in ast.walk(parsed_tree):
                # Imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for alias in node.names:
                        imports.append(f"{mod}.{alias.name}")

                # Definitions
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    functions.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)

                # Security Anti-Patterns Check
                elif isinstance(node, ast.Call):
                    # Dangerous eval / exec
                    if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                        security_findings.append(f"Dangerous call to {node.func.id}() detected at line {node.lineno}")

                    # subprocess with shell=True
                    elif isinstance(node.func, ast.Attribute) and node.func.attr in ("Popen", "run", "call", "check_output"):
                        for kw in node.keywords:
                            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                security_findings.append(f"subprocess invoked with shell=True at line {node.lineno}")

                    # os.system
                    elif (
                        isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "os"
                        and node.func.attr == "system"
                    ):
                        security_findings.append(f"Insecure call to os.system() detected at line {node.lineno}")

        # 3. Regex Linting for Hardcoded Secrets
        secret_patterns = [
            (r'(?i)(api[_-]?key|secret|password|token)\s*=\s*["\'][a-zA-Z0-9_\-]{16,}["\']', "Potential hardcoded secret or API credential"),
        ]
        for pattern, desc in secret_patterns:
            if re.search(pattern, code_str):
                security_findings.append(desc)

        has_critical = (len(syntax_errors) > 0) or (len(security_findings) > 0)

        return CodeInspectionReport(
            file_path=file_name,
            syntax_valid=len(syntax_errors) == 0,
            ast_parsed=ast_parsed,
            imports=list(dict.fromkeys(imports)),
            classes=classes,
            functions=functions,
            syntax_errors=syntax_errors,
            security_findings=security_findings,
            has_critical_defects=has_critical,
        )

    def inspect_file_on_disk(self, project_id: str, relative_path: str) -> CodeInspectionReport:
        """Inspects and compiles a concrete file inside the sandboxed project workspace."""
        target_path = resolve_sandboxed_path(project_id, relative_path)
        if not target_path.exists():
            return CodeInspectionReport(
                file_path=relative_path,
                syntax_valid=False,
                ast_parsed=False,
                syntax_errors=[f"File not found on disk: {relative_path}"],
                has_critical_defects=True,
            )

        content = target_path.read_text(encoding="utf-8", errors="replace")
        report = self.inspect_code_string(content, file_name=relative_path)

        # Py-compile verification for Python files
        if target_path.suffix == ".py" and report.syntax_valid:
            try:
                py_compile.compile(str(target_path), doraise=True)
            except Exception as ex:
                report.syntax_valid = False
                report.syntax_errors.append(f"py_compile failure: {str(ex)}")
                report.has_critical_defects = True

        return report

    def run_sandboxed_test_suite(
        self,
        project_id: str,
        test_file_rel: str,
        timeout_seconds: int = 30,
    ) -> TestExecutionReport:
        """Executes pytest on a test file strictly inside the project sandbox."""
        test_path = resolve_sandboxed_path(project_id, test_file_rel)
        if not test_path.exists():
            return TestExecutionReport(
                test_target=test_file_rel,
                passed=False,
                returncode=-1,
                output=f"Test file '{test_file_rel}' does not exist",
                duration_ms=0,
            )

        start = time.monotonic()
        try:
            cmd = [sys.executable, "-m", "pytest", str(test_path), "-v"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(test_path.parent),
            )
            dur = int((time.monotonic() - start) * 1000)
            return TestExecutionReport(
                test_target=test_file_rel,
                passed=(res.returncode == 0),
                returncode=res.returncode,
                output=res.stdout + "\n" + res.stderr,
                duration_ms=dur,
            )
        except subprocess.TimeoutExpired:
            dur = int((time.monotonic() - start) * 1000)
            return TestExecutionReport(
                test_target=test_file_rel,
                passed=False,
                returncode=-2,
                output=f"Execution timed out after {timeout_seconds}s",
                duration_ms=dur,
            )
        except Exception as ex:
            dur = int((time.monotonic() - start) * 1000)
            return TestExecutionReport(
                test_target=test_file_rel,
                passed=False,
                returncode=-3,
                output=f"Subprocess execution error: {ex}",
                duration_ms=dur,
            )

    def self_heal_syntax_defect(self, project_id: str, relative_path: str, error_msg: str) -> bool:
        """Applies deterministic syntax remediation heuristics for common agent mistakes."""
        target_path = resolve_sandboxed_path(project_id, relative_path)
        if not target_path.exists():
            return False

        content = target_path.read_text(encoding="utf-8", errors="replace")
        healed = False

        # 1. Unclosed string literal or missing closing quote
        if "unclosed string literal" in error_msg.lower() or "eol while scanning string" in error_msg.lower():
            lines = content.splitlines()
            fixed_lines = []
            for line in lines:
                # If odd number of quotes on a single line, close it
                if line.count('"') % 2 != 0 and '"""' not in line:
                    line += '"'
                    healed = True
                elif line.count("'") % 2 != 0 and "'''" not in line:
                    line += "'"
                    healed = True
                fixed_lines.append(line)
            if healed:
                content = "\n".join(fixed_lines)

        # 2. Missing trailing newline or unclosed bracket
        if content.count("(") > content.count(")"):
            content += ")" * (content.count("(") - content.count(")"))
            healed = True
        if content.count("{") > content.count("}"):
            content += "}" * (content.count("{") - content.count("}"))
            healed = True
        if content.count("[") > content.count("]"):
            content += "]" * (content.count("[") - content.count("]"))
            healed = True

        if healed:
            target_path.write_text(content, encoding="utf-8")
            report = self.inspect_file_on_disk(project_id, relative_path)
            return report.syntax_valid

        return False


software_engineering_agent = SoftwareEngineeringAgent()
