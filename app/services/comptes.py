"""Comptes, authentification PIN, consentements (REQ-F-CMP)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.audit import log
from ..core.security import hash_pin, verify_pin
from ..models import Compte, Consentement

LANGUES_SUPPORTEES = {"fr", "en", "pt", "es"}  # C-CON-009 (entrée + sortie vocales natives AAI)
DEVISES_SUPPORTEES = {"XOF"}


def creer_compte(
    db: Session, *, prenom: str, telephone: str, langue: str = "fr",
    devise: str = "XOF", pin: str,
) -> Compte:
    prenom = prenom.strip()
    telephone = telephone.strip()
    if not prenom or not telephone:
        raise ValueError("Prénom et téléphone requis.")
    if langue not in LANGUES_SUPPORTEES:
        raise ValueError(f"Langue non supportée ({sorted(LANGUES_SUPPORTEES)}).")
    if devise not in DEVISES_SUPPORTEES:
        raise ValueError("Devise non supportée en V1 (XOF uniquement).")
    if not (4 <= len(pin) <= 6) or not pin.isdigit():
        raise ValueError("Le PIN doit contenir 4 à 6 chiffres.")
    existant = db.execute(
        select(Compte).where(Compte.telephone == telephone)
    ).scalar_one_or_none()
    if existant is not None:
        raise ValueError("Un compte existe déjà avec ce numéro de téléphone.")
    compte = Compte(
        prenom=prenom, telephone=telephone, langue=langue, devise=devise,
        pin_hash=hash_pin(pin),
    )
    db.add(compte)
    db.flush()
    log(db, compte_id=compte.id, acteur="SYSTEME", action="COMPTE.CREER", reference=compte.id)
    return compte


def authentifier(db: Session, telephone: str, pin: str) -> Compte | None:
    compte = db.execute(
        select(Compte).where(Compte.telephone == telephone.strip())
    ).scalar_one_or_none()
    if compte is None or not verify_pin(pin, compte.pin_hash):
        return None
    return compte


def changer_langue(db: Session, compte_id: str, langue: str) -> Compte:
    if langue not in LANGUES_SUPPORTEES:
        raise ValueError(f"Langue non supportée ({sorted(LANGUES_SUPPORTEES)}).")
    compte = db.get(Compte, compte_id)
    compte.langue = langue
    db.flush()
    return compte


def enregistrer_consentement(db: Session, compte_id: str, perimetre: str, canal: str) -> None:
    db.add(Consentement(compte_id=compte_id, perimetre=perimetre, canal=canal))
    db.flush()


def effacer_compte(db: Session, compte_id: str) -> None:
    """Droit à l'effacement (REQ-F-CMP-004, REQ-DB-009) — suppression complète du tenant."""
    from ..models import (
        Consentement, Dette, DossierCredit, Ecriture, EntreeAudit, Notification,
        ObjectifEpargne, Produit, Relance, SessionVocale, Tiers,
    )
    tables = [
        Consentement, Produit, Tiers, ObjectifEpargne, Notification,
        DossierCredit, SessionVocale, Relance, Dette, Ecriture, EntreeAudit,
    ]
    for table in tables:
        db.execute(table.__table__.delete().where(table.compte_id == compte_id))
    compte = db.get(Compte, compte_id)
    if compte is not None:
        db.delete(compte)
    db.flush()
