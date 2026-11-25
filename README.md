# ⚡ Bidik CLI

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-00bbf9)
![Gateway](https://img.shields.io/badge/LLM_Gateway-9router_OpenAI_API-9b5de5)

**Bidik CLI** adalah *Agentic AI Coding Assistant* berbasis terminal (seperti Antigravity CLI / OpenCode / Claude Code) yang dibangun menggunakan **Python** dan terhubung langsung ke server AI **`9router`**.

Dirancang ringan, aman di dalam *isolated virtual environment* (`.venv`), dan mampu membantu membaca kode, mencari *bug*, mengedit file proyek lengkap dengan *preview diff*, serta menjalankan pengujian langsung dari terminal Anda.

---

## ✨ Fitur Utama

* **🤖 Pemilihan Model Live (`/model`):** Mengambil daftar seluruh model secara *real-time* dari endpoint `/v1/models` server `9router` (Combo, Antigravity, Gemini, OpenCode, Ollama, dll.) lengkap dengan fitur pencarian cepat & navigasi tombol panah.
* **⚡ Popup Autocomplete Interaktif (`/` & `@`):**
  * Ketik `/` untuk memunculkan menu perintah otomatis.
  * Ketik `@` untuk mencari dan melampirkan file proyek ke dalam *prompt* (contoh: `perbaiki bug di @login.py`).
* **🕒 Smart Session Cache (`/resume` & `bidik -c`):** Riwayat percakapan tersimpan otomatis dan dilengkapi *auto-cleanup* (maksimal 20 sesi terakhir) agar penyimpanan tetap ringan.
* **🛠️ Local Coding Agent Tools:** Mendukung `list_files`, `read_file`, `search_code`, `write_file`, `edit_file` (dengan tampilan *unified diff* hijau/merah), dan `run_command` dengan konfirmasi keamanan pengguna.
* **🎛️ 3 Mode Kerja (`/mode`):**
  * `⚡ Agent` — Mode standar dengan konfirmasi izin sebelum mengubah file / menjalankan terminal.
  * `🧭 Plan` — Mode *read-only* murni untuk diskusi arsitektur & analisis aman tanpa mengubah file apa pun.
  * `🚀 Auto` — Otomatis menerapkan perubahan kode di dalam folder proyek kerja.

---

## 📋 Prasyarat

* **Python 3.10 atau lebih baru** (`python --version`) — *tidak memerlukan Node.js / npm*.
* Terhubung ke jaringan LAN / VPN yang dapat mengakses server **`9router`** (default: `http://192.168.6.217:20128/v1`).

---

## 🚀 Cara Instalasi

### Opsi 1: Auto-Installer Windows (`install.bat` — Paling Mudah)

1. Clone repository ini atau ekstrak paket `.zip`:
   ```powershell
   git clone https://github.com/<USERNAME_ANDA>/bidik-cli.git
   cd bidik-cli
   ```
2. Klik 2x file **`install.bat`** (atau jalankan `.\install.bat` di terminal).
   * Installer otomatis membuat *virtual environment* terisolasi di `~/.bidik-cli/.venv` (aman, tidak mengganggu library Python sistem).
   * Otomatis mendaftarkan perintah global `bidik` ke *User PATH* (tanpa *Run as Administrator*).
3. Buka jendela terminal **baru**, lalu ketik:
   ```powershell
   bidik
   ```

### Opsi 2: Install Langsung via `pip` dari GitHub (Windows / Linux / macOS)

```bash
# Menggunakan virtual environment / pipx (direkomendasikan)
pip install git+https://github.com/<USERNAME_ANDA>/bidik-cli.git
```

---

## 💻 Cara Penggunaan

Masuk ke folder proyek kodingan mana saja, lalu jalankan:

```powershell
# Masuk ke mode interaktif (TUI)
bidik

# Melanjutkan sesi percakapan terakhir di folder proyek ini
bidik -c

# Memilih dari daftar sesi percakapan sebelumnya
bidik -r

# Menjalankan satu perintah cepat (one-shot)
bidik "jelaskan struktur kode di proyek ini"
```

Saat pertama kali dijalankan, **Bidik CLI** akan menanyakan **URL Server `9router`** dan **API Key (`sk-...`)** Anda lalu menyimpannya secara lokal di `~/.bidik/config.json`.

---

## ⌨️ Daftar Slash Commands

| Perintah | Fungsi |
| :--- | :--- |
| `/model` | Buka pemilih model AI interaktif (*live* dari server `9router`) dengan fitur cari/filter |
| `/resume` | Pilih & lanjutkan sesi obrolan sebelumnya (*auto-cleanup* maks 20 sesi) |
| `/new` | Mulai sesi obrolan baru tanpa menghapus sesi sebelumnya |
| `/mode` | Ubah mode kerja: **Agent**, **Plan** (*read-only*), atau **Auto** |
| `/status` | Cek koneksi & latensi server `9router`, ukuran *cache* sesi, dan pemakaian token |
| `/diff` | Tampilkan *diff* perubahan file pada sesi saat ini atau `git status` |
| `/clear` | Bersihkan layar & reset percakapan saat ini |
| `/compact` | Ringkas riwayat percakapan panjang agar hemat *context window* |
| `/clean` | Hapus bersih seluruh file *cache* sesi obrolan di disk (`0 KB`) |
| `/config` | Lihat atau ubah URL Server (`/config url ...`) & API Key (`/config key ...`) |
| `/help` | Tampilkan panduan lengkap |
| `/exit` | Keluar dari Bidik CLI |

---

## 🗑️ Cara Uninstall (Windows)

Klik 2x file **`uninstall.bat`** (atau jalankan `%USERPROFILE%\.bidik-cli\uninstall.bat`) untuk menghapus lingkungan terisolasi beserta perintah `bidik` dari *User PATH* secara bersih.

---

## 📂 Struktur Proyek

```text
bidik-cli/
├── bidik_cli/
│   ├── __init__.py      # Metadata versi aplikasi
│   ├── main.py          # Entry point CLI & penanganan slash commands
│   ├── config.py        # Manajemen konfigurasi (~/.bidik/config.json & .env)
│   ├── client.py        # Klien OpenAI streaming & pengambilan model live 9router
│   ├── ui.py            # Komponen TUI Rich, banner, diff viewer & selector interaktif
│   ├── completer.py     # Autocomplete popup otomatis untuk '/' dan '@file'
│   ├── sessions.py      # Smart session cache dengan auto-cleanup
│   ├── agent.py         # Agentic loop multi-step & reasoning parser
│   └── tools.py         # Local coding tools berbatas workspace
├── install.bat          # One-click installer untuk Windows
├── install.ps1          # Script PowerShell pendamping installer
├── uninstall.bat        # One-click uninstaller bersih
├── .env.example         # Contoh konfigurasi environment variable
├── .gitignore           # Aturan file yang diabaikan Git
└── pyproject.toml       # Definisi paket Python & entry point `bidik`
```
