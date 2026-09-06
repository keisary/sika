"""Bilans parlés / écrits (REQ-F-BIL) — agrégats calculés côté backend."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import DetteSens, Ecriture, EcritureStatut
from ._util import day_range, fmt_fcfa
from .dettes import dettes_actives
from .ecritures import totaux_periode


def bilan_periode(db: Session, compte_id: str, debut: datetime, fin: datetime) -> dict:
    tot = totaux_periode(db, compte_id, debut, fin)
    clients = dettes_actives(db, compte_id, sens=DetteSens.CLIENT)
    fournisseurs = dettes_actives(db, compte_id, sens=DetteSens.FOURNISSEUR)
    # jours avec activité sur la période (régularité)
    jours_actifs = len(
        set(
            db.execute(
                Ecriture.__table__.select()
                .with_only_columns(Ecriture.date)
                .where(
                    Ecriture.compte_id == compte_id,
                    Ecriture.statut == EcritureStatut.CONFIRMEE,
                    Ecriture.date >= debut,
                    Ecriture.date < fin,
                )
            ).scalars()
        )
    ) if debut.date() != fin.date() else None
    return {
        **tot,
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "jours_actifs": jours_actifs,
        "dettes_clients_actives": {
            "nb": len(clients),
            "reste_du_cents": sum(d.reste_du_cents for d in clients),
        },
        "dettes_fournisseurs_actives": {
            "nb": len(fournisseurs),
            "reste_du_cents": sum(d.reste_du_cents for d in fournisseurs),
        },
    }


def bilan_du_jour(db: Session, compte_id: str, jour=None) -> dict:
    start, end = day_range(jour)
    return bilan_periode(db, compte_id, start, end)


_LABELS = {
    "fr": {
        "ventes": "ventes", "depenses": "dépenses", "paiements_recus": "encaissements reçus",
        "solde": "solde de caisse", "dettes_clients": "créances clients en cours",
        "dettes_fournisseurs": "dettes fournisseurs en cours", "epargne": "épargne",
        "ecritures": "opérations", "pas_activite": "aucune opération sur la période.",
    },
    "en": {
        "ventes": "sales", "depenses": "expenses", "paiements_recus": "payments received",
        "solde": "cash balance", "dettes_clients": "outstanding customer debts",
        "dettes_fournisseurs": "outstanding supplier debts", "epargne": "savings",
        "ecritures": "entries", "pas_activite": "no entries in this period.",
    },
    "pt": {
        "ventes": "vendas", "depenses": "despesas", "paiements_recus": "recebimentos",
        "solde": "saldo de caixa", "dettes_clients": "dívidas de clientes",
        "dettes_fournisseurs": "dívidas a fornecedores", "epargne": "poupança",
        "ecritures": "lançamentos", "pas_activite": "nenhum lançamento no período.",
    },
    "es": {
        "ventes": "ventas", "depenses": "gastos", "paiements_recus": "cobros recibidos",
        "solde": "saldo de caja", "dettes_clients": "deudas de clientes",
        "dettes_fournisseurs": "deudas con proveedores", "epargne": "ahorro",
        "ecritures": "anotaciones", "pas_activite": "ninguna anotación en el período.",
    },
}


def format_bilan(bilan: dict, langue: str = "fr") -> str:
    """Texte lisible (lu par l'agent ou envoyé en notification)."""
    l = _LABELS.get(langue, _LABELS["fr"])
    if bilan["nb_ecritures"] == 0:
        return l["pas_activite"]
    parts = [
        f"{l['ventes']} : {fmt_fcfa(bilan['ventes_cents'])}",
        f"{l['depenses']} : {fmt_fcfa(bilan['depenses_cents'])}",
        f"{l['paiements_recus']} : {fmt_fcfa(bilan['paiements_recus_cents'])}",
        f"{l['solde']} : {fmt_fcfa(bilan['solde_caisse_cents'])}",
    ]
    if bilan["epargne_cents"]:
        parts.append(f"{l['epargne']} : {fmt_fcfa(bilan['epargne_cents'])}")
    dc = bilan["dettes_clients_actives"]
    df = bilan["dettes_fournisseurs_actives"]
    if dc["nb"]:
        parts.append(f"{l['dettes_clients']} : {dc['nb']} ({fmt_fcfa(dc['reste_du_cents'])})")
    if df["nb"]:
        parts.append(f"{l['dettes_fournisseurs']} : {df['nb']} ({fmt_fcfa(df['reste_du_cents'])})")
    return ", ".join(parts) + "."
