"""Sandboxed filesystem tools.
Strictly confined to /workspace/projects/{project_id}/ with path-traversal prevention.
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.shared.models import ToolRiskLevel
from packages.tools.base import BaseTool, ToolRequest


def resolve_sandboxed_path(project_id: Optional[str], requested_path: str) -> Path:
    """Confines requested paths strictly inside the designated project workspace."""
    if not project_id:
        # Fallback to general workspace
        base_dir = Path("workspace").resolve()
    else:
        # Sanitize project_id to prevent injection
        safe_proj = "".join(c for c in project_id if c.isalnum() or c in ("-", "_"))
        base_dir = (Path("workspace") / "projects" / safe_proj).resolve()

    base_dir.mkdir(parents=True, exist_ok=True)
    target = (base_dir / requested_path).resolve()

    # Path traversal check: must be strictly inside base_dir
    try:
        target.relative_to(base_dir)
    except ValueError:
        raise PermissionError(
            f"Path traversal violation: '{requested_path}' escapes project sandbox '{base_dir}'"
        )

    return target


class ReadFileInput(BaseModel):
    path: str = Field(description="Relative path inside the project workspace")


class ReadFileTool(BaseTool):
    name = "filesystem.read"
    description = "Read the contents of a file inside the sandboxed project workspace"
    risk_level = ToolRiskLevel.READ_ONLY
    input_schema = ReadFileInput
    required_permission = "tools:execute"

    async def execute(self, params: ReadFileInput, context: ToolRequest) -> Dict[str, Any]:
        target_path = resolve_sandboxed_path(context.project_id, params.path)
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f"File not found: {params.path}")

        content = target_path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return {
            "path": params.path,
            "content": content,
            "hash": file_hash,
            "size_bytes": len(content.encode("utf-8")),
        }


class WriteFileInput(BaseModel):
    path: str = Field(description="Relative path inside the project workspace")
    content: str = Field(description="Text content to write into the file")


class WriteFileTool(BaseTool):
    name = "filesystem.write"
    description = "Write text content to a file inside the sandboxed project workspace"
    risk_level = ToolRiskLevel.MEDIUM
    input_schema = WriteFileInput
    required_permission = "tools:execute"

    async def execute(self, params: WriteFileInput, context: ToolRequest) -> Dict[str, Any]:
        target_path = resolve_sandboxed_path(context.project_id, params.path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        target_path.write_text(params.content, encoding="utf-8")
        file_hash = hashlib.sha256(params.content.encode("utf-8")).hexdigest()
        return {
            "path": params.path,
            "status": "written",
            "hash": file_hash,
            "size_bytes": len(params.content.encode("utf-8")),
        }


class ListFilesInput(BaseModel):
    subpath: str = Field(default=".", description="Relative subdirectory to inspect")


class ListFilesTool(BaseTool):
    name = "filesystem.list"
    description = "List files and directories in the sandboxed project workspace"
    risk_level = ToolRiskLevel.READ_ONLY
    input_schema = ListFilesInput
    required_permission = "tools:execute"

    async def execute(self, params: ListFilesInput, context: ToolRequest) -> List[Dict[str, Any]]:
        target_path = resolve_sandboxed_path(context.project_id, params.subpath)
        if not target_path.exists():
            return []

        entries = []
        for entry in os.scandir(target_path):
            entries.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size_bytes": entry.stat().st_size if entry.is_file() else 0,
            })
        return entries
