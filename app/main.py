"""Point d'entrée FastAPI — Sika API."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import compte as compte_api
from .api import donnees as donnees_api
from .api import tools as tools_api
from .api import voix as voix_api
from .core.config import settings

app = FastAPI(
    title="Sika API",
    version="0.1.0",
    description="Sika — le livre de caisse qui parle. API REST (dashboard) + outils HTTP (agent vocal AssemblyAI).",
)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compte_api.router, prefix="/api/v1")
app.include_router(donnees_api.router, prefix="/api/v1")
app.include_router(tools_api.router)  # /tools/* — appelé par l'agent AAI (REQ-IF-S-002)
app.include_router(voix_api.router)  # /voix + /api/v1/voix/token — canal vocal navigateur


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def racine():
    return {"service": "Sika", "docs": "/docs", "sante": "/healthz"}
