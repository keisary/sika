"""Cycle de vie des écritures (REQ-F-VEN, REQ-F-ACH, C-CON-003/004/005)."""
import pytest
from sqlalchemy import select

from app.models import Ecriture, EcritureStatut, EcritureType, EntreeAudit
from app.services.ecritures import (
    annuler_ecriture,
    confirmer_ecriture,
    proposer_ecriture,
    totaux_periode,
)
from app.core.db import utcnow
from datetime import timedelta


def _periode():
    return utcnow() - timedelta(days=1), utcnow() + timedelta(days=1)


def test_vente_provisoire_puis_confirmee(db, compte):
    e = proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                          montant_cents=100000, canal="VOCAL_NAV")
    assert e.statut == EcritureStatut.PROVISOIRE
    confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    db.commit()
    assert e.statut == EcritureStatut.CONFIRMEE
    tot = totaux_periode(db, compte.id, *_periode())
    assert tot["solde_caisse_cents"] == 100000  # 1 000 FCFA encaissés
    assert tot["ventes_cents"] == 100000


def test_ecriture_provisoire_exclue_des_agregats(db, compte):
    proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                      montant_cents=50000, canal="VOCAL_NAV")
    db.commit()
    tot = totaux_periode(db, compte.id, *_periode())
    assert tot["nb_ecritures"] == 0  # RIEN n'est définitif avant confirmation (C-CON-004)


def test_annulation_ajustement_et_audit(db, compte):
    e = proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                          montant_cents=100000, canal="VOCAL_NAV")
    confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    annuler_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    db.commit()
    assert e.statut == EcritureStatut.ANNULEE
    ajustement = db.execute(
        select(Ecriture).where(Ecriture.type == EcritureType.AJUSTEMENT,
                               Ecriture.annule_par_id == e.id)
    ).scalar_one()
    assert ajustement.montant_cents == -100000
    tot = totaux_periode(db, compte.id, *_periode())
    assert tot["solde_caisse_cents"] == 0  # l'annulation solde exactement (C-CON-005)
    audits = db.execute(select(EntreeAudit).where(EntreeAudit.compte_id == compte.id)).scalars().all()
    actions = {a.action for a in audits}
    assert {"ECRITURE.CONFIRMER", "ECRITURE.ANNULER"} <= actions


def test_annulation_double_refusee(db, compte):
    e = proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                          montant_cents=1000, canal="WEB")
    confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    annuler_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    with pytest.raises(ValueError):
        annuler_ecriture(db, compte_id=compte.id, ecriture_id=e.id)


def test_confirmer_non_provisoire_refuse(db, compte):
    e = proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                          montant_cents=1000, canal="WEB")
    confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    with pytest.raises(ValueError):
        confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)


def test_bornes_montants(db, compte):
    with pytest.raises(ValueError):
        proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                          montant_cents=0, canal="WEB")
    with pytest.raises(ValueError):
        proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                          montant_cents=-5, canal="WEB")
    with pytest.raises(ValueError):  # > 100 000 000 FCFA (REQ-F-ACH-006)
        proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.DEPENSE,
                          montant_cents=100_000_001 * 100, canal="WEB")


def test_isolation_tenant(db, compte, compte_b):
    e = proposer_ecriture(db, compte_id=compte.id, type_=EcritureType.VENTE,
                          montant_cents=50000, canal="WEB")
    confirmer_ecriture(db, compte_id=compte.id, ecriture_id=e.id)
    db.commit()
    tot_a = totaux_periode(db, compte.id, *_periode())
    tot_b = totaux_periode(db, compte_b.id, *_periode())
    assert tot_a["ventes_cents"] == 50000
    assert tot_b["ventes_cents"] == 0  # C-CON-006 : étanchéité totale
