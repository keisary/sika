# Déploiement Render (niveaux gratuits)

Deux services + une base PostgreSQL gratuits (render.yaml fourni).

## Option A — Blueprint automatique (recommandée)

1. Pousser ce dépôt sur GitHub ;
2. Sur Render : **New → Blueprint** → sélectionner le dépôt ;
3. Render crée : `sika-web` (API + page /voix), `sika-worker` (tâches planifiées) et `sika-db` (PostgreSQL) ;
4. Renseigner les variables d'environnement suivantes (Blueprint → Environment) :
   - `SIKA_SECRET_KEY` (longue, aléatoire)
   - `ASSEMBLYAI_API_KEY`
   - `SIKA_AGENT_ID` (après publication de l'agent, cf. ci-dessous)
   - `SIKA_SEED_PIN` (PIN du compte démo ; changer avant toute mise en avant publique)
   - `DATABASE_URL` (fournie automatiquement par le Blueprint)
5. Premier démarrage : le web service applique les migrations et crée le compte démo (`Aïcha`, téléphone `+22890000000`).

## Option B — Manuel

- **Web service** : repo root, Dockerfile fourni, `Health Check Path: /healthz`, plan Free.
- **Worker** : même repo/Dockerfile, commande de démarrage `uv run python -m worker.run`.
- **PostgreSQL** : instance Free, copier la `Internal Database URL` dans `DATABASE_URL` des deux services.

## Après le déploiement — brancher la voix

1. Depuis la machine locale, publier l'agent pointant vers l'URL publique :
   ```bash
   uv run python -m app.agent_publish --url https://<votre-app>.onrender.com
   ```
2. Copier l'`id` affiché (ou lire `.agent_id`) dans la variable `SIKA_AGENT_ID` du web service ;
3. Redémarrer le service (les outils HTTP de l'agent appellent `/tools/*` sur cette URL avec le jeton d'outil).

## Vérification

- `GET /healthz` → `{"status":"ok"}`
- `POST /api/v1/auth/login` `{telephone:"+22890000000", pin:"<SIKA_SEED_PIN>"}` → jeton
- Ouvrir `/voix` dans Chrome/Edge et parler à l'agent (démo : « j'ai vendu 20 sachets à 50 F », puis « bilan du jour »).

## Limites connues (V1)

- Fournisseur WhatsApp/SMS en mode `console` (aucun SMS réel) tant qu'un agrégateur n'est pas configuré ;
- Agent vocal mono-compte démo (jeton d'outil lié au compte Aïcha) — multi-utilisateurs : V2 (jeton par session) ;
- L'arabe est reconnu en entrée mais pas encore en sortie vocale (choix V1 : FR/EN/PT/ES).
