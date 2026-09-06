"""Rate limiting simple en mémoire (REQ-NF-SEC-006).

Limite : 45 requêtes/min/IP sur les chemins sensibles (auth + outils vocaux),
120 requêtes/min/IP ailleurs. Suffisant pour le MVP ; à remplacer par un
stockage partagé (Redis) en multi-instance.
"""
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

SENSIBLE_PREFIXES = ("/api/v1/auth", "/tools")
LIMITE_SENSIBLE = 45
LIMITE_GENERALE = 120
FENETRE = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._tickets: dict[str, deque] = defaultdict(deque)

    def _autorise(self, cle: str, limite: int) -> bool:
        maintenant = time.monotonic()
        file = self._tickets[cle]
        while file and maintenant - file[0] > FENETRE:
            file.popleft()
        if len(file) >= limite:
            return False
        file.append(maintenant)
        return True

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "inconnu"
        chemin = request.url.path
        limite = LIMITE_SENSIBLE if chemin.startswith(SENSIBLE_PREFIXES) else LIMITE_GENERALE
        if not self._autorise(f"{ip}:{chemin.split('/')[1]}", limite):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429,
                content={"detail": "Trop de requêtes. Réessayez dans une minute."},
            )
        return await call_next(request)
