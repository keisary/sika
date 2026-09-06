"""Modèles SQLAlchemy 2.0 — schéma Annexe C du cahier des charges Sika.

Conventions appliquées (C-CON-001, C-CON-006, REQ-DB-002/003/004) :
- montants en BIGINT centimes ; horodatages UTC ; chaque table métier porte
  compte_id indexé (multi-tenant) ; enums stockés en String (portable).
"""
import uuid
from datetime import date as date_type

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .core.db import Base, utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


# --- Enums applicatifs (String en base, validation en couche service) ---

class EcritureType:
    VENTE = "VENTE"
    DEPENSE = "DEPENSE"
    PAIEMENT_RECU = "PAIEMENT_RECU"
    PAIEMENT_EMIS = "PAIEMENT_EMIS"
    EPARGNE = "EPARGNE"
    AJUSTEMENT = "AJUSTEMENT"
    ALL = {VENTE, DEPENSE, PAIEMENT_RECU, PAIEMENT_EMIS, EPARGNE, AJUSTEMENT}


class EcritureStatut:
    PROVISOIRE = "PROVISOIRE"
    CONFIRMEE = "CONFIRMEE"
    ANNULEE = "ANNULEE"
    ALL = {PROVISOIRE, CONFIRMEE, ANNULEE}


class DetteSens:
    CLIENT = "CLIENT"  # tiers me doit (créance)
    FOURNISSEUR = "FOURNISSEUR"  # je dois au tiers
    ALL = {CLIENT, FOURNISSEUR}


class DetteStatut:
    EN_COURS = "EN_COURS"
    PARTIELLE = "PARTIELLE"
    EN_RELANCE = "EN_RELANCE"
    PAYEE = "PAYEE"
    ANNULEE = "ANNULEE"
    ACTIVES = {EN_COURS, PARTIELLE, EN_RELANCE}
    ALL = {EN_COURS, PARTIELLE, EN_RELANCE, PAYEE, ANNULEE}


class Canal:
    VOCAL_NAV = "VOCAL_NAV"
    VOCAL_TEL = "VOCAL_TEL"
    WEB = "WEB"
    WORKER = "WORKER"
    ALL = {VOCAL_NAV, VOCAL_TEL, WEB, WORKER}


class TypeTiers:
    CLIENT = "CLIENT"
    FOURNISSEUR = "FOURNISSEUR"


class NotificationStatut:
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    ALL = {PENDING, SENT, FAILED}


class RelanceStatut:
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    ALL = {PENDING, SENT, FAILED}


# --- Tables ---

class Compte(Base):
    __tablename__ = "comptes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prenom: Mapped[str] = mapped_column(String(80), nullable=False)
    telephone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    langue: Mapped[str] = mapped_column(String(8), default="fr", nullable=False)  # fr|en|pt|es
    devise: Mapped[str] = mapped_column(String(8), default="XOF", nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(140), nullable=False)
    cree_le: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Consentement(Base):
    __tablename__ = "consentements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), index=True, nullable=False)
    perimetre: Mapped[str] = mapped_column(String(60), nullable=False)  # notifications|sessions|dossier
    canal: Mapped[str] = mapped_column(String(30), nullable=False)
    date: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Produit(Base):
    __tablename__ = "produits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), index=True, nullable=False)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    prix_unitaire_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unite: Mapped[str] = mapped_column(String(40), default="unité", nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Tiers(Base):
    __tablename__ = "tiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), index=True, nullable=False)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    telephone: Mapped[str] = mapped_column(String(32), nullable=True)
    type: Mapped[str] = mapped_column(String(20), default=TypeTiers.CLIENT, nullable=False)


class Ecriture(Base):
    __tablename__ = "ecritures"
    __table_args__ = (Index("ix_ecritures_compte_date", "compte_id", "date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    statut: Mapped[str] = mapped_column(String(12), default=EcritureStatut.PROVISOIRE, nullable=False)
    montant_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    libelle: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    date: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    canal: Mapped[str] = mapped_column(String(20), default=Canal.WEB, nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=True)
    tiers_id: Mapped[str] = mapped_column(ForeignKey("tiers.id"), nullable=True)
    annule_par_id: Mapped[str] = mapped_column(ForeignKey("ecritures.id"), nullable=True)
    lignes_json: Mapped[str] = mapped_column(Text, nullable=True)


class Dette(Base):
    __tablename__ = "dettes"
    __table_args__ = (Index("ix_dettes_compte_statut", "compte_id", "statut"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), nullable=False)
    tiers_id: Mapped[str] = mapped_column(ForeignKey("tiers.id"), nullable=False)
    ecriture_id: Mapped[str] = mapped_column(ForeignKey("ecritures.id"), nullable=True)
    sens: Mapped[str] = mapped_column(String(20), nullable=False)
    montant_initial_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reste_du_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    statut: Mapped[str] = mapped_column(String(20), default=DetteStatut.EN_COURS, nullable=False)
    echeance: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    cree_le: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Relance(Base):
    __tablename__ = "relances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), index=True, nullable=False)
    dette_id: Mapped[str] = mapped_column(ForeignKey("dettes.id"), nullable=False)
    date: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    canal: Mapped[str] = mapped_column(String(20), default="WHATSAPP", nullable=False)
    statut: Mapped[str] = mapped_column(String(12), default=RelanceStatut.PENDING, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ObjectifEpargne(Base):
    __tablename__ = "objectifs_epargne"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), index=True, nullable=False)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    cible_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    regle_montant_cents: Mapped[int] = mapped_column(BigInteger, nullable=True)
    regle_frequence: Mapped[str] = mapped_column(String(30), nullable=True)  # QUOTIDIEN|HEBDO
    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cree_le: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notif_compte_statut", "compte_id", "statut"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), nullable=False)
    destinataire: Mapped[str] = mapped_column(String(32), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    statut: Mapped[str] = mapped_column(String(12), default=NotificationStatut.PENDING, nullable=False)
    tentatives: Mapped[int] = mapped_column(default=0, nullable=False)
    horodatage: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SessionVocale(Base):
    __tablename__ = "sessions_vocales"
    __table_args__ = (Index("ix_sessions_compte_debut", "compte_id", "debut"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), nullable=True)
    session_aai_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    canal: Mapped[str] = mapped_column(String(20), default=Canal.VOCAL_NAV, nullable=False)
    langue: Mapped[str] = mapped_column(String(8), default="fr", nullable=False)
    debut: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    fin: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=True)


class DossierCredit(Base):
    __tablename__ = "dossiers_credit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), index=True, nullable=False)
    debut_periode: Mapped[date_type] = mapped_column(Date, nullable=False)
    fin_periode: Mapped[date_type] = mapped_column(Date, nullable=False)
    genere_le: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    canal: Mapped[str] = mapped_column(String(20), default=Canal.WEB, nullable=False)
    contenu_json: Mapped[str] = mapped_column(Text, nullable=False)


class EntreeAudit(Base):
    __tablename__ = "entrees_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    compte_id: Mapped[str] = mapped_column(ForeignKey("comptes.id"), nullable=True)
    acteur: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    reference: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    horodatage: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
