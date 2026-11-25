"""Local Coding Tools untuk Bidik CLI (aman, dibatasi ke workspace & konfirmasi user)."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .completer import IGNORED_DIRS
from .ui import ask_approval, console, render_diff

# Pola perintah berbahaya yang selalu diblokir demi keamanan laptop user
BLOCKED_COMMAND_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\bdel\s+/[sqf].*c:\\windows",
    r"\brm\s+-rf\s+/\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\breg\s+delete\s+hklm",
]


def get_tool_schemas(read_only: bool = False) -> list[dict[str, Any]]:
    """Kembalikan definisi OpenAI Function Calling tools."""
    schemas: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Lihat daftar file dan sub-folder di dalam direktori proyek lokal.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path relatif terhadap workspace (default '.').",
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Kedalaman maksimum pencarian folder (1-4, default 2).",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Baca isi file teks/kode lengkap dengan nomor baris.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path relatif atau absolut ke file.",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Baris awal (mulai dari 1, opsional).",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Baris akhir inklusif (opsional, default maks 300 baris).",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Cari teks atau regex di seluruh file kode dalam proyek.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Kata kunci atau pola regex yang dicari.",
                        },
                        "path": {
                            "type": "string",
                            "description": "Sub-direktori pencarian (default '.').",
                        },
                        "file_pattern": {
                            "type": "string",
                            "description": "Filter nama file glob, contoh '*.py' atau '*.ts' (default '*').",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    if read_only:
        return schemas

    schemas.extend(
        [
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Buat file baru atau timpa seluruh isi file dengan konten baru.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path relatif file di dalam workspace.",
                            },
                            "content": {
                                "type": "string",
                                "description": "Isi lengkap file yang akan ditulis.",
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Edit sebagian kode pada file dengan mengganti blok teks spesifik (old_text -> new_text).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path relatif file yang akan diedit.",
                            },
                            "old_text": {
                                "type": "string",
                                "description": "Teks asli persis termasuk indentasi yang akan diganti.",
                            },
                            "new_text": {
                                "type": "string",
                                "description": "Teks pengganti baru.",
                            },
                        },
                        "required": ["path", "old_text", "new_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Jalankan perintah terminal PowerShell di direktori proyek (misal test, linter, git status).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Perintah PowerShell yang ingin dijalankan.",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Batas waktu eksekusi dalam detik (default 60).",
                            },
                        },
                        "required": ["command"],
                    },
                },
            },
        ]
    )
    return schemas


class ToolExecutor:
    """Mengeksekusi tool calls secara aman di dalam workspace lokal."""

    def __init__(self, workspace: Path, mode: str = "agent") -> None:
        self.workspace = workspace.resolve()
        self.mode = mode
        self.session_allow_edits = False
        self.session_allow_commands = False
        self.modified_files: dict[str, tuple[str, str]] = {}  # path -> (original, latest)

    def _resolve_safe_path(self, raw_path: str, for_write: bool = False) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (self.workspace / candidate).resolve()
        else:
            candidate = candidate.resolve()

        if for_write:
            try:
                candidate.relative_to(self.workspace)
            except ValueError as exc:
                raise PermissionError(
                    f"Demi keamanan sistem laptop, penulisan di luar workspace '{self.workspace}' ditolak: {candidate}"
                ) from exc
        return candidate

    def execute(self, name: str, raw_args: str) -> str:
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError as exc:
            return f"Error: Argumen JSON tidak valid untuk tool {name}: {exc}"

        try:
            if name == "list_files":
                return self._list_files(
                    path=str(args.get("path", ".")),
                    max_depth=int(args.get("max_depth", 2) or 2),
                )
            if name == "read_file":
                return self._read_file(
                    path=str(args["path"]),
                    start_line=args.get("start_line"),
                    end_line=args.get("end_line"),
                )
            if name == "search_code":
                return self._search_code(
                    query=str(args["query"]),
                    path=str(args.get("path", ".")),
                    file_pattern=str(args.get("file_pattern", "*")),
                )

            if self.mode == "plan":
                return "Info: Saat ini dalam Plan Mode (Read-Only). Aksi penulisan/eksekusi dinonaktifkan."

            if name == "write_file":
                return self._write_file(
                    path=str(args["path"]),
                    content=str(args["content"]),
                )
            if name == "edit_file":
                return self._edit_file(
                    path=str(args["path"]),
                    old_text=str(args["old_text"]),
                    new_text=str(args["new_text"]),
                )
            if name == "run_command":
                return self._run_command(
                    command=str(args["command"]),
                    timeout=int(args.get("timeout", 60) or 60),
                )
            return f"Error: Tool '{name}' tidak dikenali."
        except Exception as exc:
            return f"Error saat menjalankan {name}: {exc}"

    def _list_files(self, path: str, max_depth: int) -> str:
        target = self._resolve_safe_path(path, for_write=False)
        if not target.exists():
            return f"Error: Direktori '{path}' tidak ditemukan."
        if target.is_file():
            return f"File: {target.name} ({target.stat().st_size} bytes)"

        max_depth = max(1, min(max_depth, 4))
        lines: list[str] = []
        count = 0
        for root, dirs, files in os.walk(target):
            rel = Path(root).relative_to(target)
            depth = len(rel.parts)
            if depth >= max_depth:
                dirs[:] = []
            else:
                dirs[:] = sorted(
                    d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")
                )

            indent = "  " * depth
            if depth > 0:
                lines.append(f"{indent}📁 {rel.name}/")

            for fname in sorted(files):
                if fname.startswith(".") and fname not in (".env.example", ".gitignore"):
                    continue
                lines.append(f"{indent}{'  ' if depth > 0 else ''}📄 {fname}")
                count += 1
                if count >= 250:
                    lines.append("... (dipotong, lebih dari 250 item)")
                    return "\n".join(lines)

        console.print(f"  [dim]📂 Membaca daftar folder:[/dim] [cyan]{path}[/cyan] [dim]({count} file)[/dim]")
        return "\n".join(lines) if lines else "(Direktori kosong)"

    def _read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        target = self._resolve_safe_path(path, for_write=False)
        if not target.exists():
            return f"Error: File '{path}' tidak ditemukan."
        if not target.is_file():
            return f"Error: '{path}' adalah direktori, gunakan list_files."

        text = target.read_text(encoding="utf-8", errors="replace")
        all_lines = text.splitlines()
        total = len(all_lines)

        s = max(1, int(start_line or 1))
        e = min(total, int(end_line or (s + 299)))
        selected = all_lines[s - 1 : e]

        console.print(
            f"  [dim]📖 Membaca file:[/dim] [cyan]{path}[/cyan] [dim](baris {s}-{e} dari {total})[/dim]"
        )
        numbered = [f"{i:4d} | {line}" for i, line in enumerate(selected, start=s)]
        header = f"File: {path} (Baris {s}-{e} dari total {total} baris)\n"
        return header + "\n".join(numbered)

    def _search_code(self, query: str, path: str, file_pattern: str) -> str:
        target = self._resolve_safe_path(path, for_write=False)
        if not target.exists():
            return f"Error: Path '{path}' tidak ditemukan."

        try:
            regex = re.compile(query, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(query), re.IGNORECASE)

        matches: list[str] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for fname in files:
                if not fnmatch.fnmatch(fname, file_pattern):
                    continue
                fpath = Path(root) / fname
                try:
                    if fpath.stat().st_size > 1_000_000:
                        continue
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                for lineno, line in enumerate(content.splitlines(), start=1):
                    if regex.search(line):
                        try:
                            rel = fpath.relative_to(self.workspace).as_posix()
                        except ValueError:
                            rel = str(fpath)
                        matches.append(f"{rel}:{lineno}: {line.strip()[:160]}")
                        if len(matches) >= 80:
                            break
                if len(matches) >= 80:
                    break
            if len(matches) >= 80:
                break

        console.print(
            f"  [dim]🔎 Mencari kode:[/dim] [cyan]'{query}'[/cyan] [dim]({len(matches)} hasil)[/dim]"
        )
        if not matches:
            return f"Tidak ditemukan kecocokan untuk '{query}'."
        return "\n".join(matches)

    def _confirm_edit(self, rel_path: str, old_text: str, new_text: str, is_new: bool) -> bool:
        render_diff(rel_path, old_text, new_text)
        if self.mode == "auto" or self.session_allow_edits:
            return True

        action_label = f"Buat file baru '{rel_path}'" if is_new else f"Edit file '{rel_path}'"
        decision = ask_approval(action_label, f"Lokasi: {self.workspace / rel_path}")
        if decision == "always":
            self.session_allow_edits = True
            return True
        return decision == "allow"

    def _record_modification(self, rel_path: str, original: str, updated: str) -> None:
        if rel_path in self.modified_files:
            orig, _ = self.modified_files[rel_path]
            self.modified_files[rel_path] = (orig, updated)
        else:
            self.modified_files[rel_path] = (original, updated)

    def _write_file(self, path: str, content: str) -> str:
        target = self._resolve_safe_path(path, for_write=True)
        rel_path = target.relative_to(self.workspace).as_posix()
        is_new = not target.exists()
        old_content = "" if is_new else target.read_text(encoding="utf-8", errors="replace")

        if not self._confirm_edit(rel_path, old_content, content, is_new=is_new):
            console.print(f"  [yellow]⚠ Penulisan file '{rel_path}' dibatalkan oleh pengguna.[/yellow]")
            return f"Ditolak oleh pengguna: File '{rel_path}' tidak diubah."

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._record_modification(rel_path, old_content, content)
        console.print(f"  [bold #00f5d4]✔ Tersimpan:[/bold #00f5d4] [white]{rel_path}[/white]")
        return f"Berhasil menulis file '{rel_path}' ({len(content.splitlines())} baris)."

    def _edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self._resolve_safe_path(path, for_write=True)
        if not target.exists():
            return f"Error: File '{path}' tidak ditemukan."

        rel_path = target.relative_to(self.workspace).as_posix()
        original = target.read_text(encoding="utf-8", errors="replace")

        if old_text not in original:
            return (
                f"Error: Blok `old_text` tidak ditemukan persis di '{rel_path}'. "
                "Gunakan read_file terlebih dahulu untuk memastikan indentasi dan isi baris akurat."
            )

        updated = original.replace(old_text, new_text, 1)
        if not self._confirm_edit(rel_path, original, updated, is_new=False):
            console.print(f"  [yellow]⚠ Edit file '{rel_path}' dibatalkan oleh pengguna.[/yellow]")
            return f"Ditolak oleh pengguna: File '{rel_path}' tidak diubah."

        target.write_text(updated, encoding="utf-8")
        self._record_modification(rel_path, original, updated)
        console.print(f"  [bold #00f5d4]✔ Berhasil diedit:[/bold #00f5d4] [white]{rel_path}[/white]")
        return f"Berhasil memperbarui '{rel_path}'."

    def _run_command(self, command: str, timeout: int) -> str:
        lowered = command.lower()
        for pat in BLOCKED_COMMAND_PATTERNS:
            if re.search(pat, lowered):
                return f"Diblokir: Perintah '{command}' terdeteksi berbahaya bagi sistem laptop."

        console.print(f"\n  [bold #fee440]💻 Permintaan Eksekusi Terminal:[/bold #fee440] [bold white]{command}[/bold white]")
        if not self.session_allow_commands:
            decision = ask_approval(
                "Jalankan perintah PowerShell di folder kerja?",
                f"Command: {command}  |  CWD: {self.workspace}",
            )
            if decision == "always":
                self.session_allow_commands = True
            elif decision != "allow":
                console.print("  [yellow]⚠ Eksekusi perintah ditolak oleh pengguna.[/yellow]")
                return "Ditolak oleh pengguna: Perintah tidak dijalankan."

        timeout = max(5, min(timeout, 180))
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            cwd=str(self.workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        combined = "\n".join(part for part in [stdout, stderr] if part)
        if len(combined) > 6000:
            combined = combined[:6000] + "\n... (output dipotong)"

        status_style = "#00f5d4" if proc.returncode == 0 else "#ff6b6b"
        console.print(
            f"  [{status_style}]↳ Exit Code {proc.returncode}[/{status_style}]"
        )
        return f"Exit code: {proc.returncode}\nOutput:\n{combined or '(tidak ada output)'}"
