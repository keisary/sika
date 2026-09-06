"""Cycle de vie des écritures (C-CON-004/005, REQ-F-VEN/ACH) :
PROVISOIRE -> CONFIRMEE (confirmation) ; annulation = écriture d'ajustement.
Tous les totaux sont calculés ici, jamais par un LLM (C-CON-003, REQ-AI-001).
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import log
from ..models import Ecriture, EcritureStatut, EcritureType, Tiers
from ._util import dumps_json, flux_cents

MAX_MONTANT_CENTS = 100_000_000 * 100  # REQ-F-ACH-006 : borne de plausibilité
PLAUSIBILITE = 100_000_000  # en FCFA


def _validate_montant(type_: str, montant_cents: int) -> None:
    """Bornes communes : montant > 0 (sauf AJUSTEMENT) et plafond (REQ-F-VEN-008, ACH-006)."""
    if type_ != EcritureType.AJUSTEMENT:
        if montant_cents <= 0:
            raise ValueError("Le montant doit être strictement positif.")
    if abs(montant_cents) > PLAUSIBILITE * 100:
        raise ValueError("Montant hors borne de plausibilité.")


def proposer_ecriture(
    db: Session,
    *,
    compte_id: str,
    type_: str,
    montant_cents: int,
    libelle: str = "",
    canal: str,
    tiers_id: str | None = None,
    meta: dict | None = None,
    session_id: str | None = None,
    date_ecriture: datetime | None = None,
) -> Ecriture:
    """Crée une écriture PROVISOIRE — rien n'est définitif avant confirmation (C-CON-004)."""
    _validate_montant(type_, montant_cents)
    ecriture = Ecriture(
        compte_id=compte_id,
        type=type_,
        statut=EcritureStatut.PROVISOIRE,
        montant_cents=montant_cents,
        libelle=libelle or type_.lower(),
        canal=canal,
        tiers_id=tiers_id,
        session_id=session_id,
        date=date_ecriture or datetime.now(timezone.utc),
        lignes_json=dumps_json(meta) if meta else None,
    )
    db.add(ecriture)
    db.flush()
    return ecriture


def confirmer_ecriture(db: Session, *, compte_id: str, ecriture_id: str, acteur: str = "COMMERCANTE") -> Ecriture:
    """Confirme une écriture PROVISOIRE -> CONFIRMEE (REQ-F-AGT-004) + audit."""
    ecriture = _get_owned(db, compte_id, ecriture_id)
    if ecriture.statut != EcritureStatut.PROVISOIRE:
        raise ValueError("Seule une écriture provisoire peut être confirmée.")
    ecriture.statut = EcritureStatut.CONFIRMEE
    log(db, compte_id=compte_id, acteur=acteur, action="ECRITURE.CONFIRMER", reference=ecriture.id)
    db.flush()
    return ecriture


def annuler_ecriture(db: Session, *, compte_id: str, ecriture_id: str, acteur: str = "COMMERCANTE") -> Ecriture:
    """Annulation tracée (C-CON-005, REQ-F-VEN-006/ACH-005/AGT-009) :
    l'original passe ANNULEE et une écriture d'ajustement inverse (CONFIRMEE) est créée.
    Refus si une dette liée est active ou payée (REQ-F-DET-009).
    """
    ecriture = _get_owned(db, compte_id, ecriture_id)
    if ecriture.statut == EcritureStatut.ANNULEE:
        raise ValueError("Cette écriture est déjà annulée.")
    if ecriture.statut != EcritureStatut.CONFIRMEE:
        raise ValueError("Seule une écriture confirmée peut être annulée.")
    _check_dette_liée(db, ecriture)
    original_statut = ecriture.statut
    ecriture.statut = EcritureStatut.ANNULEE
    ajustement = Ecriture(
        compte_id=compte_id,
        type=EcritureType.AJUSTEMENT,
        statut=EcritureStatut.CONFIRMEE,
        montant_cents=-ecriture.montant_cents,
        libelle=f"Annulation de {ecriture.libelle or ecriture.type}",
        canal=ecriture.canal,
        session_id=ecriture.session_id,
        date=datetime.now(timezone.utc),
        annule_par_id=ecriture.id,
    )
    db.add(ajustement)
    log(db, compte_id=compte_id, acteur=acteur, action="ECRITURE.ANNULER", reference=ecriture.id)
    db.flush()
    return ecriture


def _check_dette_liée(db: Session, ecriture: Ecriture) -> None:
    from ..models import Dette, DetteStatut

    if ecriture.type not in (EcritureType.VENTE, EcritureType.DEPENSE):
        return
    dette = db.execute(
        select(Dette).where(Dette.ecriture_id == ecriture.id, Dette.statut != DetteStatut.ANNULEE)
    ).scalar_one_or_none()
    if dette is not None:
        raise ValueError(
            "Impossible d'annuler : une dette est liée à cette écriture. Annulez d'abord la dette "
            "(uniquement si aucun paiement n'a été reçu)."
        )


def _get_owned(db: Session, compte_id: str, ecriture_id: str) -> Ecriture:
    ecriture = db.execute(
        select(Ecriture).where(Ecriture.id == ecriture_id, Ecriture.compte_id == compte_id)
    ).scalar_one_or_none()
    if ecriture is None:
        raise ValueError("Écriture introuvable pour ce compte.")
    return ecriture


# --- Agrégats (toujours côté backend) ---

_TYPES_AGREGES = {
    EcritureType.VENTE, EcritureType.DEPENSE, EcritureType.PAIEMENT_RECU,
    EcritureType.PAIEMENT_EMIS, EcritureType.EPARGNE,
}


def totaux_periode(db: Session, compte_id: str, start: datetime, end: datetime) -> dict:
    """Agrégats de la période — REQ-F-BIL-005.

    Ne comptent QUE les écritures CONFIRMEE des types métier : les ANNULEES et
    les AJUSTEMENT (traces de registre) sont exclus — l'annulation d'une écriture
    la rend ANNULEE (donc neutralisée) et l'ajustement n'est jamais agrégé.
    """
    rows = db.execute(
        select(Ecriture.type, Ecriture.montant_cents).where(
            Ecriture.compte_id == compte_id,
            Ecriture.statut == EcritureStatut.CONFIRMEE,
            Ecriture.type.in_(tuple(_TYPES_AGREGES)),
            Ecriture.date >= start,
            Ecriture.date < end,
        )
    ).all()
    solde_signé = sum(flux_cents(t, m) for t, m in rows)
    return {
        "solde_caisse_cents": solde_signé,
        "ventes_cents": _somme_type(db, compte_id, EcritureType.VENTE, start, end),
        "depenses_cents": _somme_type(db, compte_id, EcritureType.DEPENSE, start, end)
        + _somme_type(db, compte_id, EcritureType.PAIEMENT_EMIS, start, end),
        "paiements_recus_cents": _somme_type(db, compte_id, EcritureType.PAIEMENT_RECU, start, end),
        "epargne_cents": _somme_type(db, compte_id, EcritureType.EPARGNE, start, end),
        "nb_ecritures": len(rows),
    }


def _somme_type(db: Session, compte_id: str, type_: str, start: datetime, end: datetime) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(Ecriture.montant_cents), 0)).where(
            Ecriture.compte_id == compte_id,
            Ecriture.statut == EcritureStatut.CONFIRMEE,
            Ecriture.type == type_,
            Ecriture.date >= start,
            Ecriture.date < end,
        )
    ).scalar_one()
    return int(total)
