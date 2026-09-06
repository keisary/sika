# 🗣️ Sika — le livre de caisse qui parle

Assistant vocal multilingue **(FR / EN / PT / ES)** de tenue de caisse pour micro-entrepreneurs du secteur informel : ventes, dépenses, dettes, épargne et bilans — **saisis à la voix**, sans clavier, sans savoir lire ou écrire. Conçu pour le hackathon **AssemblyAI Voice Agent Hackathon** (LabLab.ai, sept. 2026).

> Documentation de référence : `Sika_Cahier-des-charges_SRS_v1.0.md` (racine du dépôt) — SRS ISO/IEC/IEEE 29148:2018, 152 exigences traçables.

## Pourquoi Sika

86,3 % de l'emploi en Afrique subsaharienne est informel (ILO) ; 87,9 % au Togo (INSEED). Les institutions de microfinance exigent de « justifier de revenus stables » et « démontrer sa capacité de remboursement » (FUCEC-TOGO) — preuves que l'informel ne peut pas produire, faute d'enregistrement. **Sika crée cet enregistrement par la voix** et le transforme en **dossier de crédit exportable** (« historique bancable »).

## Fonctionnalités (V1)

- **Canal vocal** (Voice Agent API AssemblyAI) : enregistrement des ventes/dépenses avec **confirmation orale systématique**, dettes clients/fournisseurs avec échéances, épargne programmée, bilan parlé, relances sur validation, dossier de crédit ;
- **Multilingue** FR/EN/PT/ES avec code-switching natif (langues d'entrée *et* de sortie supportées par la plateforme) ;
- **Intégrité** : tous les calculs sont faits par le backend, jamais par le LLM ; écritures PROVISOIRE → CONFIRMEE après confirmation ; annulations tracées par écriture d'ajustement ; journal d'audit ;
- **Dashboard web** (React) : solde, opérations, dettes, épargne, export CSV, génération du dossier de crédit ;
- **Multi-tenant** strict (isolation par compte), montants en centimes (BIGINT), horodatage UTC.

## Architecture

```
Navigateur (dashboard React / page vocale /voix)
   │ REST + Bearer          │ WSS (jeton AAI éphémère, clé jamais exposée)
   ▼                         ▼
FastAPI (API + /tools) ◄── HTTP tools (outils serveur) ──► AssemblyAI
   │                              Voice Agent API (STT U-3.5 Pro + voix estelle)
PostgreSQL ◄── Alembic            LLM Gateway (cerveau conversationnel)
Worker (recaps, relances) ──► fournisseur WhatsApp/SMS (console en dev)
```

## Démarrage local

Prérequis : Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env        # puis renseigner ASSEMBLYAI_API_KEY si dispo
uv sync                     # installe le backend (.venv)
uv run alembic upgrade head # applique le schéma (SQLite local par défaut)
uv run python -m app.seed --sample   # compte démo Aïcha / +22890000000 / PIN 1234
uv run uvicorn app.main:app --reload --port 8000

# Frontend (autre terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Tests : `uv run pytest` (35 tests : services, bornes, isolation tenant, audit, parcours API/outils vocaux).

## Canal vocal (AssemblyAI)

1. **Publier l'agent** (une fois le backend déployé sur une URL publique — AAI refuse les hôtes privés) :
   ```bash
   uv run python -m app.agent_publish --url https://<votre-app>.onrender.com
   ```
   Le script crée l'agent (`agent/sika.agent.jsonc` : prompt, voix `estelle`, 13 outils HTTP), substitue l'URL et un **jeton d'outil** (compte démo, 90 j, stocké hors git) puis enregistre `SIKA_AGENT_ID`.
2. **Configurer** `SIKA_AGENT_ID` (et `ASSEMBLYAI_API_KEY`) sur l'environnement d'exécution.
3. **Parler à Sika** : page `/voix` (canal navigateur, clé AAI jamais exposée — jetons éphémères 5 min) ou le playground AAI. Le canal téléphonique Twilio/SIP est prévu en V2.

## Sécurité (points clés)

- La clé API AssemblyAI vit uniquement côté serveur (`.env`, jamais commitée) ;
- Jetons navigateur AAI éphémères et à usage unique ; jetons applicatifs HMAC signés ;
- PIN hachés (PBKDF2), jamais en clair ; audit append-only ; effacement RGPD complet ;
- Données vocales = données personnelles : conservation minimale, consentement.

## Licence

MIT — voir `LICENSE`. Le cahier des charges (SRS) reste la référence contractuelle du périmètre V1.
