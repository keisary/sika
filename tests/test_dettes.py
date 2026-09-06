"""Dettes : cycle de vie complet (REQ-F-DET) et diagramme d'état A.6."""
from datetime import date, timedelta

import pytest

from app.models import DetteStatut, DetteSens
from app.services import dettes as svc


def _dette(db, compte, sens=DetteSens.CLIENT, montant=100000, echeance=None):
    d = svc.creer_dette(db, compte_id=compte.id, sens=sens,
                        tiers_nom="Koffi" if sens == DetteSens.CLIENT else "Grossiste",
                        montant_cents=montant, echeance=echeance, canal="WEB")
    db.commit()
    return d


def test_encaissement_partiel_puis_total(db, compte):
    d = _dette(db, compte)
    svc.encaisser_dette_client(db, compte_id=compte.id, dette_id=d.id,
                               montant_cents=40000, canal="WEB")
    db.commit()
    assert d.statut == DetteStatut.PARTIELLE
    assert d.reste_du_cents == 60000
    svc.encaisser_dette_client(db, compte_id=compte.id, dette_id=d.id,
                               montant_cents=60000, canal="WEB")
    db.commit()
    assert d.statut == DetteStatut.PAYEE
    assert d.reste_du_cents == 0


def test_encaissement_trop_eleve_refuse(db, compte):
    d = _dette(db, compte, montant=50000)
    with pytest.raises(ValueError):
        svc.encaisser_dette_client(db, compte_id=compte.id, dette_id=d.id,
                                   montant_cents=50001, canal="WEB")
    assert d.reste_du_cents == 50000


def test_encaisser_sur_dette_fournisseur_refuse(db, compte):
    d = _dette(db, compte, sens=DetteSens.FOURNISSEUR)
    with pytest.raises(ValueError):
        svc.encaisser_dette_client(db, compte_id=compte.id, dette_id=d.id,
                                   montant_cents=1000, canal="WEB")


def test_annulation_dette_avec_paiement_refusee(db, compte):
    d = _dette(db, compte, montant=50000)
    svc.encaisser_dette_client(db, compte_id=compte.id, dette_id=d.id,
                               montant_cents=10000, canal="WEB")
    db.commit()
    with pytest.raises(ValueError):
        svc.annuler_dette(db, compte_id=compte.id, dette_id=d.id)


def test_annulation_dette_propre_ok(db, compte):
    d = _dette(db, compte)
    svc.annuler_dette(db, compte_id=compte.id, dette_id=d.id)
    db.commit()
    assert d.statut == DetteStatut.ANNULEE
    # REQ-F-DET-009 : dette annulée non relançable ni encaissable
    with pytest.raises(ValueError):
        svc.encaisser_dette_client(db, compte_id=compte.id, dette_id=d.id,
                                   montant_cents=1000, canal="WEB")
    assert svc.dettes_echues_relançables(db, compte.id) == []


def test_relance_seulement_echue_plus_de_3_jours(db, compte):
    ancienne = _dette(db, compte, echeance=date.today() - timedelta(days=10))
    recente = svc.creer_dette(db, compte_id=compte.id, sens=DetteSens.CLIENT,
                              tiers_nom="Récents", montant_cents=1000,
                              echeance=date.today() - timedelta(days=1), canal="WEB")
    db.commit()
    candidates = svc.dettes_echues_relançables(db, compte.id)
    ids = {d.id for d in candidates}
    assert ancienne.id in ids
    assert recente.id not in ids  # échue depuis 1 jour seulement (REQ-F-DET-006)


def test_envoyer_relance_passe_en_etat_en_relance(db, compte):
    d = _dette(db, compte, echeance=date.today() - timedelta(days=5))
    svc.envoyer_relance(db, compte_id=compte.id, dette_id=d.id,
                        message="Rappel amical.")
    db.commit()
    assert d.statut == DetteStatut.EN_RELANCE


def test_dettes_actives_par_sens(db, compte):
    svc.creer_dette(db, compte_id=compte.id, sens=DetteSens.CLIENT,
                    tiers_nom="Client A", montant_cents=1000, canal="WEB")
    svc.creer_dette(db, compte_id=compte.id, sens=DetteSens.FOURNISSEUR,
                    tiers_nom="Fournisseur B", montant_cents=2000, canal="WEB")
    db.commit()
    clients = svc.dettes_actives(db, compte.id, sens=DetteSens.CLIENT)
    fournisseurs = svc.dettes_actives(db, compte.id, sens=DetteSens.FOURNISSEUR)
    assert len(clients) == 1 and len(fournisseurs) == 1
