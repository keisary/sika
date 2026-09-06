"""Point d'entrée FastAPI — Sika API."""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import compte as compte_api
from .api import donnees as donnees_api
from .api import tools as tools_api
from .api import voix as voix_api
from .core.config import settings
from .core.ratelimit import RateLimitMiddleware

logger = logging.getLogger("sika.main")


def _scheduler_loop() -> None:
    """Recaps fin de journée + relances PENDING + purge PROVISOIRE (si SIKA_RUN_SCHEDULER=1)."""
    from worker.run import _ecrire_etat, _lire_etat, tour

    logger.info("scheduler in-process démarré (tour toutes les 60 s)")
    etat = _lire_etat()
    while True:
        try:
            etat = tour(etat)
            _ecrire_etat(etat)
        except Exception:  # noqa: BLE001
            logger.exception("erreur scheduler")
        time.sleep(60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.sika_run_scheduler:
        thread = threading.Thread(target=_scheduler_loop, daemon=True)
        thread.start()
    yield


app = FastAPI(
    title="Sika API",
    version="0.2.0",
    description="Sika — le livre de caisse qui parle. API REST (dashboard) + outils HTTP (agent vocal AssemblyAI).",
    lifespan=lifespan,
)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(compte_api.router, prefix="/api/v1")
app.include_router(donnees_api.router, prefix="/api/v1")
app.include_router(tools_api.router)  # /tools/* — appelé par l'agent AAI (REQ-IF-S-002)
app.include_router(voix_api.router)  # /voix + /api/v1/voix/token — canal vocal navigateur

_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/healthz")
def healthz():
    """Sonde de santé : vérifie aussi la base (préparation Render)."""
    from fastapi import HTTPException
    from sqlalchemy import text

    from .core.db import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"base indisponible : {exc}")
    return {"status": "ok"}


if _DIST.exists() and (_DIST / "index.html").exists():
    # Production : le dashboard React construit est servi par FastAPI.
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="dashboard")
else:
    @app.get("/")
    def racine_dev():
        return {
            "service": "Sika (mode développement — frontend non compilé)",
            "docs": "/docs",
            "sante": "/healthz",
            "voix": "/voix",
        }
