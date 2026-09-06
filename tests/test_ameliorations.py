"""Tests des améliorations : purge worker, dettes enrichies, relance REST."""
from datetime import date, timedelta

from app.core.db import utcnow
from app.models import Ecriture, EcritureStatut
from app.services.ecritures import proposer_ecriture
from worker.run import purger_provisoires_perimees


def test_purge_provisoires_perimees(db, compte):
    from datetime import datetime, timezone

    vieille = proposer_ecriture(
        db, compte_id=compte.id, type_="VENTE", montant_cents=1000, canal="WEB",
        date_ecriture=utcnow() - timedelta(hours=3),
    )
    recente = proposer_ecriture(
        db, compte_id=compte.id, type_="VENTE", montant_cents=2000, canal="WEB",
        date_ecriture=utcnow() - timedelta(minutes=10),
    )
    db.flush()
    nb = purger_provisoires_perimees(db)
    db.commit()
    assert nb == 1
    assert db.get(Ecriture, vieille.id) is None  # jamais confirmée, purgée
    assert db.get(Ecriture, recente.id) is not None  # récente conservée
    assert db.get(Ecriture, recente.id).statut == EcritureStatut.PROVISOIRE


def _register(client, tel="+22890000020"):
    r = client.post("/api/v1/auth/register", json={
        "prenom": "Démo", "telephone": tel, "langue": "fr", "pin": "1234",
    })
    return r.json()


def test_dettes_enrichies_et_relance_rest(client):
    data = _register(client)
    h = {"Authorization": f"Bearer {data['access_token']}"}
    echeance = (date.today() - timedelta(days=10)).isoformat()
    r = client.post("/tools/dettes/creer", headers=h, json={
        "sens": "CLIENT", "tiers_nom": "Koffi", "montant_cents": 450000,
        "echeance": echeance,
    })
    assert r.json()["ok"] is True

    lister = client.get("/api/v1/dettes", headers=h).json()
    item = lister["items"][0]
    assert item["tiers_nom"] == "Koffi"
    assert item["relançable"] is True  # échue depuis 10 jours (REQ-F-DET-006)

    relance = client.post(f"/api/v1/dettes/{item['id']}/relancer", headers=h, json={})
    assert relance.status_code == 200

    apres = client.get("/api/v1/dettes", headers=h).json()["items"][0]
    assert apres["statut"] == "EN_RELANCE"
