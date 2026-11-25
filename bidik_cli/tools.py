"""Local Coding Tools untuk Bidik CLI dengan sistem Security Boundary & konfirmasi Yes/No Bahasa Indonesia."""

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

# Hanya perintah perusak fatal OS (format disk / hapus C:\Windows) yang diblokir mati.
# Aksi lainnya tetap BISA dijalankan selama diizinkan pengguna lewat konfirmasi YES / NO!
BLOCKED_COMMAND_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\bdel\s+/[sqf].*c:\\windows",
    r"\brm\s+-rf\s+[/\\]\s*$",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\bcipher\s+/w",
]

# Perintah sensitif (hapus file / ubah setting PC / restart) -> BISA, tapi WAJIB tanya YES/NO manual (tidak boleh Auto)
HIGH_RISK_COMMAND_PATTERNS = [
    r"\b(remove-item|ri|rm|rmdir|del|erase|rd)\b",
    r"\bgit\s+(reset\s+--hard|clean\s+-f)",
    r"\b(invoke-expression|iex)\b",
    r"-encodedcommand\b",
    r"\breg\s+(add|delete|import)\b",
    r"\b(setx|setenvironmentvariable|set-executionpolicy|netsh|schtasks)\b",
    r"\b(shutdown|restart-computer|stop-computer|stop-service)\b",
]

# Hanya inti kernel/OS Windows yang dilarang ditimpa langsung agar Windows tidak rusak/bootloop
HARD_BLOCKED_WRITE_PREFIXES = [
    "c:\\windows\\system32",
    "c:\\windows\\syswow64",
    "c:\\windows\\boot",
]

# Nama folder atau pola file sensitif yang akan memunculkan konfirmasi YES/NO sebelum diakses/diedit
SENSITIVE_FOLDER_NAMES = {
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".kube",
    "appdata",
    "startup",
}

SENSITIVE_FILE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.ovpn",
    "id_rsa*",
    "id_ed25519*",
    "*credentials*",
    "*secret*",
    ".gitconfig",
    "microsoft.powershell_profile.ps1",
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
        {
            "type": "function",
            "function": {
                "name": "check_pc_health",
                "description": "Cek kondisi kesehatan & performa PC/laptop pengguna (CPU, penggunaan RAM, sisa ruang Disk, Uptime, dan Top 12 proses/aplikasi paling berat penyebab lemot).",
                "parameters": {
                    "type": "object",
                    "properties": {},
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
    """Mengeksekusi tool calls dengan batas keamanan folder & pemantauan Yes/No Bahasa Indonesia."""

    def __init__(self, workspace: Path, mode: str = "agent") -> None:
        self.workspace = workspace.resolve()
        self.mode = mode
        self.session_allow_edits = False
        self.session_allow_commands = False
        self.allowed_external_dirs: set[Path] = set()
        self.modified_files: dict[str, tuple[str, str]] = {}

    def reset_permissions(self) -> None:
        """Cabut semua izin sementara yang diberikan selama sesi ini."""
        self.session_allow_edits = False
        self.session_allow_commands = False
        self.allowed_external_dirs.clear()

    @staticmethod
    def _is_sensitive_path(target: Path) -> str | None:
        """Cek apakah path menyentuh folder atau file sensitif/rahasia."""
        lower_parts = {p.lower() for p in target.parts}
        hit_folders = lower_parts.intersection(SENSITIVE_FOLDER_NAMES)
        if hit_folders:
            folder_name = sorted(hit_folders)[0]
            return f"Lokasi ini berada di dalam folder sensitif/kredensial (`{folder_name}`)."

        fname = target.name.lower()
        if fname != ".env.example":
            for pat in SENSITIVE_FILE_PATTERNS:
                if fnmatch.fnmatch(fname, pat):
                    return (
                        f"File `{target.name}` terdeteksi berpotensi menyimpan konfigurasi rahasia, "
                        "API key, password, atau kunci privat."
                    )
        return None

    def _is_within_allowed_external(self, target: Path) -> bool:
        for allowed_dir in self.allowed_external_dirs:
            try:
                target.relative_to(allowed_dir)
                return True
            except ValueError:
                continue
        return False

    def _check_path_access(
        self, raw_path: str, action_desc: str, for_write: bool = False
    ) -> Path:
        """Validasi batas folder workspace & tampilkan dialog keamanan Yes/No Bahasa Indonesia."""
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (self.workspace / candidate).resolve()
        else:
            candidate = candidate.resolve()

        norm_lower = str(candidate).lower()

        # 1. Blokir keras HANYA penulisan ke inti kernel Windows (System32/Boot) agar OS tidak rusak fatal
        if for_write:
            for sys_prefix in HARD_BLOCKED_WRITE_PREFIXES:
                if norm_lower.startswith(sys_prefix):
                    raise PermissionError(
                        f"DIBLOKIR SISTEM: File inti kernel Windows tidak boleh ditimpa ({candidate})."
                    )

        # 2. Cek apakah berada di luar batas folder kerja proyek (Out-of-Workspace) -> Tanya YES / NO!
        inside_workspace = True
        try:
            candidate.relative_to(self.workspace)
        except ValueError:
            inside_workspace = False

        if not inside_workspace:
            ext_folder = candidate if candidate.is_dir() else candidate.parent
            if for_write:
                decision = ask_approval(
                    action_title=f"{action_desc} di Luar Folder Kerja Saat Ini",
                    detail=str(candidate),
                    explanation=(
                        f"AI ingin mengedit/menulis file di folder `{ext_folder}` (di luar `{self.workspace}`). "
                        "Pilih YES jika Anda mengizinkan perubahan di folder tersebut, atau NO untuk menolak."
                    ),
                    allow_always=False,
                    warning_level="high",
                )
                if decision != "allow":
                    console.print(f"  [yellow]🛡 Penulisan ke folder luar ditolak: {candidate}[/yellow]")
                    raise PermissionError(
                        f"Ditolak oleh pengguna: Penulisan di luar workspace ({candidate}) tidak diizinkan."
                    )
            elif not self._is_within_allowed_external(candidate):
                decision = ask_approval(
                    action_title=f"{action_desc} ke Folder Lain",
                    detail=str(candidate),
                    explanation=(
                        f"AI ingin masuk/membaca folder `{ext_folder}` yang berada di luar folder aktif `{self.workspace}`. "
                        "Pilih YES untuk mengizinkan AI mengecek folder tersebut, atau NO untuk menolak."
                    ),
                    allow_always=True,
                    warning_level="normal",
                )
                if decision == "always":
                    self.allowed_external_dirs.add(ext_folder)
                elif decision != "allow":
                    console.print(f"  [yellow]🛡 Akses masuk ke folder luar ditolak: {candidate}[/yellow]")
                    raise PermissionError(
                        f"Ditolak oleh pengguna: Akses ke folder/file ({candidate}) tidak diizinkan."
                    )

        # 3. Cek apakah menyentuh file/folder sensitif (.env, .ssh, kunci rahasia, dll.)
        sensitive_reason = self._is_sensitive_path(candidate)
        if sensitive_reason:
            decision = ask_approval(
                action_title=f"{action_desc} pada File/Folder Sensitif",
                detail=str(candidate),
                explanation=f"{sensitive_reason} Pastikan aman sebelum mengizinkan AI mengaksesnya.",
                allow_always=False,
                warning_level="high",
            )
            if decision != "allow":
                console.print(f"  [yellow]🛡 Akses ke data sensitif ditolak: {candidate}[/yellow]")
                raise PermissionError(
                    f"Ditolak oleh pengguna: Akses ke file/folder sensitif '{candidate.name}' dibatalkan."
                )

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
            if name == "check_pc_health":
                return self._check_pc_health()

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
        except PermissionError as exc:
            return str(exc)
        except Exception as exc:
            return f"Error saat menjalankan {name}: {exc}"

    def _list_files(self, path: str, max_depth: int) -> str:
        target = self._check_path_access(
            path, action_desc="Melihat daftar isi folder", for_write=False
        )
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
        target = self._check_path_access(
            path, action_desc="Membaca isi file", for_write=False
        )
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
        target = self._check_path_access(
            path, action_desc=f"Mencari teks '{query}' di dalam folder", for_write=False
        )
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
                if self._is_sensitive_path(fpath):
                    continue
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

    def _confirm_edit(self, target: Path, display_path: str, old_text: str, new_text: str, is_new: bool) -> bool:
        render_diff(display_path, old_text, new_text)
        if self.mode == "auto" or self.session_allow_edits:
            return True

        action_label = f"Membuat file baru `{display_path}`" if is_new else f"Mengubah isi file `{display_path}`"
        decision = ask_approval(
            action_title=action_label,
            detail=str(target),
            explanation=(
                "Periksa kotak Diff berwarna hijau (+) dan merah (-) di atas. "
                "Pilih YES jika perubahan kode sudah sesuai keinginan Anda."
            ),
            allow_always=True,
        )
        if decision == "always":
            self.session_allow_edits = True
            return True
        return decision == "allow"

    def _record_modification(self, display_path: str, original: str, updated: str) -> None:
        if display_path in self.modified_files:
            orig, _ = self.modified_files[display_path]
            self.modified_files[display_path] = (orig, updated)
        else:
            self.modified_files[display_path] = (original, updated)

    def _display_rel(self, target: Path) -> str:
        try:
            return target.relative_to(self.workspace).as_posix()
        except ValueError:
            return str(target)

    def _write_file(self, path: str, content: str) -> str:
        target = self._check_path_access(
            path, action_desc="Menulis / membuat file", for_write=True
        )
        disp = self._display_rel(target)
        is_new = not target.exists()
        old_content = "" if is_new else target.read_text(encoding="utf-8", errors="replace")

        if not self._confirm_edit(target, disp, old_content, content, is_new=is_new):
            console.print(f"  [yellow]⚠ Penulisan file '{disp}' dibatalkan oleh pengguna.[/yellow]")
            return f"Ditolak oleh pengguna: File '{disp}' tidak diubah."

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._record_modification(disp, old_content, content)
        console.print(f"  [bold #00f5d4]✔ Tersimpan:[/bold #00f5d4] [white]{disp}[/white]")
        return f"Berhasil menulis file '{disp}' ({len(content.splitlines())} baris)."

    def _edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self._check_path_access(
            path, action_desc="Mengedit baris kode pada file", for_write=True
        )
        if not target.exists():
            return f"Error: File '{path}' tidak ditemukan."

        disp = self._display_rel(target)
        original = target.read_text(encoding="utf-8", errors="replace")

        if old_text not in original:
            return (
                f"Error: Blok `old_text` tidak ditemukan persis di '{disp}'. "
                "Gunakan read_file terlebih dahulu untuk memastikan indentasi dan isi baris akurat."
            )

        updated = original.replace(old_text, new_text, 1)
        if not self._confirm_edit(target, disp, original, updated, is_new=False):
            console.print(f"  [yellow]⚠ Edit file '{disp}' dibatalkan oleh pengguna.[/yellow]")
            return f"Ditolak oleh pengguna: File '{disp}' tidak diubah."

        target.write_text(updated, encoding="utf-8")
        self._record_modification(disp, original, updated)
        console.print(f"  [bold #00f5d4]✔ Berhasil diedit:[/bold #00f5d4] [white]{disp}[/white]")
        return f"Berhasil memperbarui '{disp}'."

    def _check_pc_health(self) -> str:
        """Diagnostik performa PC (CPU, RAM, Disk, Top aplikasi pemakan memori/CPU) dengan izin YES/NO."""
        decision = ask_approval(
            action_title="Mengecek Kesehatan & Performa PC/Laptop",
            detail="CPU Load, Pemakaian RAM, Sisa Ruang Disk, & Top 12 Aplikasi Terberat",
            explanation=(
                "AI ingin membaca informasi performa sistem (Read-Only, tidak mengubah pengaturan apa pun) "
                "untuk membantu menganalisis penyebab kendala/lemot pada PC Anda."
            ),
            allow_always=True,
        )
        if decision not in ("allow", "always"):
            return "Ditolak oleh pengguna: Pengecekan kondisi PC dibatalkan."

        ps_diag = (
            "$ErrorActionPreference = 'SilentlyContinue'; "
            "$os = Get-CimInstance Win32_OperatingSystem; "
            "$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; "
            "Write-Output '=== RINGKASAN PERFORMA PC ==='; "
            "if ($os) { "
            "  $totalRam = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2); "
            "  $freeRam = [math]::Round($os.FreePhysicalMemory / 1MB, 2); "
            "  $usedRam = [math]::Round($totalRam - $freeRam, 2); "
            "  $pctRam = [math]::Round(($usedRam / $totalRam) * 100, 1); "
            "  $uptime = (Get-Date) - $os.LastBootUpTime; "
            "  Write-Output \"CPU Load     : $cpu %\"; "
            "  Write-Output \"RAM Terpakai : $usedRam GB / $totalRam GB ($pctRam % - Sisa $freeRam GB)\"; "
            "  Write-Output (\"Uptime PC    : {0} hari {1} jam {2} menit\" -f $uptime.Days, $uptime.Hours, $uptime.Minutes); "
            "} else { "
            "  $procRam = [math]::Round(((Get-Process | Measure-Object WorkingSet64 -Sum).Sum / 1GB), 2); "
            "  Write-Output \"Total WorkingSet Aplikasi Aktif : $procRam GB\"; "
            "} "
            "Write-Output \"`n=== PENYIMPANAN DISK ===\"; "
            "Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object { "
            "  $u = [math]::Round($_.Used / 1GB, 1); $f = [math]::Round($_.Free / 1GB, 1); $t = [math]::Round(($_.Used + $_.Free) / 1GB, 1); "
            "  Write-Output (\"Drive {0}: -> Sisa {1} GB dari {2} GB (Terpakai {3} GB)\" -f $_.Name, $f, $t, $u) "
            "}; "
            "Write-Output \"`n=== TOP 12 APLIKASI PEMAKAN RAM & CPU TERBESAR ===\"; "
            "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 "
            "  @{N='Aplikasi';E={$_.ProcessName}}, "
            "  @{N='PID';E={$_.Id}}, "
            "  @{N='RAM_MB';E={[math]::Round($_.WorkingSet64 / 1MB, 1)}}, "
            "  @{N='CPU_Detik';E={[math]::Round($_.CPU, 1)}} | Format-Table -AutoSize | Out-String -Width 120"
        )
        console.print("  [dim]🩺 Mengecek diagnostik performa CPU, RAM, Disk & Proses PC...[/dim]")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_diag],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return (proc.stdout or proc.stderr or "(Gagal membaca metrik PC)").strip()

    def undo_last_changes(self) -> list[str]:
        """Kembalikan seluruh file yang diedit pada sesi ini ke kondisi awal (fitur /undo)."""
        restored: list[str] = []
        for disp, (original, _updated) in list(self.modified_files.items()):
            target = (self.workspace / disp).resolve()
            try:
                if original == "" and target.exists():
                    # File baru dibuat pada sesi ini -> kosongkan atau hapus dengan aman di dalam workspace
                    target.relative_to(self.workspace)
                    target.unlink()
                else:
                    target.write_text(original, encoding="utf-8")
                restored.append(disp)
                del self.modified_files[disp]
            except (OSError, ValueError):
                continue
        return restored

    def _run_command(self, command: str, timeout: int) -> str:
        lowered = command.lower()
        for pat in BLOCKED_COMMAND_PATTERNS:
            if re.search(pat, lowered):
                return (
                    f"DIBLOKIR SISTEM: Perintah '{command}' ditolak karena mencoba mengubah konfigurasi laptop/sistem operasi."
                )

        is_delete_or_risky = any(
            re.search(pat, lowered) for pat in HIGH_RISK_COMMAND_PATTERNS
        )
        touches_outside = bool(re.search(r"(\.\.[\\/]|[a-z]:\\)", lowered)) and (
            str(self.workspace).lower() not in lowered
        )
        force_manual = is_delete_or_risky or touches_outside
        warn_lvl = "high" if force_manual else "normal"

        if is_delete_or_risky:
            extra_note = (
                "PERINGATAN: Perintah ini mengandung aksi penghapusan file / reset! "
                "Periksa dengan teliti sebelum memilih YES."
            )
        elif touches_outside:
            extra_note = (
                "PERHATIAN: Perintah ini merujuk ke path di luar folder kerja proyek Anda! Periksa dengan teliti."
            )
        else:
            extra_note = f"Perintah PowerShell ini hanya akan dijalankan di dalam folder kerja `{self.workspace}`."

        if force_manual or not self.session_allow_commands:
            decision = ask_approval(
                action_title="Menjalankan Perintah Terminal (PowerShell)",
                detail=command,
                explanation=extra_note,
                allow_always=not force_manual,
                warning_level=warn_lvl,
            )
            if decision == "always" and not force_manual:
                self.session_allow_commands = True
            elif decision != "allow":
                console.print("  [yellow]⚠ Eksekusi perintah terminal ditolak oleh pengguna.[/yellow]")
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
