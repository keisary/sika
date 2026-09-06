"""Contrats d'entrée (Pydantic) — validation stricte avant traitement (REQ-NF-SEC-005)."""
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    telephone: str = Field(min_length=6, max_length=32)
    pin: str = Field(min_length=4, max_length=6)


class RegisterIn(BaseModel):
    prenom: str = Field(min_length=1, max_length=80)
    telephone: str = Field(min_length=6, max_length=32)
    langue: str = "fr"
    pin: str = Field(min_length=4, max_length=6)


class LangueIn(BaseModel):
    langue: str = Field(min_length=2, max_length=8)


class ConsentementIn(BaseModel):
    perimetre: str = Field(min_length=2, max_length=60)
    canal: str = "WEB"


class EcritureProposeIn(BaseModel):
    type: str
    montant_cents: int
    libelle: str = ""
    date: str | None = None  # ISO 8601 optionnel


class ConfirmerIn(BaseModel):
    ecriture_id: str


class AnnulerIn(BaseModel):
    ecriture_id: str
    raison: str = ""


class EncaisserIn(BaseModel):
    montant_cents: int = Field(gt=0)


class RelancerIn(BaseModel):
    message: str = ""


class ObjectifIn(BaseModel):
    nom: str = Field(min_length=1, max_length=120)
    cible_cents: int = Field(gt=0)
    regle_montant_cents: int | None = None
    regle_frequence: str | None = None


class DepotIn(BaseModel):
    montant_cents: int = Field(gt=0)


class DossierIn(BaseModel):
    mois: int = 3
