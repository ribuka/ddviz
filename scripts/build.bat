@echo off
cd /d %~dp0..
set script=packaging/build.py
uv run --group build %script%
pause
