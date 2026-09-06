"""Dossier de crédit « historique bancable » (REQ-F-CRD) — période glissante 3/6 mois."""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import log
from ..models import Dette, DetteStatut, DossierCredit, Ecriture, EcritureStatut
from ._util import dumps_json, fmt_fcfa, month_bounds
from .bilans import bilan_periode

MOIS_POSSIBLES = (3, 6)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _synthese_mensuelle(db: Session, compte_id: str, debut: datetime, fin_excl: datetime) -> dict:
    b = bilan_periode(db, compte_id, debut, fin_excl)
    return {
        "mois": debut.strftime("%Y-%m"),
        "ventes_cents": b["ventes_cents"],
        "depenses_cents": b["depenses_cents"],
        "solde_cents": b["solde_caisse_cents"],
        "nb_ecritures": b["nb_ecritures"],
    }


def _jours_actifs(db: Session, compte_id: str, debut: datetime, fin_excl: datetime) -> int:
    rows = db.execute(
        select(func.date(Ecriture.date)).where(
            Ecriture.compte_id == compte_id,
            Ecriture.statut == EcritureStatut.CONFIRMEE,
            Ecriture.date >= debut,
            Ecriture.date < fin_excl,
        )
    ).all()
    return len({r[0] for r in rows})


def generer_dossier(
    db: Session, *, compte_id: str, mois: int, canal: str, acteur: str = "COMMERCANTE",
) -> dict:
    """Génère le dossier, le persiste (traçabilité REQ-F-CRD-005) et le retourne."""
    if mois not in MOIS_POSSIBLES:
        raise ValueError("Période non supportée : choisir 3 ou 6 mois.")
    debut_date, fin_date = month_bounds(mois)
    debut = datetime.combine(debut_date, time.min, tzinfo=timezone.utc)
    fin_excl = datetime.combine(fin_date + timedelta(days=1), time.min, tzinfo=timezone.utc)

    mensuel = []
    cursor = debut_date
    while cursor <= fin_date:
        nxt = _next_month(cursor)
        fin_mois_excl = datetime.combine(min(nxt, fin_date + timedelta(days=1)), time.min, tzinfo=timezone.utc)
        mensuel.append(_synthese_mensuelle(db, compte_id, debut=datetime.combine(cursor, time.min, tzinfo=timezone.utc), fin_excl=fin_mois_excl))
        cursor = nxt

    jours_actifs = _jours_actifs(db, compte_id, debut, fin_excl)
    total_jours = (fin_date - debut_date).days + 1
    epargne = int(
        db.execute(
            select(func.coalesce(func.sum(Ecriture.montant_cents), 0)).where(
                Ecriture.compte_id == compte_id,
                Ecriture.statut == EcritureStatut.CONFIRMEE,
                Ecriture.type == "EPARGNE",
            )
        ).scalar_one()
    )
    dettes = list(
        db.execute(
            select(Dette).where(
                Dette.compte_id == compte_id,
                Dette.statut.in_(
                    (DetteStatut.EN_COURS, DetteStatut.PARTIELLE, DetteStatut.EN_RELANCE)
                ),
            )
        ).scalars()
    )

    dossier = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "periode": {"debut": debut_date.isoformat(), "fin": fin_date.isoformat(), "mois": mois},
        "synthese_mensuelle": mensuel,
        "regularite": {
            "jours_actifs": jours_actifs,
            "jours_couverts": total_jours,
            "taux": round(jours_actifs / total_jours, 3) if total_jours else 0,
        },
        "epargne_cents": epargne,
        "dettes_actives": [
            {"sens": d.sens, "reste_du_cents": d.reste_du_cents} for d in dettes
        ],
        "note_lecture": (
            "Ce dossier est généré par Sika à partir des opérations déclarées oralement par "
            "l'utilisatrice. Il documente l'activité, le cash-flow et la régularité ; il ne "
            "constitue ni un état financier certifié, ni un avis d'octroi."
        ),
    }
    row = DossierCredit(
        compte_id=compte_id,
        debut_periode=debut_date,
        fin_periode=fin_date,
        canal=canal,
        contenu_json=dumps_json(dossier),
    )
    db.add(row)
    db.flush()
    log(db, compte_id=compte_id, acteur=acteur, action="DOSSIER_CREDIT.GENERER", reference=row.id)
    return dossier


def render_markdown(dossier: dict) -> str:
    lignes = [
        "# Dossier de crédit — Sika",
        "",
        f"- Généré le : {dossier['genere_le'][:10]}",
        f"- Période : {dossier['periode']['debut']} → {dossier['periode']['fin']}",
        f"- Régularité : {dossier['regularite']['jours_actifs']}/{dossier['regularite']['jours_couverts']} jours actifs "
        f"({dossier['regularite']['taux'] * 100:.0f} %)",
        f"- Épargne cumulée : {fmt_fcfa(dossier['epargne_cents'])}",
        "",
        "## Activité mensuelle",
        "",
        "| Mois | Ventes | Dépenses | Solde | Opérations |",
        "|---|---|---|---|---|",
    ]
    for m in dossier["synthese_mensuelle"]:
        lignes.append(
            f"| {m['mois']} | {fmt_fcfa(m['ventes_cents'])} | {fmt_fcfa(m['depenses_cents'])} "
            f"| {fmt_fcfa(m['solde_cents'])} | {m['nb_ecritures']} |"
        )
    dettes = dossier["dettes_actives"]
    lignes += ["", "## Dettes en cours", ""]
    if dettes:
        for d in dettes:
            lignes.append(f"- {d['sens'].lower()} : {fmt_fcfa(d['reste_du_cents'])}")
    else:
        lignes.append("- Aucune.")
    lignes += ["", "## Note de lecture", "", dossier["note_lecture"], ""]
    return "\n".join(lignes)
