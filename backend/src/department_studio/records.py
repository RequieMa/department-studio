"""Project-level Markdown records: the durable audit trail for a room.

Records live outside any department workspace, inside the project's private data
directory. Humans and every runtime reach the same folder; the runtime bridge exposes
bounded list/read/write tools so Discuss agents can leave notes without shell access.
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from department_studio.domain import Conflict, Invalid, NotFound

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.md\Z")
MAX_CONTENT_BYTES = 512 * 1024
TEMPLATE = """# Project records

This folder is the project's durable audit trail. Keep room messages short; put
decisions, evidence, file paths, handoffs and longer reasoning here as Markdown.

- Name files `YYYY-MM-DD-topic.md`.
- Reference the exact absolute path when asking a department to read a record.
- Never store credentials, raw private reasoning or complete native transcripts.
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_name(value) -> str:
    if not isinstance(value, str):
        raise Invalid("Record name must be text.")
    name = value.strip()
    if not _NAME.fullmatch(name):
        raise Invalid("Record names must be a .md filename with letters, digits, dot, _ or -.")
    return name


def record_content(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Invalid("Record content must contain text.")
    if len(value.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise Invalid("Record content is too large.")
    return value


class RecordStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    def ensure(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        readme = self.root / "README.md"
        if not readme.exists():
            self._atomic(readme, TEMPLATE)
        return self

    def _safe(self, name: str) -> Path:
        name = record_name(name)
        path = (self.root / name).resolve()
        if path.parent != self.root:
            raise Invalid("Record path is outside this project's records folder.")
        return path

    def _atomic(self, path: Path, content: str):
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)

    @staticmethod
    def _entry(path: Path) -> dict:
        stat = path.stat()
        return {
            "name": path.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        }

    def list(self) -> list[dict]:
        self.ensure()
        entries = []
        for path in self.root.iterdir():
            try:
                if path.is_symlink() or not path.is_file() or not _NAME.fullmatch(path.name):
                    continue
                entries.append(self._entry(path))
            except OSError:
                continue
        return sorted(
            entries, key=lambda item: (item["modified"], item["name"].casefold()), reverse=True
        )

    def read(self, name: str) -> dict:
        path = self._safe(name)
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise NotFound("Record not found.") from exc
        except (OSError, UnicodeError) as exc:
            raise Invalid("Record could not be read.") from exc
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise Invalid("Record is too large to read in the room.")
        return {"name": path.name, "path": str(path), "content": content, "size": len(content)}

    def write(self, name: str, content: str, mode: str = "append") -> dict:
        content = record_content(content)
        if mode not in {"append", "replace", "create"}:
            raise Invalid("Record mode must be append, replace or create.")
        path = self._safe(name)
        self.ensure()
        if mode == "create" and path.exists():
            raise Conflict("A record with that name already exists.")
        if mode == "append" and path.exists():
            try:
                existing = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise Invalid("Record could not be read.") from exc
            merged = existing.rstrip() + "\n\n" + content.strip() + "\n"
            if len(merged.encode("utf-8")) > MAX_CONTENT_BYTES:
                raise Invalid("Appending would make the record too large.")
            content = merged
        self._atomic(path, content)
        return {
            "name": path.name,
            "path": str(path),
            "size": len(content.encode("utf-8")),
            "modified": _now(),
        }
