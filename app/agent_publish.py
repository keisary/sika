"""Publication / mise à jour de l'agent vocal sur le compte AssemblyAI.

Usage :
    python -m app.agent_publish --url https://votre-app.onrender.com

- Lit agent/sika.agent.jsonc, substitue ${SIKA_TOOLS_URL} et ${SIKA_TOOL_TOKEN} ;
- Le jeton d'outil est un jeton applicatif Sika du compte démo (90 jours) —
  il est stocké dans .agent_tool_token (jamais commité) ;
- POST /v1/agents pour créer, PUT /v1/agents/{id} si .agent_id existe (mise à jour) ;
- Sauvegarde l'identifiant d'agent dans .agent_id.
"""
import argparse
import os
import sys

import httpx

from app.core.db import SessionLocal
from app.core.security import new_access_token
from app.models import Compte
from app.seed import TELEPHONE_DEMO

AGENTS_API = "https://agents.assemblyai.com/v1"
AGENT_ID_FICHIER = ".agent_id"
TOKEN_FICHIER = ".agent_tool_token"
TTL_JETON = 90 * 24 * 3600


def _charger_template() -> str:
    chemin = os.path.join(os.path.dirname(__file__), "..", "agent", "sika.agent.jsonc")
    with open(os.path.normpath(chemin), encoding="utf-8") as f:
        return f.read()


def _jeton_outil() -> str:
    db = SessionLocal()
    try:
        compte = db.execute(
            db.query(Compte).filter(Compte.telephone == TELEPHONE_DEMO).statement
        ).scalar_one_or_none()
        if compte is None:
            sys.exit("Compte démo absent — lancez d'abord : python -m app.seed")
        jeton = new_access_token(compte.id, ttl=TTL_JETON)
        with open(TOKEN_FICHIER, "w", encoding="utf-8") as f:
            f.write(jeton)
        return jeton
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="URL publique du backend Sika (ex. https://sika.onrender.com)")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    from app.core.config import settings

    if not settings.assemblyai_api_key:
        sys.exit("ASSEMBLYAI_API_KEY non définie (fichier .env ou variable d'environnement).")

    jeton = _jeton_outil()
    template = _charger_template()
    body = template.replace("${SIKA_TOOLS_URL}", base).replace("${SIKA_TOOL_TOKEN}", jeton)
    import json as _json

    payload = _json.loads(body)  # jsonc sans commentaires restants -> JSON strict

    headers = {"Authorization": settings.assemblyai_api_key, "Content-Type": "application/json"}
    agent_id = None
    if os.path.exists(AGENT_ID_FICHIER):
        agent_id = open(AGENT_ID_FICHIER, encoding="utf-8").read().strip()

    with httpx.Client(timeout=60) as client:
        if agent_id:
            resp = client.put(f"{AGENTS_API}/agents/{agent_id}", headers=headers, json=payload)
            action = "mise à jour"
        else:
            resp = client.post(f"{AGENTS_API}/agents", headers=headers, json=payload)
            action = "création"
        if resp.status_code >= 400:
            sys.exit(f"Échec ({action}) : {resp.status_code} {resp.text[:500]}")
        data = resp.json()
        agent_id = data.get("id") or agent_id
        with open(AGENT_ID_FICHIER, "w", encoding="utf-8") as f:
            f.write(agent_id)
        print(f"Agent Sika {action} réussie : {agent_id}")
        print(f"Variables à configurer : SIKA_AGENT_ID={agent_id} (côté Render)")


if __name__ == "__main__":
    main()
