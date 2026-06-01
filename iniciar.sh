#!/bin/bash
# Nexaro — iniciar servidor
echo "📦 Instalando dependências..."
pip install -r backend/requirements.txt -q

echo "🚀 Subindo servidor em http://127.0.0.1:8000"
python -m uvicorn backend.server:app --reload --port 8000
