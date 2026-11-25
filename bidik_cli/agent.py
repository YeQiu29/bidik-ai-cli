"""Agentic Loop untuk Bidik CLI (Streaming + Reasoning + Multi-step Tool Calling)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from rich import box
from rich.panel import Panel
from rich.text import Text

from .client import BidikClient
from .config import BidikConfig
from .sessions import SessionManager
from .tools import ToolExecutor, get_tool_schemas
from .ui import console, render_markdown_panel


def build_system_prompt(workspace: Path, mode: str) -> str:
    mode_note = (
        "Saat ini Anda berada di PLAN MODE (Read-Only). Jangan mencoba mengubah file; fokus analisis, arsitektur, dan rencana solusi."
        if mode == "plan"
        else "Saat ini Anda memiliki akses penuh ke coding tools lokal di workspace pengguna."
    )
    return (
        "Anda adalah **Bidik CLI**, Agentic AI Coding & PC Assistant cerdas di laptop pengguna (Windows / PowerShell).\n"
        f"Direktori kerja saat ini (workspace): `{workspace}`\n"
        f"{mode_note}\n\n"
        "Kemampuan & Aturan Kerja:\n"
        "1. Gunakan Bahasa Indonesia yang jelas, ringkas, dan solutif.\n"
        "2. Anda BISA masuk dan menjelajahi sub-folder maupun folder lain di laptop (`list_files`, `read_file`, `search_code`), serta mengedit/membuat file (`edit_file`, `write_file`). Sistem keamanan otomatis akan meminta persetujuan YES/NO kepada pengguna jika Anda mengakses folder di luar workspace atau mengubah file.\n"
        "3. Anda BISA membantu mengecek kendala PC/laptop pengguna (misal laptop lemot, RAM penuh, CPU tinggi, disk penuh, cek jaringan/port/aplikasi) menggunakan `check_pc_health` atau `run_command`.\n"
        "4. Sebelum mengedit file yang belum pernah Anda baca, selalu panggil `read_file` terlebih dahulu agar indentasi akurat.\n"
        "5. Jangan pernah menjalankan perintah perusak fatal sistem operasi (seperti memformat harddisk)."
    )


class BidikAgent:
    """Mengelola percakapan multi-turn dan eksekusi tool otomatis."""

    def __init__(self, config: BidikConfig, client: BidikClient, workspace: Path) -> None:
        self.config = config
        self.client = client
        self.workspace = workspace.resolve()
        self.executor = ToolExecutor(workspace=self.workspace, mode=config.mode)
        self.session_manager = SessionManager()
        self.session_id: str = SessionManager.new_session_id()
        self.session_created_at: float = time.time()
        self.messages: list[dict[str, Any]] = []
        self.total_tokens_used: int = 0
        self.reset_conversation(new_session=False)

    def reset_conversation(self, new_session: bool = True) -> None:
        if new_session:
            self.session_id = SessionManager.new_session_id()
            self.session_created_at = time.time()
            self.total_tokens_used = 0
        self.messages = [
            {
                "role": "system",
                "content": build_system_prompt(self.workspace, self.config.mode),
            }
        ]

    def restore_session(self, data: dict[str, Any]) -> None:
        self.session_id = str(data.get("session_id") or SessionManager.new_session_id())
        self.session_created_at = float(data.get("created_at") or time.time())
        self.total_tokens_used = int(data.get("total_tokens") or 0)
        saved_msgs = [
            m for m in data.get("messages", []) if m.get("role") != "system"
        ]
        self.messages = [
            {
                "role": "system",
                "content": build_system_prompt(self.workspace, self.config.mode),
            }
        ] + saved_msgs

    def _auto_save(self) -> None:
        self.session_manager.save_session(
            session_id=self.session_id,
            workspace=self.workspace,
            model=self.config.model,
            messages=self.messages,
            total_tokens=self.total_tokens_used,
            created_at=self.session_created_at,
        )

    def sync_mode(self) -> None:
        self.executor.mode = self.config.mode
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = build_system_prompt(
                self.workspace, self.config.mode
            )

    def _expand_file_mentions(self, user_input: str) -> str:
        """Jika user mengetik @path/ke/file, lampirkan isi ringkas file ke konteks pesan."""
        mentions = re.findall(r"(?<!\S)@([^\s]+)", user_input)
        if not mentions:
            return user_input

        attached_blocks: list[str] = []
        for rel in mentions[:5]:
            candidate = (self.workspace / rel).resolve()
            try:
                candidate.relative_to(self.workspace)
            except ValueError:
                continue
            if candidate.exists() and candidate.is_file() and candidate.stat().st_size <= 200_000:
                content = candidate.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                preview = "\n".join(lines[:250])
                if len(lines) > 250:
                    preview += f"\n... (dipotong, total {len(lines)} baris)"
                attached_blocks.append(f"<attached_file path=\"{rel}\">\n{preview}\n</attached_file>")
                console.print(f"  [dim]📎 Melampirkan file konteks:[/dim] [cyan]{rel}[/cyan]")

        if not attached_blocks:
            return user_input
        return user_input + "\n\n" + "\n\n".join(attached_blocks)

    def compact_history(self) -> int:
        """Ringkas riwayat pesan lama agar hemat token."""
        if len(self.messages) <= 5:
            return 0
        removed = len(self.messages) - 5
        self.messages = [self.messages[0]] + self.messages[-4:]
        return removed

    def run_turn(self, user_input: str) -> None:
        self.sync_mode()
        enriched = self._expand_file_mentions(user_input)
        self.messages.append({"role": "user", "content": enriched})

        read_only = self.config.mode == "plan"
        tools_schema = get_tool_schemas(read_only=read_only)

        for step in range(1, self.config.max_steps + 1):
            try:
                result = self._stream_single_step(tools_schema)
            except KeyboardInterrupt:
                console.print("\n  [yellow]⏹ Dihentikan oleh pengguna (Ctrl+C).[/yellow]")
                return
            except Exception as exc:
                # Fallback jika model tertentu tidak mendukung parameter tools
                if tools_schema and ("tool" in str(exc).lower() or "400" in str(exc)):
                    try:
                        console.print(
                            "  [dim yellow]ℹ Model tidak mendukung tool-calling, beralih ke mode respons langsung...[/dim yellow]"
                        )
                        result = self._stream_single_step(None)
                    except Exception as inner_exc:
                        console.print(f"\n  [bold #ff6b6b]✖ Error API:[/bold #ff6b6b] {inner_exc}")
                        return
                else:
                    console.print(f"\n  [bold #ff6b6b]✖ Error koneksi ke 9router:[/bold #ff6b6b] {exc}")
                    return

            content = result["content"]
            tool_calls = result["tool_calls"]
            actual_model = result["actual_model"]
            usage = result["usage"]

            if usage.get("total_tokens"):
                self.total_tokens_used += usage["total_tokens"]

            label = (
                f"{self.config.model} → {actual_model}"
                if actual_model and actual_model != self.config.model
                else self.config.model
            )

            if not tool_calls:
                self.messages.append({"role": "assistant", "content": content})
                self._auto_save()
                if content:
                    render_markdown_panel(content, model_label=label, usage=usage)
                return

            # Simpan pesan asisten yang memanggil tool_calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content or "",
                "tool_calls": tool_calls,
            }
            self.messages.append(assistant_msg)

            if content:
                render_markdown_panel(content, model_label=label, usage=usage)

            # Eksekusi setiap tool yang diminta oleh AI
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                tool_output = self.executor.execute(fn_name, fn_args)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": tool_output,
                    }
                )
            self._auto_save()

        console.print(
            f"  [yellow]⚠ Mencapai batas maksimum iterasi ({self.config.max_steps} langkah). Ketik 'lanjutkan' jika masih perlu diteruskan.[/yellow]"
        )

    def _stream_single_step(
        self, tools_schema: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        reasoning_started = False
        done_payload: dict[str, Any] = {
            "content": "",
            "reasoning": "",
            "tool_calls": [],
            "actual_model": self.config.model,
            "usage": {},
        }

        status_spinner = console.status(
            f"[bold #00f5d4] Menghubungi {self.config.model}...[/bold #00f5d4]",
            spinner="dots",
        )
        status_spinner.start()
        spinner_active = True

        try:
            for event_type, data in self.client.stream_chat(
                messages=self.messages, tools=tools_schema
            ):
                if event_type == "reasoning":
                    if self.config.show_reasoning and data:
                        if spinner_active:
                            status_spinner.stop()
                            spinner_active = False
                        if not reasoning_started:
                            console.print("  [dim italic #9b5de5]💭 Berpikir:[/dim italic #9b5de5] ", end="")
                            reasoning_started = True
                        console.print(
                            Text(data, style="dim italic #8992b0"),
                            end="",
                        )
                elif event_type == "content":
                    if reasoning_started:
                        console.print()
                        reasoning_started = False
                    if not spinner_active:
                        status_spinner.update(
                            f"[bold #00bbf9] Menyusun jawaban ({self.config.model})...[/bold #00bbf9]"
                        )
                        status_spinner.start()
                        spinner_active = True
                    else:
                        status_spinner.update(
                            f"[bold #00bbf9] Menyusun jawaban ({self.config.model})...[/bold #00bbf9]"
                        )
                elif event_type == "tool_start":
                    if reasoning_started:
                        console.print()
                        reasoning_started = False
                    if not spinner_active:
                        status_spinner.start()
                        spinner_active = True
                    status_spinner.update(
                        f"[bold #fee440] Menyiapkan tool `{data}`...[/bold #fee440]"
                    )
                elif event_type == "done":
                    done_payload = data
        finally:
            if spinner_active:
                status_spinner.stop()
            if reasoning_started:
                console.print()

        return done_payload
