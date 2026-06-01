@echo off
echo Instalando dependencias...
pip install -r backend\requirements.txt -q
echo.
echo Servidor rodando em http://127.0.0.1:8000
python -m uvicorn backend.server:app --reload --port 8000
pause
