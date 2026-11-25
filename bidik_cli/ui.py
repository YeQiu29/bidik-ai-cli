"""Komponen Terminal UI (Rich + Prompt Toolkit) untuk Bidik CLI."""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import __version__
from .client import ModelInfo, ServerStatus
from .config import BidikConfig
from .sessions import SessionMeta

# Pastikan output UTF-8 aman di Windows PowerShell / CMD
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

console = Console(highlight=False)

LOGO_LINES = [
    "██████╗ ██╗██████╗ ██╗██╗  ██╗     ██████╗██╗     ██╗",
    "██╔══██╗██║██╔══██╗██║██║ ██╔╝    ██╔════╝██║     ██║",
    "██████╔╝██║██║  ██║██║█████╔╝     ██║     ██║     ██║",
    "██╔══██╗██║██║  ██║██║██╔═██╗     ██║     ██║     ██║",
    "██████╔╝██║██████╔╝██║██║  ██╗    ╚██████╗███████╗██║",
    "╚═════╝ ╚═╝╚═════╝ ╚═╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚═╝",
]

LOGO_COLORS = [
    "#00f5d4",
    "#00e1e8",
    "#00bbf9",
    "#4ea8de",
    "#7b61ff",
    "#9b5de5",
]

MODE_BADGES: dict[str, tuple[str, str, str]] = {
    "agent": ("⚡ AGENT", "bold #00f5d4", "Bisa baca, edit file & jalankan terminal (dengan izin)"),
    "plan": ("🧭 PLAN", "bold #fee440", "Mode diskusi & analisis aman (Read-Only, tidak ubah file)"),
    "auto": ("🚀 AUTO", "bold #ff6b6b", "Otomatis terapkan edit kode di folder kerja"),
}

PROMPT_STYLE = Style.from_dict(
    {
        "prompt.brand": "bold #00f5d4",
        "prompt.mode": "bold #9b5de5",
        "prompt.model": "#00bbf9",
        "prompt.arrow": "bold #00f5d4",
        "completion-menu": "bg:#1a1b26 #c0caf5",
        "completion-menu.completion": "bg:#1a1b26 #c0caf5",
        "completion-menu.completion.current": "bg:#00bbf9 #0f111a bold",
        "completion-menu.meta.completion": "bg:#16161e #7aa2f7",
        "completion-menu.meta.completion.current": "bg:#0096c7 #0f111a",
        "scrollbar.background": "bg:#16161e",
        "scrollbar.button": "bg:#7b61ff",
        "bottom-toolbar": "bg:#16161e #9aa5ce",
    }
)


def render_banner(status: ServerStatus, config: BidikConfig, workspace: Path) -> None:
    """Tampilkan logo gradien BIDIK CLI dan kartu informasi status."""
    console.print()
    for line, color in zip(LOGO_LINES, LOGO_COLORS):
        console.print(f"  [{color}]{line}[/{color}]")

    subtitle = Text("  Agentic AI Coding Assistant ", style="bold white")
    subtitle.append(f"v{__version__}", style="dim cyan")
    subtitle.append(" • Powered By ", style="dim")
    subtitle.append("Dennis Hilmansyah", style="bold #9b5de5")
    console.print(subtitle)
    console.print()

    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold #7aa2f7", justify="right")
    info.add_column(style="white")

    if status.online:
        srv_text = (
            f"[bold #00f5d4]● Terhubung[/bold #00f5d4] "
            f"[dim]({config.api_base} • {status.latency_ms} ms • {status.model_count} model tersedia)[/dim]"
        )
    else:
        srv_text = (
            f"[bold #ff6b6b]● Offline / Gagal Konek[/bold #ff6b6b] "
            f"[dim]({config.api_base} — {status.error[:60]})[/dim]"
        )

    badge_label, badge_style, badge_desc = MODE_BADGES.get(
        config.mode, MODE_BADGES["agent"]
    )
    info.add_row("Server AI", srv_text)
    info.add_row("Model Aktif", f"[bold #00bbf9]{config.model}[/bold #00bbf9]  [dim](ketik /model untuk ganti)[/dim]")
    info.add_row("Mode Kerja", f"[{badge_style}]{badge_label}[/{badge_style}]  [dim]{badge_desc}[/dim]")
    info.add_row("Workspace", f"[bold white]{workspace}[/bold white]")

    console.print(
        Panel(
            info,
            border_style="#4ea8de",
            box=box.ROUNDED,
            padding=(0, 2),
            title="[bold #00f5d4]⚡ Status Sesi[/bold #00f5d4]",
            title_align="left",
            subtitle="[dim]Ketik [bold white]/[/bold white] untuk command • [bold white]@[/bold white] sebut file • [bold white]/help[/bold white] bantuan[/dim]",
            subtitle_align="right",
        )
    )
    console.print()


def render_help() -> None:
    table = Table(
        box=box.SIMPLE_HEAVY,
        border_style="#4ea8de",
        header_style="bold #00f5d4",
        show_edge=False,
    )
    table.add_column("Perintah", style="bold #00bbf9", no_wrap=True)
    table.add_column("Fungsi")
    table.add_row("/model", "Buka pemilih model interaktif (live dari 9router) dengan fitur cari/filter")
    table.add_row("/resume", "Pilih & lanjutkan sesi obrolan sebelumnya (otomatis tersimpan maks 20 sesi)")
    table.add_row("/new", "Mulai sesi obrolan baru tanpa menghapus sesi sebelumnya")
    table.add_row("/mode", "Ubah mode kerja: Agent (default), Plan (diskusi aman), atau Auto")
    table.add_row("/cd", "Pindah folder kerja aktif, contoh: `/cd C:\\Projects\\web-app`")
    table.add_row("/security", "Lihat batas akses folder AI & cabut izin sementara (/security reset)")
    table.add_row("/status", "Cek koneksi server 9router, ukuran cache sesi, dan pemakaian token")
    table.add_row("/diff", "Lihat ringkasan perubahan kode (git diff / file yang diedit di sesi ini)")
    table.add_row("/undo", "Batalkan perubahan kode AI pada sesi ini & kembalikan file ke versi asli")
    table.add_row("/clear", "Bersihkan layar percakapan saat ini")
    table.add_row("/compact", "Ringkas riwayat percakapan panjang agar hemat kuota konteks")
    table.add_row("/clean", "Hapus bersih semua file cache sesi obrolan di disk (0 KB)")
    table.add_row("/update", "Tarik & pasang update terbaru Bidik CLI langsung dari GitHub")
    table.add_row("/config", "Lihat atau ubah alamat API Base, API Key 9router, & GitHub Token")
    table.add_row("/exit", "Keluar dari Bidik CLI (bisa juga Ctrl+D)")
    table.add_row("@namafile", "Sertakan isi file proyek secara langsung, misal: 'perbaiki bug di @app.py'")

    console.print(
        Panel(
            table,
            title="[bold #00f5d4]📖 Panduan Bidik CLI[/bold #00f5d4]",
            border_style="#7b61ff",
            box=box.ROUNDED,
        )
    )


def render_diff(file_path: str, old_content: str, new_content: str) -> None:
    """Tampilkan unified diff berwarna hijau/merah."""
    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
            n=3,
        )
    )
    if not diff_lines:
        return

    styled = Text()
    max_preview = 80
    for idx, line in enumerate(diff_lines[:max_preview]):
        if line.startswith("+++") or line.startswith("---"):
            styled.append(line + "\n", style="bold white")
        elif line.startswith("@@"):
            styled.append(line + "\n", style="cyan")
        elif line.startswith("+"):
            styled.append(line + "\n", style="#00f5d4")
        elif line.startswith("-"):
            styled.append(line + "\n", style="#ff6b6b")
        else:
            styled.append(line + "\n", style="dim white")

    if len(diff_lines) > max_preview:
        styled.append(
            f"... (+{len(diff_lines) - max_preview} baris diff lainnya)\n",
            style="italic dim",
        )

    console.print(
        Panel(
            styled,
            title=f"[bold #00bbf9]📝 Diff Perubahan: {file_path}[/bold #00bbf9]",
            border_style="#4ea8de",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def render_markdown_panel(content: str, model_label: str, usage: dict[str, int] | None = None) -> None:
    subtitle = ""
    if usage and usage.get("total_tokens"):
        subtitle = (
            f"[dim]in:{usage.get('prompt_tokens', 0)} • "
            f"out:{usage.get('completion_tokens', 0)} • "
            f"total:{usage.get('total_tokens', 0)} tok[/dim]"
        )
    console.print(
        Panel(
            Markdown(content),
            title=f"[bold #00f5d4]🤖 {model_label}[/bold #00f5d4]",
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            border_style="#00bbf9",
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )


def select_model_interactive(
    models: list[ModelInfo], current_model: str
) -> str | None:
    """Interactive selector dengan fitur live search dan navigasi tombol panah."""
    if not models:
        return None

    search_buffer = Buffer()
    state = {"index": 0}

    # Posisikan kursor awal pada model yang sedang aktif
    for i, m in enumerate(models):
        if m.id == current_model:
            state["index"] = i
            break

    def get_filtered() -> list[ModelInfo]:
        q = search_buffer.text.strip().lower()
        if not q:
            return models
        return [
            m
            for m in models
            if q in m.id.lower() or q in m.owned_by.lower() or q in m.group_label.lower()
        ]

    def on_text_changed(_buf: Buffer) -> None:
        state["index"] = 0

    search_buffer.on_text_changed += on_text_changed

    def render_list() -> FormattedText:
        filtered = get_filtered()
        if not filtered:
            return FormattedText(
                [("fg:#ff6b6b italic", "  Tidak ada model yang cocok dengan pencarian.\n")]
            )

        state["index"] = max(0, min(state["index"], len(filtered) - 1))
        cur_idx = state["index"]

        visible_rows = 14
        half = visible_rows // 2
        start = max(0, min(cur_idx - half, max(0, len(filtered) - visible_rows)))
        end = min(len(filtered), start + visible_rows)

        fragments: list[tuple[str, str]] = []
        if start > 0:
            fragments.append(("fg:#6c757d", f"  ▲ ({start} model di atas)\n"))

        for pos in range(start, end):
            m = filtered[pos]
            is_sel = pos == cur_idx
            is_active = m.id == current_model

            pointer = " ❯ " if is_sel else "   "
            active_mark = "● " if is_active else "  "

            caps = []
            if m.supports_tools:
                caps.append("Tools")
            if m.supports_reasoning:
                caps.append("Think")
            if m.supports_vision:
                caps.append("Vision")
            caps_str = "/".join(caps) if caps else "Chat"

            row_style = "bg:#00bbf9 fg:#0f111a bold" if is_sel else "fg:#e0e6ed"
            meta_style = "bg:#00bbf9 fg:#1a1b26" if is_sel else "fg:#7aa2f7"
            group_style = "bg:#00bbf9 fg:#0f111a bold" if is_sel else "fg:#9b5de5"

            fragments.append((row_style, f"{pointer}{active_mark}{m.id:<38} "))
            fragments.append((group_style, f"{m.group_label:<16} "))
            fragments.append((meta_style, f"{m.context_label:<8} [{caps_str}]\n"))

        remaining = len(filtered) - end
        if remaining > 0:
            fragments.append(("fg:#6c757d", f"  ▼ ({remaining} model lainnya)\n"))

        return FormattedText(fragments)

    kb = KeyBindings()

    @kb.add("up")
    def _up(_event) -> None:
        filtered = get_filtered()
        if filtered:
            state["index"] = (state["index"] - 1) % len(filtered)

    @kb.add("down")
    def _down(_event) -> None:
        filtered = get_filtered()
        if filtered:
            state["index"] = (state["index"] + 1) % len(filtered)

    @kb.add("pageup")
    def _pgup(_event) -> None:
        state["index"] = max(0, state["index"] - 10)

    @kb.add("pagedown")
    def _pgdn(_event) -> None:
        filtered = get_filtered()
        if filtered:
            state["index"] = min(len(filtered) - 1, state["index"] + 10)

    @kb.add("enter")
    def _enter(event) -> None:
        filtered = get_filtered()
        if filtered:
            chosen = filtered[state["index"]].id
            event.app.exit(result=chosen)
        else:
            event.app.exit(result=None)

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    header = Window(
        FormattedTextControl(
            FormattedText(
                [
                    ("bold fg:#00f5d4", " ⚡ Pilih Model AI dari Server 9router "),
                    ("fg:#9aa5ce", f"({len(models)} model aktif • ↑↓ Pilih • Enter Konfirmasi • Esc Batal)\n"),
                ]
            )
        ),
        height=1,
    )
    search_bar = VSplit(
        [
            Window(
                FormattedTextControl(FormattedText([("bold fg:#00bbf9", " 🔍 Filter: ")])),
                width=12,
                height=1,
            ),
            Window(BufferControl(buffer=search_buffer), height=1),
        ]
    )
    divider = Window(char="─", height=1, style="fg:#3b4261")
    list_win = Window(FormattedTextControl(render_list), always_hide_cursor=True)

    app = Application(
        layout=Layout(HSplit([header, search_bar, divider, list_win]), focused_element=search_bar),
        key_bindings=kb,
        style=Style.from_dict({}),
        full_screen=False,
    )
    console.print()
    result = app.run()
    console.print()
    return result


def select_mode_interactive(current_mode: str) -> str | None:
    """Interactive selector untuk mengganti mode kerja Bidik CLI."""
    options = [
        ("agent", "⚡ Agent Mode (Direkomendasikan)", "Bisa baca, edit file & jalankan command dengan izin konfirmasi"),
        ("plan", "🧭 Plan / Diskusi Mode (Aman Read-Only)", "Hanya membaca & menganalisis kode tanpa mengubah file apa pun"),
        ("auto", "🚀 Auto-Edit Mode (Cepat)", "Otomatis menerapkan edit file di proyek, tetap tanya untuk terminal"),
    ]
    state = {"index": next((i for i, o in enumerate(options) if o[0] == current_mode), 0)}

    def render() -> FormattedText:
        frags: list[tuple[str, str]] = [
            ("bold fg:#00f5d4", " 🎛  Pilih Mode Kerja Bidik CLI "),
            ("fg:#9aa5ce", "(↑↓ Pilih • Enter Konfirmasi • Esc Batal)\n"),
        ]
        for i, (key, title, desc) in enumerate(options):
            sel = i == state["index"]
            active = "●" if key == current_mode else " "
            ptr = " ❯ " if sel else "   "
            st = "bg:#00bbf9 fg:#0f111a bold" if sel else "fg:#e0e6ed"
            ds = "bg:#00bbf9 fg:#1a1b26" if sel else "fg:#9aa5ce"
            frags.append((st, f"{ptr}{active} {title:<40} "))
            frags.append((ds, f"{desc}\n"))
        return FormattedText(frags)

    kb = KeyBindings()

    @kb.add("up")
    def _up(_e) -> None:
        state["index"] = (state["index"] - 1) % len(options)

    @kb.add("down")
    def _down(_e) -> None:
        state["index"] = (state["index"] + 1) % len(options)

    @kb.add("enter")
    def _enter(e) -> None:
        e.app.exit(result=options[state["index"]][0])

    @kb.add("escape")
    @kb.add("c-c")
    def _esc(e) -> None:
        e.app.exit(result=None)

    app = Application(
        layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
        key_bindings=kb,
        full_screen=False,
    )
    console.print()
    res = app.run()
    console.print()
    return res


def ask_approval(
    action_title: str,
    detail: str = "",
    explanation: str = "",
    allow_always: bool = True,
    warning_level: str = "normal",
) -> str:
    """Konfirmasi keamanan Yes/No interaktif dalam Bahasa Indonesia.

    Return: 'allow' | 'always' | 'deny'
    """
    if not sys.stdin.isatty():
        return "deny"

    border = "#ff6b6b" if warning_level == "high" else "#fee440"
    badge = "🚨 PERINGATAN KEAMANAN TINGGI" if warning_level == "high" else "🛡️ KONFIRMASI KEAMANAN AI"

    body_lines = [f"[bold white]Aksi AI :[/bold white] {action_title}"]
    if detail:
        body_lines.append(f"[bold #7aa2f7]Target  :[/bold #7aa2f7] [white]{detail}[/white]")
    if explanation:
        body_lines.append(f"[bold #fee440]Info    :[/bold #fee440] [dim white]{explanation}[/dim white]")

    console.print()
    console.print(
        Panel(
            "\n".join(body_lines),
            title=f"[bold {border}]{badge}[/bold {border}]",
            title_align="left",
            border_style=border,
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )

    choices: list[tuple[str, str]] = [
        ("allow", "✔ YES — Ya, Izinkan Sekali Ini Saja (Tekan Y / Enter)"),
    ]
    if allow_always:
        choices.append(("always", "⚡ YES (Sesi) — Ya, Izinkan Selama Sesi Ini Berjalan (Tekan A)"))
    choices.append(("deny", "✖ NO  — Tidak, Tolak Akses Ini (Tekan N / Esc)"))

    state = {"index": len(choices) - 1 if warning_level == "high" else 0}

    def render() -> FormattedText:
        frags: list[tuple[str, str]] = [
            ("fg:#9aa5ce", "  Pilih keputusan Anda (↑↓ pilih • Y = Ya • N = Tidak):\n"),
        ]
        for i, (key, label) in enumerate(choices):
            sel = i == state["index"]
            ptr = " ❯ " if sel else "   "
            if sel:
                bg = "bg:#ff6b6b" if key == "deny" else "bg:#00f5d4"
                style = f"{bg} fg:#0f111a bold"
            else:
                style = "fg:#e0e6ed"
            frags.append((style, f"{ptr}{label}\n"))
        return FormattedText(frags)

    kb = KeyBindings()

    @kb.add("up")
    def _up(_e) -> None:
        state["index"] = (state["index"] - 1) % len(choices)

    @kb.add("down")
    def _down(_e) -> None:
        state["index"] = (state["index"] + 1) % len(choices)

    @kb.add("enter")
    def _enter(e) -> None:
        e.app.exit(result=choices[state["index"]][0])

    @kb.add("y")
    def _yes(e) -> None:
        e.app.exit(result="allow")

    @kb.add("a")
    def _always(e) -> None:
        if allow_always:
            e.app.exit(result="always")

    @kb.add("n")
    @kb.add("escape")
    @kb.add("c-c")
    def _no(e) -> None:
        e.app.exit(result="deny")

    app = Application(
        layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
        key_bindings=kb,
        full_screen=False,
    )
    return app.run() or "deny"


def ask_workspace_trust(workspace: Path) -> bool:
    """Konfirmasi Yes/No saat pertama kali Bidik CLI dijalankan di sebuah folder baru."""
    if not sys.stdin.isatty():
        return True

    ws_resolved = workspace.resolve()
    home_dir = Path.home().resolve()
    ws_lower = str(ws_resolved).lower()

    is_broad_or_sys = (
        ws_resolved == home_dir
        or len(ws_resolved.parts) <= 2
        or "c:\\windows" in ws_lower
        or "program files" in ws_lower
    )

    extra_warn = ""
    if is_broad_or_sys:
        extra_warn = (
            "\n\n[bold #ff6b6b]⚠ PERHATIAN:[/bold #ff6b6b] Anda membuka Bidik CLI di folder induk/sistem yang cakupannya luas "
            f"(`[white]{ws_resolved}[/white]`). Sebaiknya jalankan `bidik` langsung di dalam sub-folder proyek kodingan spesifik Anda."
        )

    console.print()
    console.print(
        Panel(
            f"[bold white]Folder Kerja yang Diminta:[/bold white] [bold #00bbf9]{ws_resolved}[/bold #00bbf9]\n\n"
            "[bold #00f5d4]Aturan Batasan Keamanan AI:[/bold #00f5d4]\n"
            "• AI dibatasi hanya bekerja di dalam folder proyek ini.\n"
            "• Jika AI mencoba [bold]membaca atau mengakses folder lain[/bold] di luar folder ini, sistem akan menghentikan AI dan meminta izin [bold]Yes / No[/bold] Anda.\n"
            "• File rahasia (`.env`, `.ssh`, kunci privat) dan perintah terminal selalu dipantau dengan konfirmasi Anda."
            + extra_warn,
            title="[bold #00f5d4]🔐 Izin Akses Folder Kerja (Workspace Security)[/bold #00f5d4]",
            border_style="#ff6b6b" if is_broad_or_sys else "#00bbf9",
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )

    decision = ask_approval(
        action_title=f"Izinkan Bidik CLI bekerja di dalam folder '{ws_resolved.name or ws_resolved}'?",
        detail=str(ws_resolved),
        explanation="Pilih YES jika ini memang folder proyek kodingan Anda, atau NO untuk keluar.",
        allow_always=False,
        warning_level="high" if is_broad_or_sys else "normal",
    )
    return decision == "allow"


def select_session_interactive(
    sessions: list[SessionMeta], current_workspace: Path
) -> str | None:
    """Interactive selector untuk memilih sesi obrolan yang ingin di-resume."""
    if not sessions:
        return None

    ws_norm = str(current_workspace.resolve()).lower()
    search_buffer = Buffer()
    state = {"index": 0}

    def get_filtered() -> list[SessionMeta]:
        q = search_buffer.text.strip().lower()
        if not q:
            return sessions
        return [
            s
            for s in sessions
            if q in s.title.lower()
            or q in s.workspace.lower()
            or q in s.model.lower()
        ]

    search_buffer.on_text_changed += lambda _b: state.update({"index": 0})

    def render_list() -> FormattedText:
        filtered = get_filtered()
        if not filtered:
            return FormattedText(
                [("fg:#ff6b6b italic", "  Tidak ada sesi yang cocok dengan pencarian.\n")]
            )

        state["index"] = max(0, min(state["index"], len(filtered) - 1))
        cur_idx = state["index"]
        visible = 12
        start = max(0, min(cur_idx - visible // 2, max(0, len(filtered) - visible)))
        end = min(len(filtered), start + visible)

        frags: list[tuple[str, str]] = []
        for pos in range(start, end):
            s = filtered[pos]
            sel = pos == cur_idx
            same_ws = s.workspace.lower() == ws_norm
            ws_tag = "📌 Proyek Ini" if same_ws else f"📁 {Path(s.workspace).name}"
            ptr = " ❯ " if sel else "   "

            row_style = "bg:#00bbf9 fg:#0f111a bold" if sel else "fg:#e0e6ed"
            tag_style = "bg:#00bbf9 fg:#0f111a bold" if sel else ("fg:#00f5d4" if same_ws else "fg:#9b5de5")
            meta_style = "bg:#00bbf9 fg:#1a1b26" if sel else "fg:#7aa2f7"

            short_title = s.title[:44] + ("…" if len(s.title) > 44 else "")
            frags.append((row_style, f"{ptr}{short_title:<46} "))
            frags.append((tag_style, f"{ws_tag:<16} "))
            frags.append((meta_style, f"{s.time_label} • {s.message_count} msg • {s.model}\n"))

        return FormattedText(frags)

    kb = KeyBindings()

    @kb.add("up")
    def _up(_e) -> None:
        filtered = get_filtered()
        if filtered:
            state["index"] = (state["index"] - 1) % len(filtered)

    @kb.add("down")
    def _down(_e) -> None:
        filtered = get_filtered()
        if filtered:
            state["index"] = (state["index"] + 1) % len(filtered)

    @kb.add("enter")
    def _enter(e) -> None:
        filtered = get_filtered()
        if filtered:
            e.app.exit(result=filtered[state["index"]].session_id)
        else:
            e.app.exit(result=None)

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(e) -> None:
        e.app.exit(result=None)

    header = Window(
        FormattedTextControl(
            FormattedText(
                [
                    ("bold fg:#00f5d4", " 🕒 Resume Sesi Percakapan "),
                    ("fg:#9aa5ce", f"({len(sessions)} sesi tersimpan • ↑↓ Pilih • Enter Buka • Esc Batal)\n"),
                ]
            )
        ),
        height=1,
    )
    search_bar = VSplit(
        [
            Window(
                FormattedTextControl(FormattedText([("bold fg:#00bbf9", " 🔍 Cari  : ")])),
                width=12,
                height=1,
            ),
            Window(BufferControl(buffer=search_buffer), height=1),
        ]
    )
    divider = Window(char="─", height=1, style="fg:#3b4261")
    list_win = Window(FormattedTextControl(render_list), always_hide_cursor=True)

    app = Application(
        layout=Layout(HSplit([header, search_bar, divider, list_win]), focused_element=search_bar),
        key_bindings=kb,
        full_screen=False,
    )
    console.print()
    res = app.run()
    console.print()
    return res


def print_rule(title: str = "") -> None:
    console.print(Rule(title=title, style="#3b4261"))
