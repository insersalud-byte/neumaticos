@echo off
cd /d "%~dp0backend"
title Giorda Neumaticos
echo Iniciando servidor...
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
