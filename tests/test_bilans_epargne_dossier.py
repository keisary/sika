"""Épargne, bilans, dossier de crédit, notifications (REQ-F-EPG/BIL/CRD/NOT)."""
from datetime import timedelta

import pytest

from app.core.db import utcnow
from app.models import NotificationStatut
from app.services import bilans as bilans_svc
from app.services import dossier as dossier_svc
from app.services import epargne as epargne_svc
from app.services import notifications as notif_svc
from app.services.ecritures import confirmer_ecriture, proposer_ecriture


def _ecriture(db, compte, type_, cents, jours_avant=0):
    e = proposer_ecriture(db, compte_id=compte.id, type_=type_, montant_cents=cents,
                          canal="WEB", date_ecriture=utcnow() - timedelta(days=jours_avant))
    confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    return e


# --- Épargne ---

def test_epargne_progression(db, compte):
    obj = epargne_svc.creer_objectif(db, compte_id=compte.id, nom="Réassort",
                                     cible_cents=100000, regle_montant_cents=1000)
    epargne_svc.epargner(db, compte_id=compte.id, objectif_id=obj.id,
                         montant_cents=25000, canal="WEB")
    db.commit()
    prog = epargne_svc.progression(db, compte.id, obj.id)
    assert prog["epargne_cents"] == 25000
    assert prog["reste_cents"] == 75000


def test_epargne_objectif_inconnu_refuse(db, compte):
    with pytest.raises(ValueError):
        epargne_svc.epargner(db, compte_id=compte.id, objectif_id="nope",
                             montant_cents=1000, canal="WEB")


# --- Bilans ---

def test_bilan_du_jour_agrege_et_epargne_sortie(db, compte):
    _ecriture(db, compte, "VENTE", 50000)
    _ecriture(db, compte, "DEPENSE", 15000)
    obj = epargne_svc.creer_objectif(db, compte_id=compte.id, nom="Caisse", cible_cents=100000)
    epargne_svc.epargner(db, compte_id=compte.id, objectif_id=obj.id, montant_cents=10000, canal="WEB")
    db.commit()
    b = bilans_svc.bilan_du_jour(db, compte.id)
    assert b["ventes_cents"] == 50000
    assert b["depenses_cents"] == 15000
    assert b["epargne_cents"] == 10000
    # solde = 50000 - 15000 - 10000 (épargne = sortie de caisse)
    assert b["solde_caisse_cents"] == 25000


def test_bilan_periode_personnalisee(db, compte):
    _ecriture(db, compte, "VENTE", 30000, jours_avant=6)
    _ecriture(db, compte, "VENTE", 10000, jours_avant=1)
    db.commit()
    debut = utcnow() - timedelta(days=2)
    fin = utcnow() + timedelta(minutes=1)
    b = bilans_svc.bilan_periode(db, compte.id, debut, fin)
    assert b["ventes_cents"] == 10000  # seule la vente récente est dans la fenêtre


# --- Dossier de crédit ---

def test_dossier_credit_3_mois_contenu(db, compte):
    _ecriture(db, compte, "VENTE", 50000, jours_avant=10)
    _ecriture(db, compte, "VENTE", 30000, jours_avant=60)
    db.commit()
    dossier = dossier_svc.generer_dossier(db, compte_id=compte.id, mois=3, canal="WEB")
    assert len(dossier["synthese_mensuelle"]) == 3  # 3 mois calendaires
    total_ventes = sum(m["ventes_cents"] for m in dossier["synthese_mensuelle"])
    assert total_ventes == 80000
    assert dossier["regularite"]["jours_actifs"] >= 1
    md = dossier_svc.render_markdown(dossier)
    assert "Dossier de crédit" in md and "Note de lecture" in md


def test_dossier_periode_invalide(db, compte):
    with pytest.raises(ValueError):
        dossier_svc.generer_dossier(db, compte_id=compte.id, mois=12, canal="WEB")


def test_dossier_isolation_tenant(db, compte, compte_b):
    _ecriture(db, compte, "VENTE", 9999999)
    db.commit()
    dossier_a = dossier_svc.generer_dossier(db, compte_id=compte.id, mois=3, canal="WEB")
    dossier_b = dossier_svc.generer_dossier(db, compte_id=compte_b.id, mois=3, canal="WEB")
    ventes_b = sum(m["ventes_cents"] for m in dossier_b["synthese_mensuelle"])
    assert ventes_b == 0  # aucune donnée du compte A chez B (REQ-F-CRD-003)


# --- Notifications ---

def test_notification_console_envoyee_et_tracee(db, compte):
    n = notif_svc.envoyer(db, compte_id=compte.id, destinataire=compte.telephone,
                          canal="WHATSAPP", contenu="Récap Sika")
    db.commit()
    assert n.statut == NotificationStatut.SENT
    assert n.tentatives == 0


def test_recap_journee_sans_optin_ne_part_pas(db, compte):
    _ecriture(db, compte, "VENTE", 5000)
    db.commit()
    assert notif_svc.recap_fin_journee(db) == 0  # pas de consentement (REQ-F-NOT-001)


def test_recap_journee_avec_optin_part(db, compte):
    from app.services.comptes import enregistrer_consentement

    enregistrer_consentement(db, compte.id, "notifications", "WEB")
    _ecriture(db, compte, "VENTE", 5000)
    db.commit()
    assert notif_svc.recap_fin_journee(db) == 1
