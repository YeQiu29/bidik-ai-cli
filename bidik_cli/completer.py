"""Autocomplete interaktif untuk slash command (/) dan mention file (@)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/model", "Pilih & ganti model AI live dari server 9router"),
    ("/resume", "Buka & lanjutkan sesi obrolan sebelumnya (Session Cache)"),
    ("/new", "Mulai sesi percakapan baru (sesi sebelumnya tetap tersimpan)"),
    ("/mode", "Ganti mode kerja: Agent / Plan (Diskusi) / Auto"),
    ("/status", "Cek koneksi server 9router, cache sesi & statistik token"),
    ("/diff", "Lihat perubahan kode pada git / sesi saat ini"),
    ("/clear", "Bersihkan layar & reset percakapan saat ini"),
    ("/compact", "Ringkas konteks percakapan panjang agar hemat token"),
    ("/clean", "Hapus bersih seluruh cache riwayat sesi obrolan"),
    ("/config", "Tampilkan atau ubah URL server 9router & API key"),
    ("/help", "Tampilkan panduan lengkap penggunaan Bidik CLI"),
    ("/exit", "Keluar dari Bidik CLI"),
]

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "AppData",
}


class BidikCompleter(Completer):
    """Popup otomatis saat mengetik `/` di awal baris atau `@` untuk nama file."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._file_cache: list[str] = []
        self._cache_valid = False

    def invalidate_cache(self) -> None:
        self._cache_valid = False

    def _scan_workspace_files(self, limit: int = 400) -> list[str]:
        if self._cache_valid:
            return self._file_cache
        files: list[str] = []
        try:
            for root, dirs, filenames in os.walk(self.workspace):
                rel_root = Path(root).relative_to(self.workspace)
                if len(rel_root.parts) > 3:
                    dirs[:] = []
                    continue
                dirs[:] = [
                    d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")
                ]
                for fname in filenames:
                    if fname.startswith("."):
                        continue
                    rel_path = (rel_root / fname).as_posix()
                    if rel_path.startswith("./"):
                        rel_path = rel_path[2:]
                    files.append(rel_path)
                    if len(files) >= limit:
                        break
                if len(files) >= limit:
                    break
        except OSError:
            pass
        files.sort()
        self._file_cache = files
        self._cache_valid = True
        return files

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterable[Completion]:
        text = document.text_before_cursor

        # 1) Slash command ketika input diawali '/' dan belum ada spasi
        stripped = text.lstrip()
        if stripped.startswith("/") and " " not in stripped:
            query = stripped.lower()
            for cmd, desc in SLASH_COMMANDS:
                if cmd.startswith(query):
                    yield Completion(
                        text=cmd,
                        start_position=-len(stripped),
                        display=cmd,
                        display_meta=desc,
                    )
            return

        # 2) @file mention di bagian mana pun dalam prompt
        last_space = max(text.rfind(" "), text.rfind("\n"), text.rfind("\t"))
        token = text[last_space + 1 :]
        if token.startswith("@"):
            file_query = token[1:].lower()
            for rel_path in self._scan_workspace_files():
                if file_query in rel_path.lower():
                    yield Completion(
                        text=f"@{rel_path}",
                        start_position=-len(token),
                        display=f"📄 {rel_path}",
                        display_meta="File project",
                    )
