$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  ======================================================" -ForegroundColor Cyan
Write-Host "         BIDIK CLI v1.0.0 - AUTO INSTALLER              " -ForegroundColor Cyan
Write-Host "    Powered By Dennis Hilmansyah - Agentic Coding CLI   " -ForegroundColor DarkCyan
Write-Host "  ======================================================" -ForegroundColor Cyan
Write-Host ""

function Refresh-SessionPath {
    $mPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $uPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$mPath;$uPath"
}

function Find-ValidPython {
    Refresh-SessionPath
    $checkCode = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}'); sys.exit(0 if sys.version_info >= (3,10) else 1)"

    # Cek via command PATH (python / py -3)
    foreach ($candidate in @("python", "py")) {
        try {
            $extra = if ($candidate -eq "py") { @("-3") } else { @() }
            $ver = & $candidate @extra -c $checkCode 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) {
                return @{ Exe = $candidate; PrefixArgs = $extra; Version = ($ver | Select-Object -Last 1).Trim() }
            }
        } catch {}
    }

    # Cek lokasi standar instalasi Python Windows di disk
    $diskCandidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "$env:ProgramFiles\Python312\python.exe"
    )
    foreach ($exePath in $diskCandidates) {
        if (Test-Path $exePath) {
            try {
                $ver = & $exePath -c $checkCode 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    return @{ Exe = $exePath; PrefixArgs = @(); Version = ($ver | Select-Object -Last 1).Trim() }
                }
            } catch {}
        }
    }
    return $null
}

function Install-PythonAutomatically {
    Write-Host "  [!] Python 3.10+ belum ditemukan di laptop ini." -ForegroundColor Yellow
    $ans = Read-Host "  Apakah Anda ingin menginstal Python 3.12 resmi secara otomatis sekarang? (Y/N) [Enter = Y]"
    if ($ans -and $ans.Trim().ToUpper() -ne "Y") {
        Write-Host "  [X] Instalasi dibatalkan oleh pengguna." -ForegroundColor Red
        exit 1
    }

    # Opsi Utama: Gunakan winget bawaan Windows 10/11 (User scope, tidak butuh Administrator)
    $hasWinget = $false
    try {
        $null = Get-Command winget -ErrorAction Stop
        $hasWinget = $true
    } catch {}

    if ($hasWinget) {
        Write-Host "  [*] Menginstal Python 3.12 otomatis melalui Windows Package Manager (winget)..." -ForegroundColor Cyan
        try {
            & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        } catch {}
    }

    $found = Find-ValidPython
    if ($found) { return $found }

    # Fallback Otomatis: Unduh installer resmi langsung dari python.org jika winget gagal/belum ada
    Write-Host "  [*] Mengunduh installer resmi Python 3.12.8 langsung dari python.org..." -ForegroundColor Cyan
    $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
    $tmpInstaller = Join-Path $env:TEMP "python-3.12.8-amd64-bidik.exe"

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $pyUrl -OutFile $tmpInstaller -UseBasicParsing

    Write-Host "  [*] Memasang Python 3.12 (User Mode + Auto PATH, mohon tunggu sekitar 1 menit)..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $tmpInstaller -ArgumentList "/passive InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait -PassThru
    Remove-Item -Force $tmpInstaller -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        throw "Installer Python selesai dengan kode status $($proc.ExitCode)."
    }

    return (Find-ValidPython)
}

# 1. Cek instalasi Python (dan tawarkan auto-install jika belum ada!)
$pyInfo = Find-ValidPython
if (-not $pyInfo) {
    $pyInfo = Install-PythonAutomatically
}

if (-not $pyInfo) {
    Write-Host "  [X] Python belum berhasil dideteksi setelah instalasi. Silakan tutup dan jalankan ulang install.bat." -ForegroundColor Red
    Read-Host "  Tekan Enter untuk menutup"
    exit 1
}

Write-Host "  [OK] Python $($pyInfo.Version) siap digunakan ($($pyInfo.Exe))" -ForegroundColor Green

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
    foreach ($optFile in @("README.md", "install.bat", "install.ps1", "uninstall.bat")) {
        $srcFile = Join-Path $sourceDir $optFile
        if (Test-Path $srcFile) {
            Copy-Item -Force $srcFile $installDir
        }
    }
    if (Test-Path (Join-Path $sourceDir "assets")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $installDir "assets") | Out-Null
        Copy-Item -Force (Join-Path $sourceDir "assets\*") (Join-Path $installDir "assets")
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
    $pyExe = $pyInfo.Exe
    $pyArgs = @() + $pyInfo.PrefixArgs + @("-m", "venv", $venvDir)
    & $pyExe @pyArgs
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
