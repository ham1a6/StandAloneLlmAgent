@echo off
set PYTHONPATH=%~dp0;%PYTHONPATH%
"%~dp0.venv\Scripts\python.exe" -m cli.app %*
