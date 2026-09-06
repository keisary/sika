"""Dépendances FastAPI : authentification par jeton (REQ-NF-SEC-003)."""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import decode_access_token
from ..models import Compte


def bearer_token(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton manquant.")
    return authorization.removeprefix("Bearer ").strip()


def current_compte(
    token: str = Depends(bearer_token), db: Session = Depends(get_db)
) -> Compte:
    compte_id = decode_access_token(token)
    if compte_id is None:
        raise HTTPException(status_code=401, detail="Jeton invalide ou expiré.")
    compte = db.get(Compte, compte_id)
    if compte is None:
        raise HTTPException(status_code=401, detail="Compte introuvable.")
    return compte
