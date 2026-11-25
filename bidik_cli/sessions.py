"""Manajemen Session Cache pintar dengan Auto-Cleanup untuk Bidik CLI."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR, get_data_dir

MAX_SAVED_SESSIONS = 20


@dataclass
class SessionMeta:
    session_id: str
    title: str
    workspace: str
    model: str
    updated_at: float
    created_at: float
    message_count: int
    total_tokens: int

    @property
    def time_label(self) -> str:
        dt = datetime.fromtimestamp(self.updated_at)
        return dt.strftime("%d/%m %H:%M")


class SessionManager:
    """Menyimpan, memuat, dan memangkas otomatis (auto-cleanup maks 20 sesi) obrolan."""

    def __init__(self, max_sessions: int = MAX_SAVED_SESSIONS) -> None:
        self.max_sessions = max_sessions

    @property
    def store_file(self) -> Path:
        d = get_data_dir()
        fname = "sessions.json" if d == CONFIG_DIR else ".bidik_sessions.json"
        return d / fname

    @property
    def sessions_dir(self) -> Path:
        return self.store_file

    @staticmethod
    def new_session_id() -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short = uuid.uuid4().hex[:6]
        return f"{stamp}_{short}"

    def _read_store(self) -> list[dict[str, Any]]:
        sf = self.store_file
        if not sf.exists():
            return []
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write_store(self, items: list[dict[str, Any]]) -> None:
        # Urutkan terbaru lebih dulu & pangkas otomatis ke max_sessions
        items.sort(key=lambda x: float(x.get("updated_at", 0)), reverse=True)
        trimmed = items[: self.max_sessions]
        try:
            self.store_file.write_text(
                json.dumps(trimmed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def save_session(
        self,
        session_id: str,
        workspace: Path,
        model: str,
        messages: list[dict[str, Any]],
        total_tokens: int = 0,
        created_at: float | None = None,
    ) -> None:
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return

        first_text = str(user_msgs[0].get("content", "")).splitlines()[0].strip()
        title = (first_text[:62] + "...") if len(first_text) > 65 else first_text
        if not title:
            title = "Sesi Tanpa Judul"

        now = time.time()
        non_system_msgs = [m for m in messages if m.get("role") != "system"]
        entry = {
            "session_id": session_id,
            "title": title,
            "workspace": str(workspace.resolve()),
            "model": model,
            "created_at": created_at or now,
            "updated_at": now,
            "message_count": len(non_system_msgs),
            "total_tokens": total_tokens,
            "messages": non_system_msgs,
        }

        items = [x for x in self._read_store() if x.get("session_id") != session_id]
        items.insert(0, entry)
        self._write_store(items)

    def list_sessions(self, current_workspace: Path | None = None) -> list[SessionMeta]:
        raw_items = self._read_store()
        metas: list[SessionMeta] = []
        for raw in raw_items:
            try:
                metas.append(
                    SessionMeta(
                        session_id=str(raw.get("session_id", "")),
                        title=str(raw.get("title", "Sesi Percakapan")),
                        workspace=str(raw.get("workspace", "")),
                        model=str(raw.get("model", "")),
                        updated_at=float(raw.get("updated_at", 0)),
                        created_at=float(raw.get("created_at", 0)),
                        message_count=int(raw.get("message_count", 0)),
                        total_tokens=int(raw.get("total_tokens", 0)),
                    )
                )
            except (TypeError, ValueError):
                continue

        ws_norm = str(current_workspace.resolve()).lower() if current_workspace else ""
        metas.sort(
            key=lambda s: (
                0 if ws_norm and s.workspace.lower() == ws_norm else 1,
                -s.updated_at,
            )
        )
        return metas

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        for item in self._read_store():
            if item.get("session_id") == session_id:
                return item
        return None

    def clean_all(self) -> tuple[int, int]:
        sf = self.store_file
        items = self._read_store()
        count = len(items)
        freed = 0
        if sf.exists():
            try:
                freed = sf.stat().st_size
                sf.unlink()
            except OSError:
                pass
        return (count, freed)

    def cache_stats(self) -> tuple[int, int]:
        sf = self.store_file
        items = self._read_store()
        size = 0
        if sf.exists():
            try:
                size = sf.stat().st_size
            except OSError:
                pass
        return (len(items), size)
