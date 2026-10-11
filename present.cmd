@echo off
rem Zvalgas AI - one-click presentation (double-click): the cached demo scenes, full screen. See docs/demo.md.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo.ps1"
if errorlevel 1 pause
