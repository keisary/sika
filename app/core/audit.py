"""Journal d'audit — append-only via l'API applicative (REQ-NF-SEC-007/008)."""
from sqlalchemy.orm import Session

from ..models import EntreeAudit


def log(db: Session, *, compte_id: str | None, acteur: str, action: str, reference: str = "") -> None:
    """Ajoute une entrée d'audit. Aucune route ne permet de modifier/supprimer ces entrées."""
    db.add(EntreeAudit(compte_id=compte_id, acteur=acteur, action=action, reference=reference))
