"""Sistem Auto-Update Checker & Updater langsung dari GitHub (mendukung Public & Private Repo)."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import __version__
from .config import BidikConfig, get_data_dir

GITHUB_REPO = "YeQiu29/bidik-ai-cli"
GITHUB_BRANCH = "main"


@dataclass
class UpdateInfo:
    has_update: bool = False
    latest_sha: str = ""
    latest_message: str = ""
    latest_version: str = __version__
    error: str = ""


def _state_file() -> Path:
    return get_data_dir() / "update_state.json"


def _read_saved_sha() -> str:
    sf = _state_file()
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            return str(data.get("installed_sha", ""))
        except (OSError, json.JSONDecodeError):
            pass
    return ""


def _save_installed_sha(sha: str) -> None:
    if not sha:
        return
    try:
        _state_file().write_text(
            json.dumps({"installed_sha": sha, "version": __version__}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _install_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _github_headers(config: BidikConfig) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Bidik-CLI/{__version__}",
    }
    if getattr(config, "github_token", ""):
        headers["Authorization"] = f"Bearer {config.github_token}"
    return headers


def _parse_version_tuple(ver: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", ver)
    return tuple(int(n) for n in nums) if nums else (0,)


def _fetch_remote_version(http: httpx.Client, config: BidikConfig) -> str:
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/bidik_cli/__init__.py"
    headers = _github_headers(config)
    resp = http.get(raw_url, headers=headers)
    if resp.status_code == 200:
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', resp.text)
        if m:
            return m.group(1)
    return __version__


def check_for_updates(config: BidikConfig, timeout: float = 2.2) -> UpdateInfo:
    """Cek cepat apakah ada commit atau versi baru di GitHub."""
    root = _install_root()
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as http:
            resp = http.get(api_url, headers=_github_headers(config))
            if resp.status_code in (401, 403, 404):
                # Jika repo diubah menjadi Private dan belum ada github_token, coba cek via `git ls-remote`
                if (root / ".git").exists():
                    return _check_via_git(root)
                return UpdateInfo(has_update=False)
            resp.raise_for_status()
            payload = resp.json()
            remote_sha = str(payload.get("sha", ""))
            commit_msg = (
                str(payload.get("commit", {}).get("message", "")).splitlines()[0][:70]
            )
            remote_ver = _fetch_remote_version(http, config)
    except Exception as exc:
        return UpdateInfo(has_update=False, error=str(exc))

    if not remote_sha:
        return UpdateInfo(has_update=False)

    # Jika folder memiliki .git (misal hasil git clone atau laptop developer)
    if (root / ".git").exists():
        try:
            local_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=3,
            )
            if local_proc.returncode == 0:
                local_sha = local_proc.stdout.strip()
                if local_sha == remote_sha:
                    _save_installed_sha(remote_sha)
                    return UpdateInfo(has_update=False, latest_sha=remote_sha)
                # Pastikan remote_sha bukan commit lama yang sudah ada di riwayat lokal developer
                anc = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", remote_sha, "HEAD"],
                    cwd=str(root),
                    capture_output=True,
                    timeout=3,
                )
                if anc.returncode == 0:
                    return UpdateInfo(has_update=False, latest_sha=local_sha)
                return UpdateInfo(
                    has_update=True,
                    latest_sha=remote_sha,
                    latest_message=commit_msg,
                    latest_version=remote_ver,
                )
        except Exception:
            pass

    # Jika diinstal lewat install.bat / ZIP tanpa folder .git
    saved_sha = _read_saved_sha()
    if not saved_sha:
        if _parse_version_tuple(remote_ver) > _parse_version_tuple(__version__):
            return UpdateInfo(
                has_update=True,
                latest_sha=remote_sha,
                latest_message=commit_msg,
                latest_version=remote_ver,
            )
        # Simpan baseline SHA pertama kali agar update berikutnya langsung terdeteksi
        _save_installed_sha(remote_sha)
        return UpdateInfo(has_update=False, latest_sha=remote_sha)

    if saved_sha != remote_sha:
        return UpdateInfo(
            has_update=True,
            latest_sha=remote_sha,
            latest_message=commit_msg,
            latest_version=remote_ver,
        )

    return UpdateInfo(has_update=False, latest_sha=remote_sha)


def _check_via_git(root: Path) -> UpdateInfo:
    """Fallback pengecekan update untuk Private Repo menggunakan kredensial Git lokal."""
    try:
        rem = subprocess.run(
            ["git", "ls-remote", "origin", f"refs/heads/{GITHUB_BRANCH}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=4,
        )
        loc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if rem.returncode == 0 and loc.returncode == 0 and rem.stdout.strip():
            remote_sha = rem.stdout.split()[0].strip()
            local_sha = loc.stdout.strip()
            if remote_sha and remote_sha != local_sha:
                return UpdateInfo(
                    has_update=True,
                    latest_sha=remote_sha,
                    latest_message="Pembaruan tersedia di repository Private",
                )
    except Exception:
        pass
    return UpdateInfo(has_update=False)


def perform_update(config: BidikConfig) -> tuple[bool, str]:
    """Tarik & pasang pembaruan terbaru dari GitHub tanpa menghapus config/API key user."""
    root = _install_root()
    old_pyproject = (
        (root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
        if (root / "pyproject.toml").exists()
        else ""
    )

    # Jalur 1: Jika folder instalasi adalah Git repository (.git tersedia)
    if (root / ".git").exists():
        ok, msg = _update_via_git(root, old_pyproject)
        if ok:
            return (True, msg)
        # Jika git gagal karena bukan git atau kendala lain, lanjut coba via ZIP

    # Jalur 2: Download ZIP langsung dari GitHub (tidak butuh Git terinstall di laptop teman!)
    return _update_via_zipball(root, config, old_pyproject)


def _update_via_git(root: Path, old_pyproject: str) -> tuple[bool, str]:
    try:
        status_proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status_proc.returncode == 0 and status_proc.stdout.strip():
            return (
                False,
                "Terdeteksi perubahan kode lokal yang belum di-commit di folder ini. "
                "Simpan/commit terlebih dahulu sebelum menjalankan `/update`.",
            )

        pull_proc = subprocess.run(
            ["git", "pull", "--ff-only", "origin", GITHUB_BRANCH],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if pull_proc.returncode != 0:
            err = (pull_proc.stderr or pull_proc.stdout).strip()
            return (False, f"Gagal menarik update via Git: {err}")

        sha_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        new_sha = sha_proc.stdout.strip() if sha_proc.returncode == 0 else ""
        _save_installed_sha(new_sha)
        _refresh_deps_if_needed(root, old_pyproject)
        short = new_sha[:7] if new_sha else "terbaru"
        return (
            True,
            f"Bidik CLI berhasil diperbarui via Git (commit `{short}`). Buka ulang `bidik` untuk memuat fitur baru!",
        )
    except FileNotFoundError:
        return (False, "Git tidak ditemukan")
    except Exception as exc:
        return (False, str(exc))


def _update_via_zipball(
    root: Path, config: BidikConfig, old_pyproject: str
) -> tuple[bool, str]:
    has_token = bool(getattr(config, "github_token", ""))
    zip_url = (
        f"https://api.github.com/repos/{GITHUB_REPO}/zipball/{GITHUB_BRANCH}"
        if has_token
        else f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
    )

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as http:
            # Ambil SHA terbaru untuk dicatat setelah update berhasil
            latest_sha = ""
            api_resp = http.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}",
                headers=_github_headers(config),
            )
            if api_resp.status_code == 200:
                latest_sha = str(api_resp.json().get("sha", ""))

            resp = http.get(zip_url, headers=_github_headers(config))
            if resp.status_code in (401, 403, 404):
                return (
                    False,
                    "Repository saat ini bersifat Private. Atur token akses baca dengan perintah "
                    "`/config github_token <TOKEN_GITHUB>` atau clone menggunakan Git.",
                )
            resp.raise_for_status()
            zip_bytes = resp.content
    except Exception as exc:
        return (False, f"Gagal mengunduh pembaruan dari GitHub: {exc}")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(tmp_path)

            extracted_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
            if not extracted_dirs:
                return (False, "Arsip pembaruan dari GitHub kosong atau tidak valid.")
            src_root = extracted_dirs[0]

            # Salin kode sumber terbaru ke folder instalasi (tanpa menyentuh .venv / config user)
            src_pkg = src_root / "bidik_cli"
            dst_pkg = root / "bidik_cli"
            if src_pkg.exists():
                dst_pkg.mkdir(parents=True, exist_ok=True)
                for py_file in src_pkg.glob("*.py"):
                    shutil.copy2(py_file, dst_pkg / py_file.name)

            src_assets = src_root / "assets"
            if src_assets.exists():
                dst_assets = root / "assets"
                dst_assets.mkdir(parents=True, exist_ok=True)
                for asset in src_assets.iterdir():
                    if asset.is_file():
                        shutil.copy2(asset, dst_assets / asset.name)

            for top_file in ("pyproject.toml", "README.md", "install.bat", "install.ps1", "uninstall.bat"):
                sf = src_root / top_file
                if sf.exists():
                    shutil.copy2(sf, root / top_file)

        _refresh_deps_if_needed(root, old_pyproject)
        if latest_sha:
            _save_installed_sha(latest_sha)

        short = latest_sha[:7] if latest_sha else "terbaru"
        return (
            True,
            f"Bidik CLI berhasil diperbarui ke versi terbaru (`{short}`)! "
            "Silakan ketik `/exit` lalu jalankan `bidik` lagi agar kode baru aktif.",
        )
    except Exception as exc:
        return (False, f"Gagal memasang file pembaruan: {exc}")


def _refresh_deps_if_needed(root: Path, old_pyproject: str) -> None:
    new_pyproject = (
        (root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
        if (root / "pyproject.toml").exists()
        else ""
    )
    if new_pyproject and new_pyproject != old_pyproject:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-e", str(root)],
            capture_output=True,
            timeout=120,
        )
