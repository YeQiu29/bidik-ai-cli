"""Manajemen konfigurasi lokal Bidik CLI (~/.bidik/config.json)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".bidik"
CONFIG_FILE = CONFIG_DIR / "config.json"
FALLBACK_DIR = Path(__file__).resolve().parent.parent
TEMP_FALLBACK_DIR = Path(tempfile.gettempdir()) / "bidik-cli"

DEFAULT_API_BASE = "http://192.168.6.217:20128/v1"
DEFAULT_API_KEY = ""
DEFAULT_MODEL = "bidik_ai"


def get_data_dir() -> Path:
    for candidate in (CONFIG_DIR, FALLBACK_DIR, TEMP_FALLBACK_DIR):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".bidik_write_probe"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return TEMP_FALLBACK_DIR


def get_history_file() -> Path:
    d = get_data_dir()
    name = "prompt_history.txt" if d == CONFIG_DIR else ".bidik_history.txt"
    return d / name


def _load_dotenv_values() -> dict[str, str]:
    """Baca file .env sederhana jika ada di cwd atau folder instalasi."""
    values: dict[str, str] = {}
    for env_path in (Path.cwd() / ".env", FALLBACK_DIR / ".env"):
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, v = s.split("=", 1)
                    values[k.strip()] = v.strip().strip("\"'")
            except OSError:
                pass
    return values


def _detect_defaults() -> tuple[str, str, str]:
    """Deteksi dari environment variable, .env, atau ~/.continue/config.yaml."""
    dotenv = _load_dotenv_values()
    api_base = os.environ.get("BIDIK_API_BASE") or dotenv.get("BIDIK_API_BASE") or DEFAULT_API_BASE
    api_key = os.environ.get("BIDIK_API_KEY") or dotenv.get("BIDIK_API_KEY") or DEFAULT_API_KEY
    model = os.environ.get("BIDIK_MODEL") or dotenv.get("BIDIK_MODEL") or DEFAULT_MODEL

    continue_cfg = Path.home() / ".continue" / "config.yaml"
    if continue_cfg.exists():
        try:
            text = continue_cfg.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("apiBase:") and not os.environ.get("BIDIK_API_BASE") and not dotenv.get("BIDIK_API_BASE"):
                    val = stripped.split("apiBase:", 1)[1].strip().strip("\"'")
                    if val:
                        api_base = val
                elif stripped.startswith("apiKey:") and not api_key:
                    val = stripped.split("apiKey:", 1)[1].strip().strip("\"'")
                    if val:
                        api_key = val
        except OSError:
            pass
    return api_base, api_key, model


@dataclass
class BidikConfig:
    api_base: str = DEFAULT_API_BASE
    api_key: str = DEFAULT_API_KEY
    model: str = DEFAULT_MODEL
    mode: str = "agent"  # "agent" | "plan" | "auto"
    max_steps: int = 25
    timeout: float = 120.0
    show_reasoning: bool = True
    trusted_workspaces: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "BidikConfig":
        api_base, api_key, model = _detect_defaults()
        cfg = cls(api_base=api_base, api_key=api_key, model=model)
        for cfg_path in (CONFIG_FILE, FALLBACK_DIR / "config.local.json"):
            if cfg_path.exists():
                try:
                    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
                    for key, val in raw.items():
                        if hasattr(cfg, key) and val not in (None, ""):
                            setattr(cfg, key, val)
                    break
                except (OSError, json.JSONDecodeError):
                    pass
        return cfg

    def save(self) -> None:
        try:
            d = get_data_dir()
            fname = "config.json" if d == CONFIG_DIR else "config.local.json"
            target = d / fname
            target.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
