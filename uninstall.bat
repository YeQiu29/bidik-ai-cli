@echo off
title Uninstall Bidik CLI
echo.
echo  ======================================================
echo            UNINSTALL BIDIK CLI (BERSIH AMAN)
echo  ======================================================
echo.
set /p CONFIRM="Apakah Anda yakin ingin menghapus Bidik CLI dari laptop ini? (Y/N): "
if /I not "%CONFIRM%"=="Y" (
    echo Dibatal. Tidak ada yang dihapus.
    pause
    exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$binDir = Join-Path $HOME '.bidik\bin'; " ^
  "$userPath = [Environment]::GetEnvironmentVariable('Path', 'User'); " ^
  "if ($userPath) { " ^
  "  $cleaned = ($userPath -split ';' | Where-Object { $_ -and ($_ -ne $binDir) }) -join ';'; " ^
  "  [Environment]::SetEnvironmentVariable('Path', $cleaned, 'User'); " ^
  "} " ^
  "if (Test-Path $binDir) { Remove-Item -Recurse -Force $binDir } " ^
  "$installDir = Join-Path $HOME '.bidik-cli'; " ^
  "if (Test-Path $installDir) { Remove-Item -Recurse -Force $installDir } " ^
  "Write-Host '  [OK] Bidik CLI dan perintah global berhasil dihapus bersih.' -ForegroundColor Green"

echo.
pause
