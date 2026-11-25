$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  ======================================================" -ForegroundColor Cyan
Write-Host "         BIDIK CLI v1.0.0 - AUTO INSTALLER              " -ForegroundColor Cyan
Write-Host "    Powered By Dennis Hilmansyah - Agentic Coding CLI   " -ForegroundColor DarkCyan
Write-Host "  ======================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Cek instalasi Python (>= 3.10)
$pythonCmd = $null
foreach ($candidate in @("python", "py")) {
    try {
        $cmdArgs = if ($candidate -eq "py") { @("-3", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}'); sys.exit(0 if sys.version_info >= (3,10) else 1)") } else { @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}'); sys.exit(0 if sys.version_info >= (3,10) else 1)") }
        $ver = & $candidate @cmdArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver) {
            $pythonCmd = $candidate
            Write-Host "  [OK] Python $ver terdeteksi ($candidate)" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "  [X] Python 3.10+ belum terdeteksi di laptop ini!" -ForegroundColor Red
    Write-Host "      Silakan install Python terlebih dahulu dari https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "      (Pastikan centang 'Add Python to PATH' saat install)." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Tekan Enter untuk menutup"
    exit 1
}

$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = Join-Path $HOME ".bidik-cli"
$configDir  = Join-Path $HOME ".bidik"
$binDir     = Join-Path $configDir "bin"

Write-Host "  [*] Lokasi instalasi terisolasi : $installDir" -ForegroundColor Gray

# 2. Salin kode sumber bersih ke ~/.bidik-cli (kecuali jika sudah dijalankan dari folder tersebut)
if ($sourceDir.TrimEnd('\') -ne $installDir.TrimEnd('\')) {
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $installDir "bidik_cli") | Out-Null

    Copy-Item -Force (Join-Path $sourceDir "pyproject.toml") $installDir
    if (Test-Path (Join-Path $sourceDir "README.md")) {
        Copy-Item -Force (Join-Path $sourceDir "README.md") $installDir
    }
    if (Test-Path (Join-Path $sourceDir "uninstall.bat")) {
        Copy-Item -Force (Join-Path $sourceDir "uninstall.bat") $installDir
    }
    Copy-Item -Force (Join-Path $sourceDir "bidik_cli\*.py") (Join-Path $installDir "bidik_cli")
    Write-Host "  [OK] File program berhasil disalin." -ForegroundColor Green
}

# 3. Buat Virtual Environment terisolasi (tidak mengganggu Python sistem)
$venvDir = Join-Path $installDir ".venv"
$venvPy  = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "  [*] Membuat virtual environment terisolasi (.venv)..." -ForegroundColor Cyan
    if ($pythonCmd -eq "py") {
        & py -3 -m venv $venvDir
    } else {
        & python -m venv $venvDir
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Gagal membuat virtual environment di $venvDir"
    }
}
Write-Host "  [OK] Virtual environment siap." -ForegroundColor Green

# 4. Install paket & dependensi
Write-Host "  [*] Mengunduh & menginstal pustaka Bidik CLI (mohon tunggu 1-2 menit)..." -ForegroundColor Cyan
& $venvPip install --disable-pip-version-check -e $installDir
if ($LASTEXITCODE -ne 0) {
    throw "Gagal menginstal dependensi Bidik CLI. Pastikan koneksi internet aktif."
}
Write-Host "  [OK] Pustaka Bidik CLI berhasil terinstal." -ForegroundColor Green

# 5. Buat launcher global ringan di ~/.bidik/bin & daftarkan ke User PATH
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$bidikExe = Join-Path $venvDir "Scripts\bidik.exe"

$cmdLauncher = Join-Path $binDir "bidik.cmd"
Set-Content -Path $cmdLauncher -Encoding ASCII -Value "@echo off`r`n`"$bidikExe`" %*`r`n"

$shLauncher = Join-Path $binDir "bidik"
$bidikExePosix = $bidikExe -replace '\\', '/'
Set-Content -Path $shLauncher -Encoding ASCII -NoNewline -Value "#!/usr/bin/env sh`nexec `"$bidikExePosix`" `"`$@`"`n"

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
$pathItems = $userPath -split ';' | Where-Object { $_ -ne "" }
if ($pathItems -notcontains $binDir) {
    $newPath = ($pathItems + $binDir) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "  [OK] Perintah 'bidik' berhasil didaftarkan ke User PATH." -ForegroundColor Green
} else {
    Write-Host "  [OK] Perintah 'bidik' sudah terdaftar di User PATH." -ForegroundColor Green
}

# 6. Konfigurasi Server & API Key jika belum ada di ~/.bidik/config.json
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$cfgPath = Join-Path $configDir "config.json"
if (-not (Test-Path $cfgPath)) {
    Write-Host ""
    $enteredUrl = Read-Host "  Masukkan URL 9router (tekan Enter untuk default http://192.168.6.217:20128/v1)"
    if (-not $enteredUrl -or $enteredUrl.Trim() -eq "") {
        $enteredUrl = "http://192.168.6.217:20128/v1"
    }
    $customKey = Read-Host "  Masukkan API Key 9router (contoh: sk-... / tekan Enter untuk isi nanti saat buka bidik)"
    $cfgObj = @{
        api_base = $enteredUrl.Trim()
        api_key  = $customKey.Trim()
        model    = "bidik_ai"
        mode     = "agent"
    }
    $cfgObj | ConvertTo-Json | Set-Content -Path $cfgPath -Encoding UTF8
    Write-Host "  [OK] Konfigurasi awal berhasil disimpan di $cfgPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "  ======================================================" -ForegroundColor Green
Write-Host "         INSTALASI BIDIK CLI SELESAI & SIAP PAKAI!      " -ForegroundColor Green
Write-Host "  ======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Cara pakai:" -ForegroundColor White
Write-Host "  1. Buka jendela PowerShell / CMD / Terminal VS Code BARU" -ForegroundColor Yellow
Write-Host "  2. Masuk ke folder kodingan Anda, lalu ketik: bidik" -ForegroundColor Cyan
Write-Host "  3. Ketik /model untuk memilih model AI dari server 9router" -ForegroundColor Gray
Write-Host ""
Read-Host "  Tekan Enter untuk keluar dari installer"
