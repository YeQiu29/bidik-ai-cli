@echo off
title Installer Bidik CLI
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Instalasi berhenti dengan kode error %ERRORLEVEL%.
    pause
)
