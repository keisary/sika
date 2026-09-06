"""Dettes clients/fournisseurs : cycle de vie complet (REQ-F-DET, diagramme A.6)."""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.audit import log
from ..models import (
    Dette,
    DetteSens,
    DetteStatut,
    Ecriture,
    EcritureStatut,
    EcritureType,
    Relance,
    RelanceStatut,
    Tiers,
    TypeTiers,
)
from .ecritures import confirmer_ecriture, proposer_ecriture

DELAI_RELANCE_JOURS = 3  # REQ-F-DET-006 : échue depuis plus de 3 jours


def get_or_create_tiers(
    db: Session, *, compte_id: str, nom: str, telephone: str | None = None,
    type_: str = TypeTiers.CLIENT,
) -> Tiers:
    nom = nom.strip()
    tiers = db.execute(
        select(Tiers).where(
            Tiers.compte_id == compte_id, Tiers.type == type_, Tiers.nom == nom
        )
    ).scalar_one_or_none()
    if tiers is None:
        tiers = Tiers(compte_id=compte_id, nom=nom, telephone=telephone, type=type_)
        db.add(tiers)
        db.flush()
    return tiers


def creer_dette(
    db: Session,
    *,
    compte_id: str,
    sens: str,
    tiers_nom: str,
    montant_cents: int,
    echeance: date | None = None,
    ecriture: Ecriture | None = None,
    canal: str,
    acteur: str = "COMMERCANTE",
) -> Dette:
    """Crée une dette (client : on me doit / fournisseur : je dois)."""
    if montant_cents <= 0:
        raise ValueError("Le montant de la dette doit être strictement positif.")
    type_tiers = TypeTiers.CLIENT if sens == DetteSens.CLIENT else TypeTiers.FOURNISSEUR
    tiers = get_or_create_tiers(db, compte_id=compte_id, nom=tiers_nom, type_=type_tiers)
    dette = Dette(
        compte_id=compte_id,
        tiers_id=tiers.id,
        ecriture_id=ecriture.id if ecriture else None,
        sens=sens,
        montant_initial_cents=montant_cents,
        reste_du_cents=montant_cents,
        statut=DetteStatut.EN_COURS,
        echeance=echeance,
    )
    db.add(dette)
    db.flush()
    log(db, compte_id=compte_id, acteur=acteur, action="DETTE.CREER", reference=dette.id)
    return dette


def _get_dette(db: Session, compte_id: str, dette_id: str) -> Dette:
    dette = db.execute(
        select(Dette).where(Dette.id == dette_id, Dette.compte_id == compte_id)
    ).scalar_one_or_none()
    if dette is None:
        raise ValueError("Dette introuvable pour ce compte.")
    return dette


def dettes_actives(db: Session, compte_id: str, sens: str | None = None) -> list[Dette]:
    q = select(Dette).where(
        Dette.compte_id == compte_id, Dette.statut.in_(DetteStatut.ACTIVES)
    )
    if sens:
        q = q.where(Dette.sens == sens)
    q = q.order_by(Dette.cree_le)
    return list(db.execute(q).scalars())


def _appliquer_paiement(db: Session, dette: Dette, montant_cents: int) -> None:
    if montant_cents <= 0:
        raise ValueError("Le montant doit être strictement positif.")
    if montant_cents > dette.reste_du_cents:
        raise ValueError(
            f"Montant supérieur au reste dû ({dette.reste_du_cents} centimes)."
        )
    if dette.statut not in DetteStatut.ACTIVES:
        raise ValueError("Cette dette n'est pas active (payée ou annulée).")
    dette.reste_du_cents -= montant_cents
    if dette.reste_du_cents == 0:
        dette.statut = DetteStatut.PAYEE
    elif dette.statut != DetteStatut.EN_RELANCE:
        dette.statut = DetteStatut.PARTIELLE


def encaisser_dette_client(
    db: Session, *, compte_id: str, dette_id: str, montant_cents: int,
    canal: str, acteur: str = "COMMERCANTE",
) -> Ecriture:
    """Paiement reçu d'un client (REQ-F-DET-004) : écriture + recalcul du reste dû."""
    dette = _get_dette(db, compte_id, dette_id)
    if dette.sens != DetteSens.CLIENT:
        raise ValueError("Cette dette est une dette fournisseur, pas une créance client.")
    _appliquer_paiement(db, dette, montant_cents)
    ecriture = proposer_ecriture(
        db, compte_id=compte_id, type_=EcritureType.PAIEMENT_RECU,
        montant_cents=montant_cents, libelle=f"Encaissement {dette.sens} - {_tiers_nom(db, dette)}",
        canal=canal, tiers_id=dette.tiers_id,
    )
    confirmer_ecriture(db, compte_id=compte_id, ecriture_id=ecriture.id, acteur=acteur)
    log(db, compte_id=compte_id, acteur=acteur, action="DETTE.ENCAISSER", reference=dette.id)
    db.flush()
    return ecriture


def regler_dette_fournisseur(
    db: Session, *, compte_id: str, dette_id: str, montant_cents: int,
    canal: str, acteur: str = "COMMERCANTE",
) -> Ecriture:
    dette = _get_dette(db, compte_id, dette_id)
    if dette.sens != DetteSens.FOURNISSEUR:
        raise ValueError("Cette dette est une créance client, pas une dette fournisseur.")
    _appliquer_paiement(db, dette, montant_cents)
    ecriture = proposer_ecriture(
        db, compte_id=compte_id, type_=EcritureType.PAIEMENT_EMIS,
        montant_cents=montant_cents, libelle=f"Règlement fournisseur - {_tiers_nom(db, dette)}",
        canal=canal, tiers_id=dette.tiers_id,
    )
    confirmer_ecriture(db, compte_id=compte_id, ecriture_id=ecriture.id, acteur=acteur)
    log(db, compte_id=compte_id, acteur=acteur, action="DETTE.REGLER", reference=dette.id)
    db.flush()
    return ecriture


def annuler_dette(
    db: Session, *, compte_id: str, dette_id: str, acteur: str = "COMMERCANTE",
) -> Dette:
    """Annulation tracée (REQ-F-DET-008) — refus si des paiements ont déjà eu lieu."""
    dette = _get_dette(db, compte_id, dette_id)
    if dette.statut == DetteStatut.ANNULEE:
        raise ValueError("Cette dette est déjà annulée.")
    if dette.statut == DetteStatut.PAYEE:
        raise ValueError("Impossible d'annuler une dette payée.")
    if dette.reste_du_cents != dette.montant_initial_cents:
        raise ValueError("Impossible d'annuler : des paiements ont déjà été reçus sur cette dette.")
    if dette.statut == DetteStatut.EN_RELANCE:
        pass  # une dette relancée mais jamais payée reste annulable
    dette.statut = DetteStatut.ANNULEE
    log(db, compte_id=compte_id, acteur=acteur, action="DETTE.ANNULER", reference=dette.id)
    db.flush()
    return dette


def _tiers_nom(db: Session, dette: Dette) -> str:
    tiers = db.get(Tiers, dette.tiers_id)
    return tiers.nom if tiers else "?"


def dettes_echues_relançables(db: Session, compte_id: str, aujourdhui: date | None = None) -> list[Dette]:
    """Dettes client actives échues depuis > DELAI_RELANCE_JOURS (REQ-F-DET-006)."""
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    dettes = dettes_actives(db, compte_id, sens=DetteSens.CLIENT)
    result = []
    for d in dettes:
        reference = d.echeance or d.cree_le.date()
        if (aujourdhui - reference).days > DELAI_RELANCE_JOURS:
            result.append(d)
    return result


def envoyer_relance(
    db: Session, *, compte_id: str, dette_id: str, message: str,
    acteur: str = "COMMERCANTE",
) -> Relance:
    """Envoi d'une relance validée par l'utilisatrice (REQ-F-DET-006/007, REQ-AI-006)."""
    dette = _get_dette(db, compte_id, dette_id)
    if dette.sens != DetteSens.CLIENT:
        raise ValueError("On ne relance que les clients débiteurs.")
    relance = Relance(compte_id=compte_id, dette_id=dette.id, message=message)
    db.add(relance)
    db.flush()
    if dette.statut in DetteStatut.ACTIVES:
        dette.statut = DetteStatut.EN_RELANCE
    log(db, compte_id=compte_id, acteur=acteur, action="DETTE.RELANCER", reference=dette.id)
    db.flush()
    return relance
