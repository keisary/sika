"""Utilitaires métier : formatage monétaire (C-CON-001/002), signes de flux."""
import json
from datetime import date, datetime, time, timedelta, timezone

from app.models import EcritureType


def fmt_fcfa(cents: int) -> str:
    """'1234567' -> '12 345 FCFA' (affichage, centimes d'abord divisés)."""
    if cents is None:
        return "0 FCFA"
    amount = abs(cents) // 100
    grouped = f"{amount:,}".replace(",", " ")
    return f"{grouped} FCFA"


def flux_cents(ecriture_type: str, montant_cents: int) -> int:
    """Signe du flux de caisse selon le type.

    AJUSTEMENT porte déjà son signe (montant négatif pour inverser l'original).
    Les autres types ont un signe fixe : entrées (+) / sorties (-).
    """
    if ecriture_type == EcritureType.AJUSTEMENT:
        return montant_cents
    return montant_cents if ecriture_type in {
        EcritureType.VENTE, EcritureType.PAIEMENT_RECU,
    } else -montant_cents


def dumps_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def day_start(dt: datetime | None = None) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    return datetime.combine(dt.date(), time.min, tzinfo=timezone.utc)


def day_range(day: date | None = None):
    day = day or datetime.now(timezone.utc).date()
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def month_bounds(months_back: int, today: date | None = None) -> tuple[date, date]:
    """[début, fin] d'une fenêtre glissante de N mois finissant aujourd'hui."""
    today = today or datetime.now(timezone.utc).date()
    first = today.replace(day=1)
    for _ in range(months_back - 1):
        first = (first.replace(day=1) - timedelta(days=1)).replace(day=1)
    return first, today
