@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0amadeus.ps1" %*
exit /b %ERRORLEVEL%
