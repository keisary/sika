"""Épargne programmée (REQ-F-EPG) : objectifs, règles, écritures d'épargne."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import log
from ..models import Ecriture, EcritureStatut, EcritureType, ObjectifEpargne
from .ecritures import confirmer_ecriture, proposer_ecriture


def creer_objectif(
    db: Session, *, compte_id: str, nom: str, cible_cents: int,
    regle_montant_cents: int | None = None, regle_frequence: str | None = None,
) -> ObjectifEpargne:
    if cible_cents <= 0:
        raise ValueError("La cible doit être strictement positive.")
    obj = ObjectifEpargne(
        compte_id=compte_id, nom=nom, cible_cents=cible_cents,
        regle_montant_cents=regle_montant_cents, regle_frequence=regle_frequence,
    )
    db.add(obj)
    db.flush()
    return obj


def epargner(
    db: Session, *, compte_id: str, objectif_id: str, montant_cents: int,
    canal: str, acteur: str = "COMMERCANTE",
) -> Ecriture:
    """Écriture d'épargne (sortie de caisse vers l'objectif) — REQ-F-EPG-003."""
    obj = db.execute(
        select(ObjectifEpargne).where(
            ObjectifEpargne.id == objectif_id, ObjectifEpargne.compte_id == compte_id
        )
    ).scalar_one_or_none()
    if obj is None:
        raise ValueError("Objectif d'épargne introuvable.")
    if not obj.actif:
        raise ValueError("Cet objectif d'épargne est suspendu ou clôturé.")
    ecriture = proposer_ecriture(
        db, compte_id=compte_id, type_=EcritureType.EPARGNE,
        montant_cents=montant_cents, libelle=f"Épargne - {obj.nom}", canal=canal,
    )
    confirmer_ecriture(db, compte_id=compte_id, ecriture_id=ecriture.id, acteur=acteur)
    log(db, compte_id=compte_id, acteur=acteur, action="EPARGNE.DEPOSER", reference=obj.id)
    db.flush()
    return ecriture


def progression(db: Session, compte_id: str, objectif_id: str) -> dict:
    obj = db.execute(
        select(ObjectifEpargne).where(
            ObjectifEpargne.id == objectif_id, ObjectifEpargne.compte_id == compte_id
        )
    ).scalar_one_or_none()
    if obj is None:
        raise ValueError("Objectif d'épargne introuvable.")
    ep = int(
        db.execute(
            select(func.coalesce(func.sum(Ecriture.montant_cents), 0)).where(
                Ecriture.compte_id == compte_id,
                Ecriture.statut == EcritureStatut.CONFIRMEE,
                Ecriture.type == EcritureType.EPARGNE,
            )
        ).scalar_one()
    )
    return {"objectif": obj.nom, "cible_cents": obj.cible_cents,
            "epargne_cents": ep, "reste_cents": max(obj.cible_cents - ep, 0)}


def liste_objectifs(db: Session, compte_id: str) -> list[ObjectifEpargne]:
    return list(db.execute(
        select(ObjectifEpargne).where(
            ObjectifEpargne.compte_id == compte_id, ObjectifEpargne.actif.is_(True)
        ).order_by(ObjectifEpargne.cree_le)
    ).scalars())
