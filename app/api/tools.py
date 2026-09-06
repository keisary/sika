"""Outils HTTP appelés par l'agent vocal AssemblyAI (C-CON-007, REQ-IF-S-002).

Chaque outil écrit après confirmation verbale de l'utilisatrice (le rôle de
l'agent est de confirmer AVANT d'appeler). Réponse normalisée :
{"ok": bool, "message": str (canonique FR, l'agent traduit), "data": {...}}
Tous les calculs sont faits ici (C-CON-003, REQ-AI-001).
"""
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Compte, Ecriture
from ..services import bilans as bilans_svc
from ..services import dettes as dettes_svc
from ..services import dossier as dossier_svc
from ..services import epargne as epargne_svc
from ..services._util import dumps_json, fmt_fcfa
from ..services.ecritures import annuler_ecriture, confirmer_ecriture, proposer_ecriture
from .deps import current_compte

router = APIRouter()


def _ok(message: str, data: dict | None = None) -> dict:
    return {"ok": True, "message": message, "data": data or {}}


def _ko(error: str) -> dict:
    return {"ok": False, "message": error, "data": {}}


def _canal(header: str = Header(default="VOCAL_NAV")) -> str:
    return header.upper() if header.upper() in {"VOCAL_NAV", "VOCAL_TEL"} else "VOCAL_NAV"


def _parse_echeance(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Échéance invalide (format AAAA-MM-JJ).")


def _montant_lignes(lignes: list | None, quantite: int | None, prix_unitaire_cents: int | None) -> tuple[int, list]:
    """Calcule le total côté backend à partir des lignes (REQ-F-VEN-002/003)."""
    if lignes:
        total = 0
        normalisees = []
        for ligne in lignes:
            q = int(ligne.get("quantite", 1))
            p = int(ligne["prix_unitaire_cents"])
            if q <= 0 or p <= 0:
                raise ValueError("Quantités et prix doivent être strictement positifs.")
            total += q * p
            normalisees.append({"produit": ligne.get("produit", ""), "quantite": q,
                                "prix_unitaire_cents": p})
        return total, normalisees
    q = int(quantite or 1)
    p = int(prix_unitaire_cents or 0)
    if q <= 0 or p <= 0:
        raise ValueError("Quantité et prix unitaire requis et strictement positifs.")
    return q * p, [{"quantite": q, "prix_unitaire_cents": p}]


@router.post("/tools/accueil")
def accueil(compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    b = bilans_svc.bilan_du_jour(db, compte.id)
    candidates = dettes_svc.dettes_echues_relançables(db, compte.id)
    msg = (
        f"Bonjour {compte.prenom}, je suis Sika. Solde du jour : {fmt_fcfa(b['solde_caisse_cents'])}. "
        f"{b['dettes_clients_actives']['nb']} créance(s) client en cours, dont "
        f"{len(candidates)} échue(s) depuis plus de 3 jours."
    )
    return _ok(msg, {
        "prenom": compte.prenom, "langue": compte.langue,
        "solde_jour_cents": b["solde_caisse_cents"],
        "nb_dettes_clients": b["dettes_clients_actives"]["nb"],
        "nb_relances_candidates": len(candidates),
    })


@router.post("/tools/ventes/proposer")
def proposer_vente(body: dict, compte: Compte = Depends(current_compte),
                   db: Session = Depends(get_db), canal: str = Depends(_canal)):
    try:
        total, lignes = _montant_lignes(
            body.get("lignes"), body.get("quantite"), body.get("prix_unitaire_cents"))
        meta = {"lignes": lignes, "a_credit": bool(body.get("a_credit")),
                "tiers_nom": (body.get("tiers_nom") or "").strip(),
                "echeance": body.get("echeance")}
        e = proposer_ecriture(
            db, compte_id=compte.id, type_="VENTE", montant_cents=total,
            libelle=body.get("libelle") or f"Vente ({len(lignes)} ligne(s))",
            canal=canal, meta=meta, session_id=body.get("session_id"),
        )
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    description = " ; ".join(
        f"{l['quantite']} x {fmt_fcfa(l['prix_unitaire_cents'])}" for l in lignes)
    suffixe = " À crédit." if meta["a_credit"] else " Au comptant."
    return _ok(
        f"Vente proposée : {description}, total {fmt_fcfa(total)}.{suffixe} "
        "Confirmez-vous cette vente ?",
        {"ecriture_id": e.id, "montant_cents": total, "statut": e.statut},
    )


@router.post("/tools/ecritures/confirmer")
def confirmer(body: dict, compte: Compte = Depends(current_compte),
              db: Session = Depends(get_db)):
    ecriture_id = body.get("ecriture_id")
    if not ecriture_id:
        return _ko("ecriture_id requis.")
    try:
        e = db.get(Ecriture, ecriture_id)
        if e is None or e.compte_id != compte.id:
            raise ValueError("Écriture introuvable.")
        meta = json.loads(e.lignes_json) if e.lignes_json else {}
        confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
        message = f"Confirmé : {fmt_fcfa(e.montant_cents)} notés."
        if e.type == "VENTE" and meta.get("a_credit"):
            echeance = _parse_echeance(meta.get("echeance"))
            dette = dettes_svc.creer_dette(
                db, compte_id=compte.id, sens="CLIENT",
                tiers_nom=meta.get("tiers_nom") or "client",
                montant_cents=e.montant_cents, echeance=echeance,
                ecriture=e, canal=e.canal,
            )
            message += f" Dette client créée : {fmt_fcfa(dette.montant_initial_cents)}."
        elif e.type == "DEPENSE" and meta.get("a_credit"):
            echeance = _parse_echeance(meta.get("echeance"))
            dette = dettes_svc.creer_dette(
                db, compte_id=compte.id, sens="FOURNISSEUR",
                tiers_nom=meta.get("tiers_nom") or "fournisseur",
                montant_cents=e.montant_cents, echeance=echeance,
                ecriture=e, canal=e.canal,
            )
            message += f" Dette fournisseur créée : {fmt_fcfa(dette.montant_initial_cents)}."
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _ko(str(exc))
    return _ok(message, {"ecriture_id": e.id, "statut": e.statut})


@router.post("/tools/depenses/proposer")
def proposer_depense(body: dict, compte: Compte = Depends(current_compte),
                     db: Session = Depends(get_db), canal: str = Depends(_canal)):
    try:
        montant = int(body["montant_cents"])
        meta = {"a_credit": bool(body.get("a_credit")),
                "tiers_nom": (body.get("tiers_nom") or "").strip(),
                "echeance": body.get("echeance")}
        e = proposer_ecriture(
            db, compte_id=compte.id, type_="DEPENSE", montant_cents=montant,
            libelle=body.get("libelle") or "Dépense", canal=canal, meta=meta,
            session_id=body.get("session_id"),
        )
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    suffixe = " À crédit." if meta["a_credit"] else " Au comptant."
    return _ok(
        f"Dépense proposée : {fmt_fcfa(montant)}.{suffixe} Je confirme ?",
        {"ecriture_id": e.id, "montant_cents": montant, "statut": e.statut},
    )


@router.post("/tools/ecritures/annuler")
def annuler(body: dict, compte: Compte = Depends(current_compte),
            db: Session = Depends(get_db)):
    ecriture_id = body.get("ecriture_id")
    if not ecriture_id:
        return _ko("ecriture_id requis.")
    try:
        annuler_ecriture(db, compte_id=compte.id, ecriture_id=ecriture_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _ko(str(exc))
    return _ok("Opération annulée. Une écriture d'ajustement a été créée.", {"ecriture_id": ecriture_id})


@router.get("/tools/ecritures/derniere")
def derniere_ecriture(compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    from sqlalchemy import select

    e = db.execute(
        select(Ecriture).where(Ecriture.compte_id == compte.id,
                               Ecriture.statut == "CONFIRMEE",
                               Ecriture.type != "AJUSTEMENT")
        .order_by(Ecriture.date.desc()).limit(1)
    ).scalar_one_or_none()
    if e is None:
        return _ok("Aucune opération à annuler.", {})
    return _ok(
        f"Dernière opération : {e.libelle or e.type}, {fmt_fcfa(e.montant_cents)}.",
        {"ecriture_id": e.id, "type": e.type, "libelle": e.libelle,
         "montant_cents": e.montant_cents},
    )


@router.get("/tools/dettes/lister")
def lister_dettes(sens: str | None = None, compte: Compte = Depends(current_compte),
                  db: Session = Depends(get_db)):
    dettes = dettes_svc.dettes_actives(db, compte.id, sens=sens)
    relançables = {d.id for d in dettes_svc.dettes_echues_relançables(db, compte.id)}
    items = [
        {"id": d.id, "sens": d.sens, "reste_du_cents": d.reste_du_cents,
         "statut": d.statut, "echeance": d.echeance.isoformat() if d.echeance else None,
         "relançable": d.id in relançables}
        for d in dettes
    ]
    if not items:
        return _ok("Aucune dette en cours.", {"items": []})
    texte = "Dettes en cours : " + ", ".join(
        f"{d['sens'].lower()} {fmt_fcfa(d['reste_du_cents'])}"
        + (" (relançable)" if d["relançable"] else "") for d in items)
    return _ok(texte, {"items": items})


@router.post("/tools/dettes/creer")
def creer_dette(body: dict, compte: Compte = Depends(current_compte),
                db: Session = Depends(get_db), canal: str = Depends(_canal)):
    try:
        sens = str(body.get("sens", "")).upper()
        if sens not in {"CLIENT", "FOURNISSEUR"}:
            raise ValueError("sens doit être CLIENT ou FOURNISSEUR.")
        tiers_nom = (body.get("tiers_nom") or "").strip()
        if not tiers_nom:
            raise ValueError("tiers_nom requis.")
        montant = int(body["montant_cents"])
        echeance = _parse_echeance(body.get("echeance"))
        dette = dettes_svc.creer_dette(
            db, compte_id=compte.id, sens=sens, tiers_nom=tiers_nom,
            montant_cents=montant, echeance=echeance, canal=canal,
        )
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    label = "créance client" if sens == "CLIENT" else "dette fournisseur"
    return _ok(
        f"{label.capitalize()} créée : {tiers_nom}, {fmt_fcfa(montant)}.",
        {"dette_id": dette.id},
    )


@router.post("/tools/dettes/encaisser")
def encaisser(body: dict, compte: Compte = Depends(current_compte),
              db: Session = Depends(get_db), canal: str = Depends(_canal)):
    try:
        dettes_svc.encaisser_dette_client(
            db, compte_id=compte.id, dette_id=body["dette_id"],
            montant_cents=int(body["montant_cents"]), canal=canal,
        )
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    return _ok(f"Encaissement enregistré : {fmt_fcfa(int(body['montant_cents']))}.",
               {"dette_id": body["dette_id"]})


@router.post("/tools/dettes/regler")
def regler(body: dict, compte: Compte = Depends(current_compte),
           db: Session = Depends(get_db), canal: str = Depends(_canal)):
    try:
        dettes_svc.regler_dette_fournisseur(
            db, compte_id=compte.id, dette_id=body["dette_id"],
            montant_cents=int(body["montant_cents"]), canal=canal,
        )
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    return _ok(f"Règlement enregistré : {fmt_fcfa(int(body['montant_cents']))}.",
               {"dette_id": body["dette_id"]})


@router.post("/tools/dettes/relancer")
def relancer(body: dict, compte: Compte = Depends(current_compte),
             db: Session = Depends(get_db)):
    try:
        relance = dettes_svc.envoyer_relance(
            db, compte_id=compte.id, dette_id=body["dette_id"],
            message=body.get("message") or "Rappel amical de votre dette, merci.",
        )
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    return _ok("Relance enregistrée.", {"relance_id": relance.id})


@router.get("/tools/epargne/objectifs")
def objectifs(compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    items = []
    for o in epargne_svc.liste_objectifs(db, compte.id):
        p = epargne_svc.progression(db, compte.id, o.id)
        items.append({"objectif_id": o.id, "nom": o.nom, **p})
    if not items:
        return _ok("Aucun objectif d'épargne.", {"items": []})
    return _ok("Objectifs d'épargne disponibles.", {"items": items})


@router.post("/tools/epargne/deposer")
def deposer(body: dict, compte: Compte = Depends(current_compte),
            db: Session = Depends(get_db), canal: str = Depends(_canal)):
    try:
        epargne_svc.epargner(
            db, compte_id=compte.id, objectif_id=body["objectif_id"],
            montant_cents=int(body["montant_cents"]), canal=canal,
        )
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    return _ok(f"Épargne enregistrée : {fmt_fcfa(int(body['montant_cents']))}.",
               {"objectif_id": body["objectif_id"]})


@router.post("/tools/bilan")
def bilan(body: dict, compte: Compte = Depends(current_compte),
          db: Session = Depends(get_db)):
    try:
        periode = body.get("periode", "jour")
        if periode == "dates":
            debut = datetime.fromisoformat(body["debut"])
            fin = datetime.fromisoformat(body["fin"])
            b = bilans_svc.bilan_periode(db, compte.id, debut, fin)
        else:
            b = bilans_svc.bilan_du_jour(db, compte.id)
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    return _ok(bilans_svc.format_bilan(b, compte.langue), b)


@router.post("/tools/dossier/generer")
def generer(body: dict, compte: Compte = Depends(current_compte),
            db: Session = Depends(get_db), canal: str = Depends(_canal)):
    try:
        mois = int(body.get("mois", 3))
        dossier = dossier_svc.generer_dossier(db, compte_id=compte.id, mois=mois, canal=canal)
        db.commit()
    except (ValueError, KeyError) as exc:
        db.rollback()
        return _ko(str(exc))
    taux = dossier["regularite"]["taux"] * 100
    return _ok(
        f"Dossier de crédit ({mois} mois) généré. Régularité : {taux:.0f} %. "
        "Disponible sur le tableau de bord.",
        {"mois": mois, "regularite_taux": dossier["regularite"]["taux"]},
    )
