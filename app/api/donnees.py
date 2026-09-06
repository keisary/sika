"""Données du dashboard : écritures, dettes, épargne, bilan, dossier, notifications."""
import csv
import io
import json
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import (
    Compte, Dette, DossierCredit, Ecriture, EcritureStatut, Notification,
    ObjectifEpargne,
)
from ..services import bilans as bilans_svc
from ..services import dettes as dettes_svc
from ..services import dossier as dossier_svc
from ..services import epargne as epargne_svc
from ..services.ecritures import annuler_ecriture, confirmer_ecriture, proposer_ecriture
from .deps import current_compte
from .schemas import AnnulerIn, DepotIn, DossierIn, EncaisserIn, ObjectifIn

router = APIRouter()


def _ecriture_out(e: Ecriture) -> dict:
    return {
        "id": e.id, "type": e.type, "statut": e.statut,
        "montant_cents": e.montant_cents, "libelle": e.libelle,
        "date": e.date.isoformat(), "canal": e.canal,
        "session_id": e.session_id, "tiers_id": e.tiers_id,
        "annule_par_id": e.annule_par_id,
    }


@router.get("/ecritures")
def lister_ecritures(
    type: str | None = None, statut: str | None = None,
    depuis: str | None = None, jusqua: str | None = None,
    canal: str | None = None, limit: int = Query(100, le=500),
    compte: Compte = Depends(current_compte), db: Session = Depends(get_db),
):
    q = select(Ecriture).where(Ecriture.compte_id == compte.id)
    if type:
        q = q.where(Ecriture.type == type.upper())
    if statut:
        q = q.where(Ecriture.statut == statut.upper())
    if canal:
        q = q.where(Ecriture.canal == canal.upper())
    if depuis:
        q = q.where(Ecriture.date >= datetime.fromisoformat(depuis))
    if jusqua:
        q = q.where(Ecriture.date < datetime.fromisoformat(jusqua))
    rows = db.execute(q.order_by(Ecriture.date.desc()).limit(limit)).scalars().all()
    return {"items": [_ecriture_out(e) for e in rows]}


@router.get("/ecritures/export.csv")
def export_csv(
    depuis: str | None = None, jusqua: str | None = None,
    compte: Compte = Depends(current_compte), db: Session = Depends(get_db),
):
    q = select(Ecriture).where(Ecriture.compte_id == compte.id)
    if depuis:
        q = q.where(Ecriture.date >= datetime.fromisoformat(depuis))
    if jusqua:
        q = q.where(Ecriture.date < datetime.fromisoformat(jusqua))
    rows = db.execute(q.order_by(Ecriture.date)).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "date", "type", "statut", "montant_cents", "libelle", "canal", "session_id"])
    for e in rows:
        writer.writerow([e.id, e.date.isoformat(), e.type, e.statut, e.montant_cents, e.libelle, e.canal, e.session_id or ""])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sika_ecritures.csv"'},
    )


@router.get("/ecritures/{ecriture_id}")
def detail_ecriture(ecriture_id: str, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    e = db.execute(
        select(Ecriture).where(Ecriture.id == ecriture_id, Ecriture.compte_id == compte.id)
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="Écriture introuvable.")
    return _ecriture_out(e)


@router.post("/ecritures")
def creer_ecriture_web(body: dict, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    """Saisie web directe : validée puis confirmée immédiatement (canal WEB)."""
    try:
        e = proposer_ecriture(
            db, compte_id=compte.id, type_=body["type"].upper(),
            montant_cents=int(body["montant_cents"]), libelle=body.get("libelle", ""),
            canal="WEB",
        )
        confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
        db.commit()
    except (KeyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return _ecriture_out(e)


@router.post("/ecritures/{ecriture_id}/annuler")
def annuler_route(ecriture_id: str, body: AnnulerIn | None = None,
                  compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    try:
        annuler_ecriture(db, compte_id=compte.id, ecriture_id=ecriture_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/dettes")
def lister_dettes(
    sens: str | None = None, statut: str | None = None,
    compte: Compte = Depends(current_compte), db: Session = Depends(get_db),
):
    q = select(Dette).where(Dette.compte_id == compte.id)
    if sens:
        q = q.where(Dette.sens == sens.upper())
    if statut:
        q = q.where(Dette.statut == statut.upper())
    dettes = db.execute(q.order_by(Dette.cree_le.desc())).scalars().all()
    from ..models import Tiers

    noms = {t.id: t.nom for t in db.execute(select(Tiers).where(Tiers.compte_id == compte.id)).scalars()}
    relançables = {d.id for d in dettes_svc.dettes_echues_relançables(db, compte.id)}
    return {"items": [{"id": d.id, "sens": d.sens, "tiers_id": d.tiers_id,
                       "tiers_nom": noms.get(d.tiers_id, "?"),
                       "montant_initial_cents": d.montant_initial_cents,
                       "reste_du_cents": d.reste_du_cents, "statut": d.statut,
                       "relançable": d.id in relançables,
                       "echeance": d.echeance.isoformat() if d.echeance else None}
                      for d in dettes]}


@router.post("/dettes/{dette_id}/encaisser")
def encaisser(dette_id: str, body: EncaisserIn, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    try:
        dettes_svc.encaisser_dette_client(db, compte_id=compte.id, dette_id=dette_id,
                                          montant_cents=body.montant_cents, canal="WEB")
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/dettes/{dette_id}/regler")
def regler(dette_id: str, body: EncaisserIn, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    try:
        dettes_svc.regler_dette_fournisseur(db, compte_id=compte.id, dette_id=dette_id,
                                            montant_cents=body.montant_cents, canal="WEB")
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/dettes/{dette_id}/annuler")
def annuler_dette(dette_id: str, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    try:
        dettes_svc.annuler_dette(db, compte_id=compte.id, dette_id=dette_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/dettes/{dette_id}/relancer")
def relancer_dette(dette_id: str, body: dict | None = None,
                   compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    """Relance validée par l'utilisatrice (REQ-F-DET-006/007, REQ-AI-006)."""
    try:
        message = (body or {}).get("message") or "Bonjour, rappel amical de votre dette. Merci de régulariser."
        dettes_svc.envoyer_relance(db, compte_id=compte.id, dette_id=dette_id, message=message)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/epargne/objectifs")
def objectifs(compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    out = []
    for o in epargne_svc.liste_objectifs(db, compte.id):
        prog = epargne_svc.progression(db, compte.id, o.id)
        out.append({"id": o.id, "nom": o.nom, "cible_cents": o.cible_cents,
                    "actif": o.actif, **prog})
    return {"items": out}


@router.post("/epargne/objectifs")
def creer_objectif(body: ObjectifIn, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    o = epargne_svc.creer_objectif(
        db, compte_id=compte.id, nom=body.nom, cible_cents=body.cible_cents,
        regle_montant_cents=body.regle_montant_cents, regle_frequence=body.regle_frequence,
    )
    db.commit()
    return {"id": o.id}


@router.post("/epargne/objectifs/{objectif_id}/depot")
def depot(objectif_id: str, body: DepotIn, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    try:
        epargne_svc.epargner(db, compte_id=compte.id, objectif_id=objectif_id,
                             montant_cents=body.montant_cents, canal="WEB")
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


def _parse_date(s: str | None, default: date | None = None) -> datetime | None:
    if s is None:
        return None
    d = date.fromisoformat(s)
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


@router.get("/bilan")
def bilan(
    debut: str | None = None, fin: str | None = None,
    compte: Compte = Depends(current_compte), db: Session = Depends(get_db),
):
    start = _parse_date(debut) or datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    end = _parse_date(fin) or datetime.combine(
        date.today() if not debut else date.fromisoformat(debut),
        time.max, tzinfo=timezone.utc,
    )
    if not debut:  # bilan du jour par défaut
        from ..services._util import day_range
        start, end = day_range()
    return bilans_svc.bilan_periode(db, compte.id, start, end)


@router.post("/dossier/generer")
def generer_dossier(body: DossierIn, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    try:
        dossier = dossier_svc.generer_dossier(
            db, compte_id=compte.id, mois=body.mois, canal="WEB",
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"markdown": dossier_svc.render_markdown(dossier), "dossier": dossier}


@router.get("/dossier")
def lister_dossiers(compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    rows = db.execute(
        select(DossierCredit).where(DossierCredit.compte_id == compte.id)
        .order_by(DossierCredit.genere_le.desc()).limit(20)
    ).scalars().all()
    return {"items": [{"id": d.id, "debut_periode": d.debut_periode.isoformat(),
                       "fin_periode": d.fin_periode.isoformat(),
                       "genere_le": d.genere_le.isoformat(), "canal": d.canal} for d in rows]}


@router.get("/dossier/{dossier_id}")
def lire_dossier(dossier_id: str, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    d = db.execute(
        select(DossierCredit).where(DossierCredit.id == dossier_id, DossierCredit.compte_id == compte.id)
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    return {"markdown": dossier_svc.render_markdown(json.loads(d.contenu_json))}


@router.get("/notifications")
def lister_notifications(statut: str | None = None,
                         compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.compte_id == compte.id)
    if statut:
        q = q.where(Notification.statut == statut.upper())
    rows = db.execute(q.order_by(Notification.horodatage.desc()).limit(50)).scalars().all()
    return {"items": [{"id": n.id, "canal": n.canal, "destinataire": n.destinataire,
                       "statut": n.statut, "contenu": n.contenu,
                       "horodatage": n.horodatage.isoformat()} for n in rows]}
