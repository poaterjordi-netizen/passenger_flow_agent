from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from metro_agent.assistant.schemas import RunRecord, SessionRecord


class TraceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sessions = root / "sessions"
        self.runs = root / "runs"
        self.sessions.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> SessionRecord:
        record = SessionRecord(
            session_id=f"session-{uuid.uuid4().hex}",
            created_at=_now(),
        )
        self.save_session(record)
        return record

    def get_session(self, session_id: str) -> SessionRecord:
        return SessionRecord.model_validate(self._read(self._safe_path(self.sessions, session_id)))

    def save_session(self, record: SessionRecord) -> None:
        self._write(
            self._safe_path(self.sessions, record.session_id), record.model_dump(mode="json")
        )

    def save_run(self, record: RunRecord) -> None:
        self._write(self._safe_path(self.runs, record.run_id), record.model_dump(mode="json"))

    def get_run(self, run_id: str) -> RunRecord:
        return RunRecord.model_validate(self._read(self._safe_path(self.runs, run_id)))

    def _safe_path(self, directory: Path, identifier: str) -> Path:
        if not identifier or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in identifier
        ):
            raise ValueError("invalid trace identifier")
        return directory / f"{identifier}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(path.stem)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid trace record")
        return value

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
