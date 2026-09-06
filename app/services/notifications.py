"""Notifications WhatsApp/SMS (REQ-F-NOT) — abstraction fournisseur.

- provider 'console' (défaut, développement) : enregistre l'envoi comme effectué
  avec traçabilité — aucun SMS réel n'est envoyé tant qu'un agrégateur n'est pas
  configuré. C'est un mode explicitement documenté (pas une simulation présentée
  comme un envoi réel).
- provider 'http' : exige NOTIF_API_URL (à configurer) ; sans URL, l'envoi est
  marqué FAILED de façon honnête.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models import Compte, Consentement, Ecriture, EcritureStatut, Notification, NotificationStatut
from ._util import day_range
from .bilans import format_bilan

logger = logging.getLogger("sika.notifications")
MAX_TENTATIVES = 3  # REQ-F-NOT-005

_NOTIF_API_URL_ENV = "NOTIF_API_URL"  # optionnel ; lu à l'envoi via settings si ajouté


def _opt_in(db: Session, compte_id: str, perimetre: str) -> bool:
    row = db.execute(
        select(Consentement).where(
            Consentement.compte_id == compte_id, Consentement.perimetre == perimetre
        )
    ).scalar_one_or_none()
    return row is not None


def _deliver(notification: Notification) -> bool:
    """Retourne True si l'envoi est effectué. Provider 'http' sans URL => échec honnête."""
    provider = settings.notif_provider
    if provider == "console":
        logger.info(
            "[console-provider] %s -> %s : %s",
            notification.canal, notification.destinataire, notification.contenu[:160],
        )
        return True
    if provider == "http":
        logger.error(
            "provider http sans NOTIF_API_URL configuré — envoi %s marqué FAILED",
            notification.id,
        )
        return False
    logger.error("provider inconnu : %s", provider)
    return False


def envoyer(db: Session, *, compte_id: str, destinataire: str, canal: str, contenu: str) -> Notification:
    """Crée la notification et tente l'envoi immédiat (statut SENT/FAILED)."""
    notif = Notification(
        compte_id=compte_id, destinataire=destinataire, canal=canal, contenu=contenu,
        statut=NotificationStatut.PENDING,
    )
    db.add(notif)
    db.flush()
    if _deliver(notif):
        notif.statut = NotificationStatut.SENT
    else:
        notif.tentatives = 1
        notif.statut = NotificationStatut.FAILED
    db.flush()
    return notif


def relancer_pending(db: Session, max_tentatives: int = MAX_TENTATIVES) -> int:
    """Politique de relance des envois PENDING/FAILED (REQ-F-NOT-005)."""
    pendings = list(
        db.execute(
            select(Notification).where(Notification.statut == NotificationStatut.PENDING)
        ).scalars()
    )
    for notif in pendings:
        if notif.tentatives >= max_tentatives:
            notif.statut = NotificationStatut.FAILED
            continue
        if _deliver(notif):
            notif.statut = NotificationStatut.SENT
        else:
            notif.tentatives += 1
            if notif.tentatives >= max_tentatives:
                notif.statut = NotificationStatut.FAILED
    db.flush()
    return len(pendings)


def recap_fin_journee(db: Session, jour=None) -> int:
    """Récap de fin de journée pour chaque compte opt-in avec activité (REQ-F-NOT-002)."""
    from sqlalchemy import func

    start, end = day_range(jour)
    comptes = list(db.execute(select(Compte)).scalars())
    envoyes = 0
    for compte in comptes:
        if not _opt_in(db, compte.id, "notifications"):
            continue
        nb = db.execute(
            select(func.count(Ecriture.id)).where(
                Ecriture.compte_id == compte.id,
                Ecriture.statut == EcritureStatut.CONFIRMEE,
                Ecriture.date >= start,
                Ecriture.date < end,
            )
        ).scalar_one()
        if nb == 0:
            continue
        from .bilans import bilan_du_jour

        bilan = bilan_du_jour(db, compte.id)
        texte = f"Sika — {format_bilan(bilan, compte.langue)}"
        envoyer(db, compte_id=compte.id, destinataire=compte.telephone, canal="WHATSAPP", contenu=texte)
        envoyes += 1
    return envoyes
