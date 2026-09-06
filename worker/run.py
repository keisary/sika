"""Worker planifié (processus séparé sur Render) — REQ-F-BIL-003, REQ-F-NOT-002/005.

Tâches :
1. Relance des notifications PENDING (politique 3 tentatives — REQ-F-NOT-005) ;
2. Récapitulatif de fin de journée (opt-in + activité) — une fois par jour ;
3. Recensement (log uniquement, aucun envoi auto) des dettes éligibles à relance —
   l'envoi exige la validation de l'utilisatrice (REQ-AI-006).
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

from app.core.db import SessionLocal, utcnow
from app.services import notifications as notif_svc
from app.services.dettes import dettes_echues_relançables
from app.models import Compte

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sika.worker")

ETAT_FICHIER = os.environ.get("SIKA_WORKER_STATE", ".worker_state.json")
HEURE_RECAP = int(os.environ.get("SIKA_RECAP_HOUR", "17"))  # UTC


def _lire_etat() -> dict:
    try:
        with open(ETAT_FICHIER, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _ecrire_etat(etat: dict) -> None:
    with open(ETAT_FICHIER, "w", encoding="utf-8") as f:
        json.dump(etat, f)


def tour(etat: dict) -> dict:
    db = SessionLocal()
    try:
        notif_svc.relancer_pending(db)
        db.commit()

        maintenant = utcnow()
        jour = maintenant.date().isoformat()
        if maintenant.hour == HEURE_RECAP and etat.get("dernier_recap") != jour:
            envoyes = notif_svc.recap_fin_journee(db)
            db.commit()
            etat["dernier_recap"] = jour
            logger.info("recap fin de journée : %s envoi(s)", envoyes)

        for compte in db.execute(db.query(Compte).statement).scalars():
            candidates = dettes_echues_relançables(db, compte.id)
            if candidates:
                logger.info(
                    "compte %s : %s dette(s) client éligible(s) à relance (validation utilisatrice requise)",
                    compte.id, len(candidates),
                )
        db.commit()
    finally:
        db.close()
    return etat


def main() -> None:
    logger.info("worker Sika démarré (recap à %s h UTC)", HEURE_RECAP)
    etat = _lire_etat()
    while True:
        try:
            etat = tour(etat)
            _ecrire_etat(etat)
        except Exception:  # noqa: BLE001 — le worker ne doit pas mourir
            logger.exception("erreur pendant un tour")
        time.sleep(45)


if __name__ == "__main__":
    main()
