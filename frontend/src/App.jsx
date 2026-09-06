import React, { useEffect, useState } from 'react';

const API = '';
const TOKEN_KEY = 'sika_token';
const CENTS = 100;

const fmtFcfa = (cents) => {
  const valeur = Math.round(Math.abs(cents || 0) / CENTS);
  return `${valeur.toLocaleString('fr-FR').replace(/\u202f/g, ' ')} FCFA`;
};

const signe = (type) =>
  ['VENTE', 'PAIEMENT_RECU'].includes(type) ? '+' : '-';

function api(path, options = {}) {
  return fetch(`${API}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(localStorage.getItem(TOKEN_KEY)
        ? { Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` }
        : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
}

function Login({ onLogin }) {
  const [pin, setPin] = useState('');
  const [erreur, setErreur] = useState('');
  const [chargement, setChargement] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setChargement(true);
    setErreur('');
    try {
      const r = await api('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({ telephone: '+22890000000', pin }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Connexion refusée');
      localStorage.setItem(TOKEN_KEY, data.access_token);
      onLogin(data.compte);
    } catch (err) {
      setErreur(err.message);
    } finally {
      setChargement(false);
    }
  };

  return (
    <div className="centre">
      <h1>🗣️ Sika</h1>
      <p className="sous-titre">Ta caisse qui parle — tableau de bord</p>
      <form onSubmit={submit} className="carte login">
        <input
          type="password" inputMode="numeric" maxLength={6} placeholder="PIN (démo : 1234)"
          value={pin} onChange={(e) => setPin(e.target.value)} autoFocus
        />
        {erreur && <p className="erreur">{erreur}</p>}
        <button type="submit" disabled={chargement || pin.length < 4}>
          {chargement ? '…' : 'Se connecter'}
        </button>
        <a className="lien" href="/voix" target="_blank" rel="noreferrer">
          🎙️ Essayer la version vocale (agent Sika)
        </a>
      </form>
    </div>
  );
}

function Carte({ titre, valeur, detail, accent }) {
  return (
    <div className={`carte carte-stat ${accent || ''}`}>
      <div className="stat-titre">{titre}</div>
      <div className="stat-valeur">{valeur}</div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

function Dashboard({ compte, onLogout }) {
  const [bilan, setBilan] = useState(null);
  const [ecritures, setEcritures] = useState([]);
  const [dettes, setDettes] = useState([]);
  const [dossierMd, setDossierMd] = useState('');
  const [note, setNote] = useState('');

  const charger = async () => {
    const [b, e, d] = await Promise.all([
      api('/api/v1/bilan').then((r) => r.json()),
      api('/api/v1/ecritures?limit=50').then((r) => r.json()),
      api('/api/v1/dettes').then((r) => r.json()),
    ]);
    setBilan(b);
    setEcritures(e.items);
    setDettes(d.items);
  };

  useEffect(() => {
    charger();
  }, []);

  const annuler = async (id) => {
    if (!window.confirm('Annuler cette opération ? (écriture d’ajustement tracée)')) return;
    const r = await api(`/api/v1/ecritures/${id}/annuler`, { method: 'POST' });
    setNote(r.ok ? 'Opération annulée.' : 'Annulation refusée : dette liée active.');
    charger();
  };

  const genererDossier = async () => {
    const r = await api('/api/v1/dossier/generer', { method: 'POST', body: JSON.stringify({ mois: 3 }) });
    const data = await r.json();
    setDossierMd(data.markdown || JSON.stringify(data));
  };

  const encaisserRegler = async (d) => {
    const f = window.prompt(
      `${d.sens === 'CLIENT' ? 'Encaisser' : 'Régler'} sur ${d.tiers_nom} — reste dû : ${fmtFcfa(d.reste_du_cents)}\nMontant en FCFA :`
    );
    if (!f) return;
    const cents = Math.round(Number(f.replace(/\s/g, '')) * 100);
    if (!cents || cents <= 0) return;
    const route = d.sens === 'CLIENT' ? 'encaisser' : 'regler';
    const r = await api(`/api/v1/dettes/${d.id}/${route}`, {
      method: 'POST',
      body: JSON.stringify({ montant_cents: cents }),
    });
    setNote(r.ok ? 'Paiement enregistré.' : (await r.json()).detail || 'Échec.');
    charger();
  };

  const relancer = async (d) => {
    if (!window.confirm(`Envoyer une relance à ${d.tiers_nom} (${fmtFcfa(d.reste_du_cents)}) ?`)) return;
    const r = await api(`/api/v1/dettes/${d.id}/relancer`, { method: 'POST', body: '{}' });
    setNote(r.ok ? 'Relance envoyée.' : (await r.json()).detail || 'Échec.');
    charger();
  };

  const telechargerCsv = async () => {
    const r = await api('/api/v1/ecritures/export.csv');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'sika_ecritures.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <header className="barre">
        <strong>🗣️ Sika — {compte.prenom}</strong>
        <span className="filler" />
        <a className="lien" href="/voix" target="_blank" rel="noreferrer">🎙️ Parler à Sika</a>
        <button className="ghost" onClick={onLogout}>Déconnexion</button>
      </header>

      {note && <p className="note">{note}</p>}

      {bilan && (
        <section className="grille">
          <Carte titre="Solde du jour" valeur={fmtFcfa(bilan.solde_caisse_cents)} accent="vert" />
          <Carte titre="Ventes" valeur={fmtFcfa(bilan.ventes_cents)} />
          <Carte titre="Dépenses" valeur={fmtFcfa(bilan.depenses_cents)} />
          <Carte titre="Créances clients" valeur={`${bilan.dettes_clients_actives.nb}`}
            detail={fmtFcfa(bilan.dettes_clients_actives.reste_du_cents)} />
        </section>
      )}

      <section className="rangée">
        <div className="carte bloc">
          <h2>Dernières opérations</h2>
          {ecritures.length === 0 && <p>Aucune opération.</p>}
          <ul className="liste">
            {ecritures.map((e) => (
              <li key={e.id} className={e.statut === 'ANNULEE' ? 'barre-rouge' : ''}>
                <span className={`montant ${e.statut === 'ANNULEE' ? 'gris' : ''}`}>
                  {signe(e.type)} {fmtFcfa(e.montant_cents)}
                </span>
                <span className="libelle">{e.libelle || e.type} <small>({e.statut})</small></span>
                <span className="filler" />
                {e.statut === 'CONFIRMEE' && (
                  <button className="ghost petit" onClick={() => annuler(e.id)}>Annuler</button>
                )}
              </li>
            ))}
          </ul>
          <button className="ghost petit" onClick={telechargerCsv}>⬇️ Exporter CSV</button>
        </div>

        <div className="carte bloc">
          <h2>Dettes en cours</h2>
          {dettes.length === 0 && <p>Aucune dette active. ✅</p>}
          <ul className="liste">
            {dettes.map((d) => (
              <li key={d.id}>
                <span className={`montant ${d.sens === 'FOURNISSEUR' ? 'rouge' : 'vert'}`}>
                  {fmtFcfa(d.reste_du_cents)}
                </span>
                <span className="libelle">
                  {d.sens === 'CLIENT' ? '👤 ' : '🏪 '}
                  {d.tiers_nom}
                  {d.relançable ? ' · 🔔 relançable' : ''} <small>({d.statut})</small>
                </span>
                <button className="ghost petit" onClick={() => encaisserRegler(d)}>
                  {d.sens === 'CLIENT' ? 'Encaisser' : 'Régler'}
                </button>
                {d.relançable && (
                  <button className="ghost petit" onClick={() => relancer(d)}>Relancer</button>
                )}
              </li>
            ))}
          </ul>
          <h2>Dossier de crédit</h2>
          <button onClick={genererDossier}>Générer le dossier (3 mois)</button>
          {dossierMd && <pre className="md">{dossierMd}</pre>}
        </div>
      </section>
    </div>
  );
}

export default function App() {
  const [compte, setCompte] = useState(null);

  useEffect(() => {
    if (localStorage.getItem(TOKEN_KEY)) {
      api('/api/v1/compte/me')
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then(setCompte)
        .catch(() => localStorage.removeItem(TOKEN_KEY));
    }
  }, []);

  return compte ? (
    <Dashboard
      compte={compte}
      onLogout={() => {
        localStorage.removeItem(TOKEN_KEY);
        setCompte(null);
      }}
    />
  ) : (
    <Login onLogin={setCompte} />
  );
}
