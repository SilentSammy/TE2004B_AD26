@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update-desktop-repo.ps1"
if errorlevel 1 pause
