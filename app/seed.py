"""Seed — compte démo + jeu de données réaliste (~3 mois) pour démo/développement.

Usage : python -m app.seed [--sample]
"""
import argparse
import sys
from datetime import timedelta

from app.core.config import settings
from app.core.db import SessionLocal, utcnow
from app.services import comptes as comptes_svc
from app.services import dettes as dettes_svc
from app.services import epargne as epargne_svc
from app.services.ecritures import confirmer_ecriture, proposer_ecriture

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


def _ecriture(db, compte_id, type_, cents, libelle, jours_avant, heures_avant=0):
    e = proposer_ecriture(
        db, compte_id=compte_id, type_=type_, montant_cents=cents, libelle=libelle,
        canal="WEB",
        date_ecriture=utcnow() - timedelta(days=jours_avant, hours=heures_avant),
    )
    confirmer_ecriture(db, compte_id=compte_id, ecriture_id=e.id)
    return e


def _exemples(db, compte_id: str) -> None:
    """~3 mois d'activité : rend le dashboard et le dossier de crédit démontrables."""
    # Aujourd'hui (bilan du jour parlant)
    _ecriture(db, compte_id, "VENTE", 40000, "Vente : 8 kilos de tomates", 0, heures_avant=5)
    _ecriture(db, compte_id, "VENTE", 22500, "Vente : 15 sachets d'arachides", 0, heures_avant=4)
    _ecriture(db, compte_id, "DEPENSE", 6000, "Transport marchandise", 0, heures_avant=3)
    _ecriture(db, compte_id, "VENTE", 30000, "Vente : 2 cartons d'huile", 0, heures_avant=1)
    # Dettes : Koffi (échue depuis 10 jours → relançable) et grossiste (à venir)
    koffi = dettes_svc.creer_dette(
        db, compte_id=compte_id, sens="CLIENT", tiers_nom="Koffi",
        montant_cents=450000, echeance=(utcnow() - timedelta(days=10)).date(), canal="WEB",
    )
    grossiste = dettes_svc.creer_dette(
        db, compte_id=compte_id, sens="FOURNISSEUR", tiers_nom="Grossiste Adjamé",
        montant_cents=1200000, echeance=(utcnow() + timedelta(days=5)).date(), canal="WEB",
    )
    # Épargne : objectif + dépôts
    obj = epargne_svc.creer_objectif(
        db, compte_id=compte_id, nom="Réassort de fin de mois", cible_cents=100000,
        regle_montant_cents=2000, regle_frequence="QUOTIDIEN",
    )
    epargne_svc.epargner(db, compte_id=compte_id, objectif_id=obj.id,
                         montant_cents=20000, canal="WEB")

    # Historique ~3 mois (pour le dossier de crédit 3 mois)
    plan = [
        # (jours_avant, type, centimes, libellé)
        (95, "VENTE", 35000, "Vente : légumes variés"),
        (92, "DEPENSE", 8000, "Réassort tomates"),
        (90, "VENTE", 22000, "Vente : 11 kilos d'oignons"),
        (88, "VENTE", 15000, "Vente : arachides"),
        (75, "VENTE", 40000, "Vente : 2 cartons d'huile"),
        (72, "DEPENSE", 10000, "Réassort huile"),
        (70, "VENTE", 28000, "Vente : légumes variés"),
        (60, "VENTE", 33000, "Vente : tomates et piments"),
        (58, "VENTE", 19000, "Vente : 19 sachets de biscuits"),
        (55, "DEPENSE", 5000, "Transport marchandise"),
        (45, "VENTE", 45000, "Vente : 3 cartons d'huile"),
        (42, "VENTE", 25000, "Vente : 10 kilos de tomates"),
        (40, "DEPENSE", 9000, "Réassort divers"),
        (35, "VENTE", 30000, "Vente : 2 cartons de savon"),
        (30, "VENTE", 21000, "Vente : 7 kilos de gombo"),
        (28, "DEPENSE", 6000, "Électricité étal (mois écoulé)"),
        (25, "VENTE", 50000, "Vente : 4 cartons d'huile"),
        (20, "VENTE", 18000, "Vente : arachides et pistaches"),
        (18, "DEPENSE", 12000, "Réassort Adjamé"),
        (15, "VENTE", 36000, "Vente : légumes variés"),
        (12, "VENTE", 27000, "Vente : 9 kilos d'oignons"),
        (10, "DEPENSE", 7000, "Réassort tomates"),
        (8, "VENTE", 42000, "Vente : 2 cartons d'huile + savon"),
        (6, "VENTE", 23000, "Vente : 23 sachets de bonbons"),
        (4, "DEPENSE", 5500, "Transport marchandise"),
        (2, "VENTE", 31000, "Vente : 2 cartons de concentré"),
    ]
    for jours, type_, cents, libelle in plan:
        _ecriture(db, compte_id, type_, cents, libelle, jours)

    epargne_svc.epargner(db, compte_id=compte_id, objectif_id=obj.id,
                         montant_cents=10000, canal="WEB")
    db.commit()
    print(
        f"Jeu de données ajouté : {len(plan) + 4} écritures, dette Koffi (relançable : {koffi.id[:8]}), "
        f"dette fournisseur {grossiste.id[:8]}, objectif épargne {obj.id[:8]}."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="ajoute le jeu de données de démo")
    args = parser.parse_args()
    sys.exit(seed(avec_exemple=args.sample))
