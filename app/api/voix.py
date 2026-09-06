"""Canal vocal navigateur — intégration Voice Agent API (docs browser-integration).

Flux :
1. L'utilisatrice s'authentifie (PIN) -> jeton Sika ;
2. Le front appelle GET /api/v1/voix/token (Bearer Sika) ;
3. Le serveur frappe AAI GET /v1/token (clé serveur, jamais exposée) ;
4. Le navigateur ouvre wss://agents.assemblyai.com/v1/ws?token=... et
   envoie session.update {session:{agent_id}} ;
5. Session terminée proprement via session.end (facturation au temps réel).

Exige SIKA_AGENT_ID (résultat de app.agent_publish) côté serveur.
"""
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..models import Compte, SessionVocale
from .deps import current_compte

router = APIRouter()

AGENTS_API = "https://agents.assemblyai.com"


@router.get("/api/v1/voix/token")
def voix_token(compte: Compte = Depends(current_compte), db: Session = Depends(get_db)):
    agent_id = os.environ.get("SIKA_AGENT_ID", "").strip()
    if not settings.assemblyai_api_key:
        raise HTTPException(status_code=503, detail="ASSEMBLYAI_API_KEY non configurée.")
    if not agent_id:
        raise HTTPException(status_code=503, detail="SIKA_AGENT_ID non configurée (python -m app.agent_publish).")
    try:
        resp = httpx.get(
            f"{AGENTS_API}/v1/token",
            params={"expires_in_seconds": 300, "max_session_duration_seconds": 3600},
            headers={"Authorization": settings.assemblyai_api_key},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Échec AAI : {exc}")
    token = resp.json().get("token")
    session = SessionVocale(compte_id=compte.id, session_aai_id="pending", canal="VOCAL_NAV", langue=compte.langue)
    db.add(session)
    db.flush()
    db.commit()
    return {"token": token, "agent_id": agent_id, "expires_in_seconds": 300}


_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sika — parler avec ta caisse</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem;background:#0f172a;color:#e2e8f0}
  button{background:#16a34a;color:#fff;border:0;border-radius:999px;padding:.8rem 1.4rem;font-size:1.1rem;cursor:pointer;margin:.4rem}
  button:disabled{opacity:.5;cursor:wait}
  #log{background:#1e293b;border-radius:12px;padding:1rem;min-height:220px;white-space:pre-wrap;font-size:.95rem}
  .ok{color:#4ade80}.user{color:#7dd3fc}.err{color:#f87171}
</style>
</head>
<body>
<h1>🗣️ Sika — ta caisse qui parle</h1>
<p>PIN du compte démo : <code>1234</code> (saisis-le ci-dessous pour ouvrir la session).</p>
<input id="pin" type="password" inputmode="numeric" placeholder="PIN" style="font-size:1.2rem;padding:.5rem">
<button id="login">Connexion</button>
<button id="start" disabled>Démarrer la conversation</button>
<button id="stop" disabled>Raccrocher</button>
<div id="status"></div>
<h3>Conversation</h3>
<pre id="log">Connecte-toi puis démarre la session vocale.</pre>
<script>
const log=(m,c='')=>{const el=document.getElementById('log');el.textContent+=m+'\\n';};
let ws=null, audioCtx=null, stream=null, playbackTime=0, ready=false, sikaToken='';

document.getElementById('login').onclick=async()=>{
  const pin=document.getElementById('pin').value;
  const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({telephone:'+22890000000',pin})});
  if(!r.ok){log('Échec connexion : PIN incorrect ?','err');return;}
  const data=await r.json(); sikaToken=data.access_token;
  log('Connectée. Prête pour l’appel.','ok');
  document.getElementById('start').disabled=false;
};

document.getElementById('start').onclick=async()=>{
  if(!sikaToken){log('Connecte-toi d’abord.','err');return;}
  const cfg=await fetch('/api/v1/voix/token',{headers:{Authorization:'Bearer '+sikaToken}}).then(r=>r.json());
  if(cfg.detail){log('Erreur serveur : '+JSON.stringify(cfg.detail),'err');return;}

  audioCtx=new AudioContext({sampleRate:24000});
  await audioCtx.audioWorklet.addModule('/pcm-processor.js');
  stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:false,sampleRate:24000}});
  const source=audioCtx.createMediaStreamSource(stream);
  const worklet=new AudioWorkletNode(audioCtx,'pcm-processor');
  source.connect(worklet).connect(audioCtx.destination);
  playbackTime=audioCtx.currentTime;

  const wsUrl=new URL('wss://agents.assemblyai.com/v1/ws');
  wsUrl.searchParams.set('token',cfg.token);
  ws=new WebSocket(wsUrl);
  worklet.port.onmessage=(e)=>{ if(ready&&ws.readyState===WebSocket.OPEN){
    const b64=btoa(String.fromCharCode(...new Uint8Array(e.data)));
    ws.send(JSON.stringify({type:'input.audio',audio:b64})); }};

  ws.onopen=()=>ws.send(JSON.stringify({type:'session.update',session:{agent_id:cfg.agent_id}}));
  ws.onmessage=(ev)=>{
    const msg=JSON.parse(ev.data);
    if(msg.type==='session.ready'){ready=true;log('Session prête — parle !','ok');
      document.getElementById('stop').disabled=false;}
    else if(msg.type==='reply.audio'){
      const raw=atob(msg.data); const pcm=new Int16Array(raw.length/2);
      for(let i=0;i<pcm.length;i++){pcm[i]=raw.charCodeAt(i*2)|(raw.charCodeAt(i*2+1)<<8);}
      const f=new Float32Array(pcm.length); for(let i=0;i<pcm.length;i++){f[i]=pcm[i]/32768;}
      const buf=audioCtx.createBuffer(1,f.length,24000); buf.getChannelData(0).set(f);
      const src=audioCtx.createBufferSource(); src.buffer=buf; src.connect(audioCtx.destination);
      const now=audioCtx.currentTime; playbackTime=Math.max(playbackTime,now);
      src.start(playbackTime); playbackTime+=buf.duration;
    }else if(msg.type==='reply.done'&&msg.status==='interrupted'){playbackTime=audioCtx.currentTime;}
    else if(msg.type==='transcript.user'){log('👩🏾‍💼 '+msg.text,'user');}
    else if(msg.type==='transcript.agent'){log('🤖 '+msg.text);}
    else if(msg.type==='session.error'||msg.type==='error'){log('Erreur : '+msg.message,'err');}
    else if(msg.type==='session.ended'){cleanup();log('Appel terminé.','ok');}
  };
  ws.onclose=()=>{ready=false;log('Connexion fermée.');};
};

document.getElementById('stop').onclick=()=>{ if(ws&&ws.readyState===WebSocket.OPEN){ws.send(JSON.stringify({type:'session.end'}));} };
window.addEventListener('pagehide',()=>{ if(ws&&ws.readyState===WebSocket.OPEN){ws.send(JSON.stringify({type:'session.end'}));} });

function cleanup(){ ws?.close(); stream?.getTracks().forEach(t=>t.stop()); audioCtx?.close(); ready=false; }
</script>
</body>
</html>
"""

_PCM = """class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input) {
      const pcm16 = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        pcm16[i] = Math.max(-32768, Math.min(32767, Math.round(input[i] * 32767)));
      }
      this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
"""


@router.get("/voix")
def page_voix():
    return Response(content=_PAGE, media_type="text/html")


@router.get("/pcm-processor.js")
def worklet():
    return Response(content=_PCM, media_type="application/javascript")
