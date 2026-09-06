"""Seed — crée le compte démo (et, avec --sample, quelques écritures d'exemple).

Usage : python -m app.seed [--sample]
"""
import argparse
import sys

from app.core.db import SessionLocal
from app.core.config import settings
from app.services import comptes as comptes_svc
from app.services.ecritures import confirmer_ecriture, proposer_ecriture
from app.services.epargne import creer_objectif, epargner

TELEPHONE_DEMO = "+22890000000"


def seed(avec_exemple: bool = False) -> str:
    db = SessionLocal()
    try:
        try:
            compte = comptes_svc.creer_compte(
                db, prenom="Aïcha", telephone=TELEPHONE_DEMO,
                langue="fr", pin=settings.sika_seed_pin,
            )
            db.commit()
            print(f"Compte démo créé : {compte.prenom} <{TELEPHONE_DEMO}> (PIN {settings.sika_seed_pin})")
        except ValueError as e:
            db.rollback()
            compte = comptes_svc.authentifier(db, TELEPHONE_DEMO, settings.sika_seed_pin)
            print(f"Compte démo existant ({e}).")
        if avec_exemple:
            _exemples(db, compte.id)
        return compte.id
    finally:
        db.close()


def _exemples(db, compte_id: str) -> None:
    from datetime import timedelta
    from app.core.db import utcnow

    exemples = [
        ("VENTE", 50000, "Exemple : 20 sachets d'eau", 0),
        ("VENTE", 12500, "Exemple : 5 kilos de tomates", 0),
        ("DEPENSE", 6000, "Exemple : transport marchandise", 0),
        ("VENTE", 30000, "Exemple : vente à crédit (Koffi)", 1),
    ]
    for type_, cents, libelle, _ in exemples:
        e = proposer_ecriture(db, compte_id=compte_id, type_=type_, montant_cents=cents,
                              libelle=libelle, canal="WEB",
                              date_ecriture=utcnow() - timedelta(hours=1))
        confirmer_ecriture(db, compte_id=compte_id, ecriture_id=e.id)
    obj = creer_objectif(db, compte_id=compte_id, nom="Réassort", cible_cents=100000,
                         regle_montant_cents=1000, regle_frequence="QUOTIDIEN")
    epargner(db, compte_id=compte_id, objectif_id=obj.id, montant_cents=5000, canal="WEB")
    db.commit()
    print("Écritures d'exemple ajoutées.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="ajoute des écritures d'exemple")
    args = parser.parse_args()
    sys.exit(seed(avec_exemple=args.sample))
