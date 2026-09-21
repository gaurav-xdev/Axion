"""Unit tests for the Software Engineering Agent."""

import pytest
from packages.agent.engineering import (
    CodeInspectionReport,
    SoftwareEngineeringAgent,
    software_engineering_agent,
)


def test_inspect_clean_python_code():
    code = (
        'import os\n'
        'import hmac\n'
        'from fastapi import FastAPI, Header\n\n'
        'app = FastAPI()\n\n'
        '@app.post("/webhook")\n'
        'def handle_event(x_sig: str = Header(None)):\n'
        '    return {"status": "ok"}\n'
    )

    report = software_engineering_agent.inspect_code_string(code)
    assert report.syntax_valid is True
    assert report.ast_parsed is True
    assert "fastapi.FastAPI" in report.imports
    assert "handle_event" in report.functions
    assert len(report.security_findings) == 0
    assert report.has_critical_defects is False


def test_inspect_dangerous_security_anti_patterns():
    dangerous_code = (
        'import os\n'
        'import subprocess\n\n'
        'def execute_cmd(user_input):\n'
        '    os.system(user_input)\n'
        '    eval(user_input)\n'
        '    subprocess.run("ls " + user_input, shell=True)\n'
        '    api_key = "sk_live_1234567890abcdef123456"\n'
    )

    report = software_engineering_agent.inspect_code_string(dangerous_code)
    assert report.syntax_valid is True
    assert len(report.security_findings) >= 3
    assert any("os.system" in f for f in report.security_findings)
    assert any("eval()" in f for f in report.security_findings)
    assert any("shell=True" in f for f in report.security_findings)
    assert report.has_critical_defects is True


def test_inspect_syntax_error():
    syntax_error_code = (
        'def broken_function(\n'
        '    print("missing closing paren"\n'
    )

    report = software_engineering_agent.inspect_code_string(syntax_error_code)
    assert report.syntax_valid is False
    assert len(report.syntax_errors) > 0
    assert report.has_critical_defects is True
