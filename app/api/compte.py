"""Comptes & authentification (REQ-F-CMP) — routes REST."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import new_access_token
from ..models import Compte
from ..services import comptes as svc
from .deps import current_compte
from .schemas import ConsentementIn, LangueIn, LoginIn, RegisterIn

router = APIRouter()


def _compte_public(compte: Compte) -> dict:
    return {
        "id": compte.id,
        "prenom": compte.prenom,
        "telephone": compte.telephone,
        "langue": compte.langue,
        "devise": compte.devise,
    }


@router.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    try:
        compte = svc.creer_compte(
            db, prenom=body.prenom, telephone=body.telephone,
            langue=body.langue, pin=body.pin,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"compte": _compte_public(compte),
            "access_token": new_access_token(compte.id)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    compte = svc.authentifier(db, body.telephone, body.pin)
    if compte is None:
        raise HTTPException(status_code=401, detail="Téléphone ou PIN incorrect.")
    return {"compte": _compte_public(compte),
            "access_token": new_access_token(compte.id)}


@router.get("/compte/me")
def me(compte: Compte = Depends(current_compte)):
    return _compte_public(compte)


@router.patch("/compte/langue")
def set_langue(body: LangueIn, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    try:
        svc.changer_langue(db, compte.id, body.langue)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return _compte_public(svc_changed(db, compte.id))


def svc_changed(db, compte_id):
    return db.get(Compte, compte_id)


@router.post("/compte/consentements")
def consentement(body: ConsentementIn, compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    svc.enregistrer_consentement(db, compte.id, body.perimetre, body.canal)
    db.commit()
    return {"ok": True}


@router.delete("/compte")
def effacer(compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    """Droit à l'effacement (REQ-F-CMP-004)."""
    svc.effacer_compte(db, compte.id)
    db.commit()
    return {"ok": True}
