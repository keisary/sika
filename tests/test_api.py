"""Tests d'intégration API + outils HTTP de l'agent vocal (parcours réels)."""
from conftest import token_de  # noqa: F401 (réutilisé implicitement via fixtures)
from fastapi.testclient import TestClient


def _register(client: TestClient, tel: str = "+22890000007") -> dict:
    r = client.post("/api/v1/auth/register", json={
        "prenom": "Testa", "telephone": tel, "langue": "fr", "pin": "1234",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_auth_mauvais_pin(client):
    _register(client)
    r = client.post("/api/v1/auth/login",
                    json={"telephone": "+22890000007", "pin": "9999"})
    assert r.status_code == 401


def test_effacement_compte(client):
    data = _register(client)
    r = client.delete("/api/v1/compte", headers=_headers(data["access_token"]))
    assert r.status_code == 200
    r2 = client.post("/api/v1/auth/login",
                     json={"telephone": "+22890000007", "pin": "1234"})
    assert r2.status_code == 401  # compte supprimé (REQ-F-CMP-004)


def test_ecriture_web_puis_bilan(client):
    data = _register(client)
    h = _headers(data["access_token"])
    r = client.post("/api/v1/ecritures", json={"type": "VENTE", "montant_cents": 25000}, headers=h)
    assert r.status_code == 200
    b = client.get("/api/v1/bilan", headers=h).json()
    assert b["ventes_cents"] == 25000
    assert b["solde_caisse_cents"] == 25000
    csv = client.get("/api/v1/ecritures/export.csv", headers=h)
    assert csv.status_code == 200
    assert "text/csv" in csv.headers["content-type"]


def test_parcours_vocal_vente_et_bilan(client):
    data = _register(client, "+22890000008")
    h = _headers(data["access_token"])

    r = client.post("/tools/ventes/proposer",
                    json={"quantite": 20, "prix_unitaire_cents": 5000}, headers=h)
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["montant_cents"] == 100000  # 20 x 50 F, calcul backend

    r = client.post("/tools/ecritures/confirmer",
                    json={"ecriture_id": body["data"]["ecriture_id"]}, headers=h)
    assert r.json()["ok"] is True

    b = client.get("/api/v1/bilan", headers=h).json()
    assert b["solde_caisse_cents"] == 100000

    accueil = client.post("/tools/accueil", json={}, headers=h).json()
    assert accueil["ok"] is True
    assert "Testa" in accueil["message"]
    assert accueil["data"]["solde_jour_cents"] == 100000


def test_vente_a_credit_cree_dette_puis_encaissement(client):
    data = _register(client, "+22890000009")
    h = _headers(data["access_token"])

    prop = client.post("/tools/ventes/proposer", json={
        "quantite": 1, "prix_unitaire_cents": 450000,
        "a_credit": True, "tiers_nom": "Koffi", "echeance": "2026-09-12",
    }, headers=h).json()
    assert prop["ok"] is True
    conf = client.post("/tools/ecritures/confirmer",
                       json={"ecriture_id": prop["data"]["ecriture_id"]}, headers=h).json()
    assert conf["ok"] is True
    assert "Dette client créée" in conf["message"]

    lister = client.get("/tools/dettes/lister", headers=h).json()
    assert lister["ok"] is True and len(lister["data"]["items"]) == 1
    dette_id = lister["data"]["items"][0]["id"]

    # Écriture liée à une dette active : annulation refusée (REQ-F-DET-009)
    annul = client.post("/tools/ecritures/annuler",
                        json={"ecriture_id": prop["data"]["ecriture_id"]}, headers=h).json()
    assert annul["ok"] is False

    enc = client.post("/tools/dettes/encaisser",
                      json={"dette_id": dette_id, "montant_cents": 450000}, headers=h).json()
    assert enc["ok"] is True
    lister2 = client.get("/tools/dettes/lister", headers=h).json()
    assert lister2["data"]["items"] == []  # dette payée

    # Garde-fou : la vente à crédit payée garde sa chaîne (dette + encaissement) ;
    # l'annulation reste refusée pour préserver la cohérence du registre.
    annul2 = client.post("/tools/ecritures/annuler",
                         json={"ecriture_id": prop["data"]["ecriture_id"]}, headers=h).json()
    assert annul2["ok"] is False


def test_depense_proposer_et_annulation_derniere(client):
    data = _register(client, "+22890000010")
    h = _headers(data["access_token"])
    prop = client.post("/tools/depenses/proposer",
                       json={"montant_cents": 60000, "libelle": "Transport"}, headers=h).json()
    assert prop["ok"] is True
    client.post("/tools/ecritures/confirmer",
                json={"ecriture_id": prop["data"]["ecriture_id"]}, headers=h)
    derniere = client.get("/tools/ecritures/derniere", headers=h).json()
    assert derniere["data"]["ecriture_id"] == prop["data"]["ecriture_id"]
    annul = client.post("/tools/ecritures/annuler",
                        json={"ecriture_id": prop["data"]["ecriture_id"]}, headers=h).json()
    assert annul["ok"] is True
    b = client.get("/api/v1/bilan", headers=h).json()
    assert b["solde_caisse_cents"] == 0


def test_epargne_et_dossier_outils(client):
    data = _register(client, "+22890000011")
    h = _headers(data["access_token"])
    client.post("/api/v1/ecritures", json={"type": "VENTE", "montant_cents": 100000}, headers=h)
    obj = client.post("/api/v1/epargne/objectifs",
                      json={"nom": "Réassort", "cible_cents": 500000}, headers=h).json()
    dep = client.post("/tools/epargne/deposer",
                      json={"objectif_id": obj["id"], "montant_cents": 25000}, headers=h).json()
    assert dep["ok"] is True
    dossier = client.post("/tools/dossier/generer", json={"mois": 3}, headers=h).json()
    assert dossier["ok"] is True
    d = client.post("/api/v1/dossier/generer", json={"mois": 6}, headers=h)
    assert d.status_code == 200 and "markdown" in d.json()


def test_outils_sans_jeton_refuses(client):
    assert client.get("/tools/ecritures/derniere").status_code == 401
    assert client.post("/tools/bilan", json={}).status_code == 401


def test_voix_token_sans_agent_configure(client):
    data = _register(client, "+22890000012")
    r = client.get("/api/v1/voix/token", headers=_headers(data["access_token"]))
    assert r.status_code == 503  # SIKA_AGENT_ID / clé non configurés en test
