"""
Nexaro — Servidor Python para o site "Sobre Nós"
Serve o index.html e expõe um endpoint de contato simples.
"""
import os
import sqlite3
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict
import time

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from dotenv import load_dotenv

# ── Config ──────────────────────────────────────────────
BACKEND_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR   = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR  = os.path.join(PROJECT_DIR, "frontend")
DB_PATH       = os.path.join(BACKEND_DIR, "nexaro.db")

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASS     = os.getenv("SMTP_PASS", "")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO", SMTP_USER)
ADMIN_KEY     = os.getenv("ADMIN_API_KEY", "troque-esta-chave")

# ── Rate limit ─────────────────────────────────────────
_rate_store: dict = defaultdict(list)
_rate_lock = threading.Lock()

def check_rate_limit(ip: str, max_req=5, window=900) -> bool:
    now = time.time()
    with _rate_lock:
        ts = [t for t in _rate_store[ip] if now - t < window]
        if len(ts) >= max_req:
            return False
        ts.append(now)
        _rate_store[ip] = ts
    return True

# ── Banco ──────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contatos (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nome      TEXT NOT NULL,
                email     TEXT NOT NULL,
                mensagem  TEXT,
                ip        TEXT,
                criado_em TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()

# ── Lifespan ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("\n✅  Nexaro — servidor rodando!")
    print(f"   → Abra: http://127.0.0.1:8000\n")
    yield

# ── App ────────────────────────────────────────────────
app = FastAPI(title="Nexaro", lifespan=lifespan, docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Serve arquivos estáticos (css, imagens etc. se houver)
static_dir = os.path.join(FRONTEND_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ── Schemas ────────────────────────────────────────────
class Contato(BaseModel):
    nome    : str
    email   : EmailStr
    mensagem: str = ""

    @field_validator("nome")
    @classmethod
    def nome_ok(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Nome obrigatório")
        return v[:120]

    @field_validator("mensagem", mode="before")
    @classmethod
    def msg_ok(cls, v):
        return (v or "")[:2000].strip()

# ── E-mail ─────────────────────────────────────────────
def enviar_emails(c: Contato, ip: str):
    if not SMTP_HOST:
        print(f"[CONTATO] Novo: {c.nome} <{c.email}> — SMTP não configurado, e-mail ignorado.")
        return
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)

            # Interno
            m = MIMEMultipart("alternative")
            m["Subject"] = f"[Nexaro Site] Contato de {c.nome}"
            m["From"] = SMTP_USER; m["To"] = EMAIL_DESTINO
            m.attach(MIMEText(f"""
            <h2 style="font-family:sans-serif">Novo contato via site</h2>
            <p><b>Nome:</b> {c.nome}</p>
            <p><b>E-mail:</b> {c.email}</p>
            <p><b>Mensagem:</b> {c.mensagem or '—'}</p>
            <p style="color:#999;font-size:12px">IP: {ip}</p>
            """, "html"))
            s.sendmail(SMTP_USER, EMAIL_DESTINO, m.as_string())

            # Cliente
            mc = MIMEMultipart("alternative")
            mc["Subject"] = "Recebemos seu contato — Nexaro"
            mc["From"] = SMTP_USER; mc["To"] = c.email
            mc.attach(MIMEText(f"""
            <div style="font-family:sans-serif;max-width:500px;color:#0A1628">
              <h2 style="font-weight:300">Olá, {c.nome} 👋</h2>
              <p style="color:#4A5A72;line-height:1.7">
                Recebemos sua mensagem e retornaremos em breve.<br>
                Se precisar falar mais rápido:
                <a href="https://wa.me/5592984984242" style="color:#1B4FD8">WhatsApp</a>.
              </p>
              <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
              <p style="font-size:12px;color:#999">Nexaro · nexarodev1@gmail.com</p>
            </div>
            """, "html"))
            s.sendmail(SMTP_USER, c.email, mc.as_string())
    except Exception as e:
        print(f"[EMAIL] Falha: {e}")

# ── Rotas ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(FRONTEND_DIR, "index.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/api/contato")
async def contato(body: Contato, request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host)
    if not check_rate_limit(ip):
        raise HTTPException(429, "Muitas tentativas. Aguarde 15 minutos.")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO contatos (nome, email, mensagem, ip) VALUES (?,?,?,?)",
            (body.nome, body.email, body.mensagem, ip)
        )
        conn.commit()

    threading.Thread(target=enviar_emails, args=(body, ip), daemon=True).start()
    return {"ok": True, "mensagem": "Mensagem recebida!"}

@app.get("/api/contatos")
async def listar(request: Request):
    key = request.headers.get("x-api-key", "")
    if key != ADMIN_KEY:
        raise HTTPException(401, "Não autorizado.")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM contatos ORDER BY criado_em DESC").fetchall()
    return {"ok": True, "total": len(rows), "contatos": [dict(r) for r in rows]}

@app.get("/api/health")
async def health():
    return {"ok": True, "ts": datetime.now().isoformat()}
