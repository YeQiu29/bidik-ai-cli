"""Entry point utama untuk Bidik CLI (`bidik`)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich import box
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .agent import BidikAgent
from .client import BidikClient
from .completer import BidikCompleter
from .config import BidikConfig, get_data_dir, get_history_file
from .updater import check_for_updates, perform_update
from .ui import (
    MODE_BADGES,
    PROMPT_STYLE,
    ask_approval,
    ask_workspace_trust,
    console,
    render_banner,
    render_diff,
    render_help,
    select_mode_interactive,
    select_model_interactive,
    select_session_interactive,
)

STANDALONE_SLASH = {
    "/model",
    "/resume",
    "/history",
    "/sessions",
    "/new",
    "/mode",
    "/security",
    "/status",
    "/diff",
    "/undo",
    "/clear",
    "/compact",
    "/clean",
    "/update",
    "/config",
    "/help",
    "/exit",
    "/quit",
}


def _is_unsafe_root_workspace(workspace: Path) -> bool:
    """Deteksi apakah user tidak sengaja menjalankan `bidik` di folder sistem / root / Home user."""
    ws = workspace.resolve()
    home = Path.home().resolve()
    ws_lower = str(ws).lower().rstrip("\\/")
    if ws == home or len(ws.parts) <= 1:
        return True
    unsafe_roots = {
        "c:\\windows",
        "c:\\program files",
        "c:\\program files (x86)",
        "c:\\programdata",
        "c:\\users",
    }
    return ws_lower in unsafe_roots or any(
        ws_lower.startswith(u + "\\") for u in ("c:\\windows", "c:\\program files", "c:\\program files (x86)")
    )


def _build_prompt_session(
    config: BidikConfig, completer: BidikCompleter, workspace: Path
) -> PromptSession:
    hist_file = get_history_file()
    kb = KeyBindings()

    @kb.add("enter")
    def _smart_enter(event) -> None:
        buf = event.current_buffer
        # Jika menu popup sedang terbuka dan ada item yang disorot, pilih item tersebut
        if buf.complete_state and buf.complete_state.current_completion:
            comp = buf.complete_state.current_completion
            buf.apply_completion(comp)
            # Jika yang dipilih adalah slash command mandiri (misal /model), langsung eksekusi!
            if buf.text.strip().lower() in STANDALONE_SLASH:
                buf.validate_and_handle()
            return
        buf.validate_and_handle()

    def bottom_toolbar() -> FormattedText:
        badge_label, _, _ = MODE_BADGES.get(config.mode, MODE_BADGES["agent"])
        return FormattedText(
            [
                ("bold", f" {badge_label} "),
                ("", f"│ 🤖 Model: {config.model} │ 📁 {workspace.name} │ "),
                ("italic", "Ketik / untuk menu • /model ganti AI • @ sebut file "),
            ]
        )

    return PromptSession(
        history=FileHistory(str(hist_file)),
        completer=completer,
        complete_while_typing=True,
        style=PROMPT_STYLE,
        key_bindings=kb,
        bottom_toolbar=bottom_toolbar,
    )


def _prompt_tokens(config: BidikConfig) -> FormattedText:
    mode_short = config.mode.upper()
    return FormattedText(
        [
            ("class:prompt.brand", "bidik"),
            ("", "("),
            ("class:prompt.mode", mode_short),
            ("", ":"),
            ("class:prompt.model", config.model),
            ("", ") "),
            ("class:prompt.arrow", "❯ "),
        ]
    )


def _handle_slash_command(
    raw_cmd: str,
    config: BidikConfig,
    client: BidikClient,
    agent: BidikAgent,
    completer: BidikCompleter,
) -> bool:
    """Proses slash command. Return False jika user meminta keluar (/exit)."""
    parts = raw_cmd.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        console.print("  [bold #00f5d4]👋 Sampai jumpa! Terima kasih telah menggunakan Bidik CLI.[/bold #00f5d4]")
        return False

    if cmd == "/help":
        render_help()
        return True

    if cmd == "/new":
        agent.reset_conversation(new_session=True)
        completer.invalidate_cache()
        console.print(
            "  [bold #00f5d4]🆕 Sesi percakapan baru dimulai![/bold #00f5d4] [dim](Sesi sebelumnya tetap tersimpan di /resume)[/dim]\n"
        )
        return True

    if cmd == "/clear":
        agent.reset_conversation(new_session=True)
        completer.invalidate_cache()
        console.clear()
        status = client.check_status(timeout=4.0)
        render_banner(status, config, agent.workspace)
        console.print("  [bold #00f5d4]✨ Layar & sesi percakapan telah direset.[/bold #00f5d4]\n")
        return True

    if cmd in ("/resume", "/history", "/sessions"):
        sessions = agent.session_manager.list_sessions(agent.workspace)
        if not sessions:
            console.print("  [dim]Belum ada riwayat sesi obrolan yang tersimpan.[/dim]")
            return True

        chosen_id = arg if arg else select_session_interactive(sessions, agent.workspace)
        if not chosen_id:
            return True

        loaded = agent.session_manager.load_session(chosen_id)
        if not loaded:
            console.print(f"  [bold #ff6b6b]✖ Sesi `{chosen_id}` tidak ditemukan.[/bold #ff6b6b]")
            return True

        agent.restore_session(loaded)
        _render_resumed_summary(loaded)
        return True

    if cmd == "/clean":
        cnt, total_bytes = agent.session_manager.cache_stats()
        if cnt == 0:
            console.print("  [dim]Cache sesi sudah bersih (0 file).[/dim]")
            return True
        decision = ask_approval(
            f"Hapus semua {cnt} sesi cache ({total_bytes / 1024:.1f} KB)?",
            f"Folder: {agent.session_manager.sessions_dir}",
        )
        if decision in ("allow", "always"):
            deleted, freed = agent.session_manager.clean_all()
            console.print(
                f"  [bold #00f5d4]🧹 Berhasil menghapus {deleted} sesi ({freed / 1024:.1f} KB dibebaskan).[/bold #00f5d4]"
            )
        else:
            console.print("  [dim]Pembersihan cache dibatalkan.[/dim]")
        return True

    if cmd == "/compact":
        removed = agent.compact_history()
        if removed:
            console.print(
                f"  [bold #00f5d4]🗜 Berhasil meringkas konteks ({removed} pesan lama dibersihkan).[/bold #00f5d4]"
            )
        else:
            console.print("  [dim]Konteks percakapan saat ini masih ringkas.[/dim]")
        return True

    if cmd == "/model":
        if arg:
            config.model = arg
            config.save()
            console.print(
                f"  [bold #00f5d4]✔ Model aktif diganti ke:[/bold #00f5d4] [bold #00bbf9]{config.model}[/bold #00bbf9]"
            )
            return True

        with console.status(
            "[bold #00bbf9]Mengambil daftar model live dari server 9router...[/bold #00bbf9]",
            spinner="dots",
        ):
            try:
                models = client.fetch_models(force_refresh=True)
            except Exception as exc:
                console.print(f"  [bold #ff6b6b]✖ Gagal mengambil daftar model:[/bold #ff6b6b] {exc}")
                return True

        chosen = select_model_interactive(models, config.model)
        if chosen:
            config.model = chosen
            config.save()
            console.print(
                f"  [bold #00f5d4]✔ Model aktif sekarang:[/bold #00f5d4] [bold #00bbf9]{config.model}[/bold #00bbf9]"
            )
        else:
            console.print(f"  [dim]Tetap menggunakan model: {config.model}[/dim]")
        return True

    if cmd == "/cd":
        if not arg:
            console.print(f"  [bold #7aa2f7]Folder aktif saat ini:[/bold #7aa2f7] {agent.workspace}")
            console.print("  [dim]Gunakan `/cd <path_folder>` untuk berpindah folder kerja.[/dim]")
            return True
        new_ws = Path(arg).expanduser()
        if not new_ws.is_absolute():
            new_ws = (agent.workspace / new_ws).resolve()
        else:
            new_ws = new_ws.resolve()
        if not new_ws.exists() or not new_ws.is_dir():
            console.print(f"  [bold #ff6b6b]✖ Folder tidak ditemukan:[/bold #ff6b6b] {new_ws}")
            return True
        agent.workspace = new_ws
        agent.executor.workspace = new_ws
        completer.workspace = new_ws
        completer.invalidate_cache()
        agent.sync_mode()
        console.print(f"  [bold #00f5d4]📂 Folder kerja berpindah ke:[/bold #00f5d4] [bold white]{new_ws}[/bold white]")
        return True

    if cmd == "/mode":
        if arg in ("agent", "plan", "auto"):
            chosen_mode = arg
        else:
            chosen_mode = select_mode_interactive(config.mode)
        if chosen_mode:
            config.mode = chosen_mode
            config.save()
            agent.sync_mode()
            badge, style, desc = MODE_BADGES[config.mode]
            console.print(f"  [bold #00f5d4]✔ Mode diubah ke:[/bold #00f5d4] [{style}]{badge}[/{style}] — [dim]{desc}[/dim]")
        return True

    if cmd == "/security":
        if arg.lower() == "reset":
            agent.executor.reset_permissions()
            console.print(
                "  [bold #00f5d4]🔐 Seluruh izin akses sementara sesi ini berhasil direset kembali ke ketat![/bold #00f5d4]"
            )
            return True

        ext_list = (
            ", ".join(str(p) for p in sorted(agent.executor.allowed_external_dirs))
            if agent.executor.allowed_external_dirs
            else "Tidak ada (ketat terkunci di folder proyek)"
        )
        sec_tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        sec_tbl.add_column(style="bold #7aa2f7")
        sec_tbl.add_column(style="white")
        sec_tbl.add_row("Batas Folder Proyek", f"[bold #00f5d4]{agent.workspace}[/bold #00f5d4]")
        sec_tbl.add_row("Proteksi Luar Folder", "Aktif — Wajib konfirmasi Yes/No Bahasa Indonesia")
        sec_tbl.add_row("Proteksi File Rahasia", "Aktif — `.env`, `.ssh`, `.key`, `.pem`, `AppData` dipantau")
        sec_tbl.add_row("Folder Sistem OS", "Diblokir Keras (`C:\\Windows`, `Program Files`)")
        sec_tbl.add_row("Folder Luar Diizinkan", ext_list)
        sec_tbl.add_row(
            "Izin Edit / Terminal Sesi",
            f"Auto-Edit: {'Ya' if agent.executor.session_allow_edits else 'Tanya Yes/No'} • "
            f"Auto-Cmd: {'Ya' if agent.executor.session_allow_commands else 'Tanya Yes/No'}",
        )
        console.print(
            Panel(
                sec_tbl,
                title="[bold #00f5d4]🛡️ Status Batasan Keamanan AI (/security)[/bold #00f5d4]",
                subtitle="[dim]Ketik `/security reset` untuk mencabut semua izin sesi sementara[/dim]",
                border_style="#00bbf9",
                box=box.ROUNDED,
            )
        )
        return True

    if cmd == "/status":
        status = client.check_status(timeout=5.0)
        tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        tbl.add_column(style="bold #7aa2f7")
        tbl.add_column(style="white")
        tbl.add_row("Endpoint 9router", config.api_base)
        tbl.add_row(
            "Status Server",
            f"[bold #00f5d4]Online ({status.latency_ms} ms)[/bold #00f5d4]"
            if status.online
            else f"[bold #ff6b6b]Offline ({status.error})[/bold #ff6b6b]",
        )
        tbl.add_row("Total Model Server", str(status.model_count))
        tbl.add_row("Model Aktif", f"[bold #00bbf9]{config.model}[/bold #00bbf9]")
        tbl.add_row("Mode Aktif", config.mode.upper())
        sess_cnt, sess_bytes = agent.session_manager.cache_stats()
        tbl.add_row("Pesan di Memori", f"{len(agent.messages)} pesan (ID: {agent.session_id})")
        tbl.add_row("Cache Sesi Disk", f"{sess_cnt}/20 sesi ({sess_bytes / 1024:.1f} KB — auto-cleanup aktif)")
        tbl.add_row("Total Token Sesi", f"{agent.total_tokens_used:,} token")
        console.print(
            Panel(
                tbl,
                title="[bold #00f5d4]📡 Status Koneksi & Sesi[/bold #00f5d4]",
                border_style="#4ea8de",
                box=box.ROUNDED,
            )
        )
        return True

    if cmd == "/undo":
        if not agent.executor.modified_files:
            console.print("  [dim]Tidak ada perubahan file oleh AI pada sesi ini yang perlu di-undo.[/dim]")
            return True
        files_str = ", ".join(agent.executor.modified_files.keys())
        decision = ask_approval(
            action_title="Kembalikan (Undo) perubahan kode ke versi semula?",
            detail=files_str,
            explanation="Seluruh file yang telah diedit AI pada sesi ini akan dikembalikan ke isi aslinya.",
            allow_always=False,
        )
        if decision == "allow":
            restored = agent.executor.undo_last_changes()
            console.print(
                f"  [bold #00f5d4]⏪ Berhasil mengembalikan {len(restored)} file ke kondisi semula:[/bold #00f5d4] {', '.join(restored)}"
            )
        return True

    if cmd == "/diff":
        if agent.executor.modified_files:
            for rel_path, (orig, updated) in agent.executor.modified_files.items():
                render_diff(rel_path, orig, updated)
            return True

        # Coba cek git diff jika belum ada edit sesi tapi ini repo git
        try:
            proc = subprocess.run(
                ["git", "status", "-s"],
                cwd=str(agent.workspace),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                console.print(
                    Panel(
                        proc.stdout.strip(),
                        title="[bold #00bbf9]🔀 Git Status Workspace[/bold #00bbf9]",
                        border_style="#4ea8de",
                    )
                )
                return True
        except Exception:
            pass

        console.print("  [dim]Belum ada perubahan file pada sesi ini.[/dim]")
        return True

    if cmd == "/update":
        with console.status(
            "[bold #00bbf9]Memeriksa & mengunduh pembaruan terbaru dari GitHub...[/bold #00bbf9]",
            spinner="dots",
        ):
            ok, message = perform_update(config)
        if ok:
            console.print(
                Panel(
                    f"[bold #00f5d4]✔ {message}[/bold #00f5d4]",
                    title="[bold #00f5d4]🚀 Update Berhasil[/bold #00f5d4]",
                    border_style="#00f5d4",
                    box=box.ROUNDED,
                )
            )
        else:
            console.print(f"  [bold #ff6b6b]✖ Update gagal:[/bold #ff6b6b] {message}")
        return True

    if cmd == "/config":
        if not arg:
            gh_state = "Tersimpan (Private Repo siap)" if config.github_token else "Kosong (Mode Public Repo)"
            masked_key = (
                f"{config.api_key[:10]}...{config.api_key[-4:]}"
                if len(config.api_key) > 14
                else ("(belum diisi)" if not config.api_key else "***")
            )
            console.print(
                Panel(
                    f"[bold #7aa2f7]File Config  :[/bold #7aa2f7] {get_data_dir() / 'config.json'}\n"
                    f"[bold #7aa2f7]API Base     :[/bold #7aa2f7] {config.api_base}\n"
                    f"[bold #7aa2f7]API Key      :[/bold #7aa2f7] {masked_key}\n"
                    f"[bold #7aa2f7]Model Aktif  :[/bold #7aa2f7] {config.model}\n"
                    f"[bold #7aa2f7]GitHub Token :[/bold #7aa2f7] {gh_state}\n\n"
                    "[dim]Ubah cepat:\n"
                    "• `/config url http://192.168.6.217:20128/v1`\n"
                    "• `/config key <API_KEY_9ROUTER>`\n"
                    "• `/config github_token <TOKEN>` (opsional jika repo GitHub diubah ke Private)[/dim]",
                    title="[bold #00f5d4]⚙ Konfigurasi Bidik CLI[/bold #00f5d4]",
                    border_style="#7b61ff",
                    box=box.ROUNDED,
                )
            )
            return True

        sub = arg.split(maxsplit=1)
        if len(sub) == 2 and sub[0].lower() == "url":
            config.api_base = sub[1].strip()
            config.save()
            console.print(f"  [bold #00f5d4]✔ API Base diperbarui ke:[/bold #00f5d4] {config.api_base}")
        elif len(sub) == 2 and sub[0].lower() == "key":
            config.api_key = sub[1].strip()
            config.save()
            console.print("  [bold #00f5d4]✔ API Key berhasil diperbarui.[/bold #00f5d4]")
        elif len(sub) == 2 and sub[0].lower() == "github_token":
            tok = sub[1].strip()
            config.github_token = "" if tok.lower() in ("clear", "none", "hapus") else tok
            config.save()
            console.print("  [bold #00f5d4]✔ GitHub Token berhasil diperbarui.[/bold #00f5d4]")
        else:
            console.print(
                "  [yellow]Format: `/config url <URL>`, `/config key <API_KEY>`, atau `/config github_token <TOKEN>`[/yellow]"
            )
        return True

    console.print(
        f"  [yellow]Perintah `{cmd}` tidak dikenal. Ketik `/help` untuk daftar perintah.[/yellow]"
    )
    return True


def _render_resumed_summary(loaded: dict) -> None:
    title = loaded.get("title", "Sesi Percakapan")
    msg_cnt = loaded.get("message_count", 0)
    msgs = loaded.get("messages", [])
    last_user = next(
        (m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"),
        "",
    )
    last_preview = str(last_user).splitlines()[0][:90] if last_user else "-"
    console.print(
        Panel(
            f"[bold white]{title}[/bold white]\n"
            f"[dim]Jumlah pesan dipulihkan: {msg_cnt} pesan • Pesan terakhir: \"{last_preview}\"[/dim]",
            title="[bold #00f5d4]🔄 Sesi Berhasil Dilanjutkan[/bold #00f5d4]",
            border_style="#00bbf9",
            box=box.ROUNDED,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bidik",
        description="Bidik CLI - Agentic AI Coding Assistant (Powered By Dennis Hilmansyah)",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt langsung (opsional, kosongkan untuk masuk mode interaktif)",
    )
    parser.add_argument("-m", "--model", help="Override model AI untuk sesi ini")
    parser.add_argument(
        "--mode",
        choices=["agent", "plan", "auto"],
        help="Mode kerja awal (agent / plan / auto)",
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_last",
        action="store_true",
        help="Langsung lanjutkan sesi percakapan terakhir di proyek ini",
    )
    parser.add_argument(
        "-r",
        "--resume",
        action="store_true",
        help="Buka menu pemilih sesi obrolan sebelumnya saat masuk",
    )
    parser.add_argument(
        "-u",
        "--update",
        action="store_true",
        help="Perbarui Bidik CLI langsung dari GitHub lalu keluar",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"Bidik CLI v{__version__}"
    )
    args = parser.parse_args()

    config = BidikConfig.load()
    if args.update:
        with console.status(
            "[bold #00bbf9]Memeriksa & mengunduh pembaruan terbaru dari GitHub...[/bold #00bbf9]",
            spinner="dots",
        ):
            ok, msg = perform_update(config)
        style = "bold #00f5d4" if ok else "bold #ff6b6b"
        icon = "✔" if ok else "✖"
        console.print(f"  [{style}]{icon} {msg}[/{style}]")
        return
    if args.model:
        config.model = args.model
    if args.mode:
        config.mode = args.mode

    # Onboarding otomatis saat pertama kali dijalankan jika API Key belum diset
    if not config.api_key and sys.stdin.isatty():
        console.print(
            Panel(
                "[bold white]Selamat datang di Bidik CLI![/bold white]\n"
                "Masukkan alamat Server 9router & API Key Anda (cukup satu kali, akan disimpan di `~/.bidik/config.json`).",
                title="[bold #00f5d4]🔑 Setup Awal Bidik CLI[/bold #00f5d4]",
                border_style="#00bbf9",
                box=box.ROUNDED,
            )
        )
        entered_url = console.input(
            f"  [bold #7aa2f7]Server API Base[/bold #7aa2f7] [dim](Enter = {config.api_base})[/dim]: "
        ).strip()
        if entered_url:
            config.api_base = entered_url
        entered_key = console.input(
            "  [bold #7aa2f7]API Key 9router[/bold #7aa2f7] [dim](contoh: sk-...)[/dim]: "
        ).strip()
        if entered_key:
            config.api_key = entered_key
        console.print()

    config.save()

    workspace = Path.cwd().resolve()
    ws_norm = str(workspace).lower()
    if ws_norm not in [w.lower() for w in config.trusted_workspaces]:
        if not ask_workspace_trust(workspace):
            console.print("  [yellow]🚪 Akses folder tidak diizinkan. Keluar dari Bidik CLI.[/yellow]")
            return
        config.trusted_workspaces.append(str(workspace))
        config.save()

    client = BidikClient(config)
    agent = BidikAgent(config=config, client=client, workspace=workspace)

    # Mode one-shot jika dipanggil dengan argumen teks langsung: `bidik "cek bug di app.py"`
    if args.prompt:
        one_shot_prompt = " ".join(args.prompt).strip()
        agent.run_turn(one_shot_prompt)
        return

    status = client.check_status(timeout=4.0)
    render_banner(status=status, config=config, workspace=workspace)

    upd = check_for_updates(config=config, timeout=2.0)
    if upd.has_update:
        short_sha = upd.latest_sha[:7] if upd.latest_sha else "baru"
        note = f" — {upd.latest_message}" if upd.latest_message else ""
        console.print(
            Panel(
                f"[bold #fee440]🔔 Pembaruan Bidik CLI tersedia di GitHub![/bold #fee440] "
                f"[dim](`{short_sha}`{note})[/dim]\n"
                "Ketik [bold #00f5d4]/update[/bold #00f5d4] untuk memperbarui otomatis dalam hitungan detik tanpa menghapus konfigurasi Anda.",
                border_style="#fee440",
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )
        console.print()

    if args.continue_last:
        sessions = agent.session_manager.list_sessions(workspace)
        ws_sessions = [
            s for s in sessions if s.workspace.lower() == str(workspace.resolve()).lower()
        ] or sessions
        if ws_sessions:
            loaded = agent.session_manager.load_session(ws_sessions[0].session_id)
            if loaded:
                agent.restore_session(loaded)
                _render_resumed_summary(loaded)
        else:
            console.print("  [dim]Belum ada sesi tersimpan untuk dilanjutkan, memulai sesi baru.[/dim]\n")
    elif args.resume:
        sessions = agent.session_manager.list_sessions(workspace)
        if sessions:
            chosen_id = select_session_interactive(sessions, workspace)
            if chosen_id:
                loaded = agent.session_manager.load_session(chosen_id)
                if loaded:
                    agent.restore_session(loaded)
                    _render_resumed_summary(loaded)
        else:
            console.print("  [dim]Belum ada sesi tersimpan untuk dipilih.[/dim]\n")

    completer = BidikCompleter(workspace=workspace)
    session = _build_prompt_session(config=config, completer=completer, workspace=workspace)

    while True:
        try:
            user_text = session.prompt(_prompt_tokens(config)).strip()
        except KeyboardInterrupt:
            console.print("  [dim](Tekan Ctrl+D atau ketik /exit untuk keluar)[/dim]")
            continue
        except EOFError:
            console.print("\n  [bold #00f5d4]👋 Sampai jumpa![/bold #00f5d4]")
            break

        if not user_text:
            continue

        if user_text.startswith("/"):
            keep_going = _handle_slash_command(
                user_text, config, client, agent, completer
            )
            if not keep_going:
                break
            continue

        agent.run_turn(user_text)
        completer.invalidate_cache()
        console.print()


if __name__ == "__main__":
    main()
