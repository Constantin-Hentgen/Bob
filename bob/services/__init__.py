"""Services voisins de Bob, dans le même stack Docker : Remy (nutrition), Emile (courses), Dora (boucles).

Chaque service a son module (`remy`, `emile`, `dora`) qui expose un client typé, construit une fois depuis la configuration.
Le reste de Bob n'appelle jamais leur HTTP directement et ne voit qu'un seul modèle d'erreur :

    from bob.services import ServiceError, Unavailable
    from bob.services import remy

    try:
        with remy.calls():
            day = remy.client().day("today")
    except Unavailable:
        ...   # « Remy ne répond pas » : ne jamais faire comme si c'était enregistré

`calls()` traduit les exceptions propres à chaque client (codes HTTP, réseau) en sous-classes de `ServiceError` et
note l'état du service dans `STATUS` (affiché par /health).
"""
import contextlib
import datetime
from collections.abc import Callable, Iterator

import httpx
import httpx2


class ServiceError(Exception):
    """Échec d'un appel à un service voisin. `service` : « Remy »… ; `code` : code d'erreur stable du service s'il en
    donne un (`stale_list`…), sinon le statut HTTP ; `detail` : texte lisible, sans secret."""

    def __init__(self, service: str, detail: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(f"{service} : {detail}")
        self.service, self.detail, self.status, self.code = service, detail, status, code or (str(status) if status else None)


class NotConfigured(ServiceError):
    """Le service n'est pas configuré (URL ou clé d'API absente)."""


class Unavailable(ServiceError):
    """Service injoignable, trop lent ou en erreur interne (réseau, 5xx) : rien n'a été fait."""


class Unauthorized(ServiceError):
    """Clé d'API refusée (401/403) : mauvaise clé ou clé révoquée."""


class NotFound(ServiceError):
    """La ressource n'existe pas (404)."""


class Conflict(ServiceError):
    """L'état a changé entre-temps (409), par exemple une liste de courses remplacée."""


class Invalid(ServiceError):
    """Requête refusée (400/422) : `detail` explique pourquoi ; rien n'a été modifié."""


def error_for(service: str, status: int, detail: object, code: str | None = None) -> ServiceError:
    """L'exception `ServiceError` qui correspond à une réponse d'erreur HTTP."""
    cls = (Unauthorized if status in (401, 403) else NotFound if status == 404 else Conflict if status == 409
           else Invalid if status in (400, 422) else Unavailable if status >= 500 or status == 429 else ServiceError)
    return cls(service, _text(detail), status=status, code=code)


def _text(detail: object) -> str:
    if isinstance(detail, list):   # erreurs de validation FastAPI : [{"loc": [...], "msg": "..."}]
        return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)[:300]
    return str(detail)[:300]


# Dernier état connu de chaque service (démarrage puis chaque appel) : affiché par /health, sans requête de plus.
STATUS: dict[str, dict[str, object]] = {}


def record(service: str, error: ServiceError | None = None) -> None:
    """Note l'issue d'un appel. Un 404, 409 ou 422 est une réponse normale : le service va bien."""
    down = isinstance(error, (Unavailable, Unauthorized, NotConfigured))
    STATUS[service] = {"ok": not down, "error": error.detail if down else None,
                       "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")}


@contextlib.contextmanager
def translate(service: str, client_error: type[Exception], convert: Callable[[Exception], ServiceError]) -> Iterator[None]:
    """Traduit les erreurs du client du service (`client_error`, via `convert`) et du réseau (httpx, httpx2) en
    `ServiceError`, et note l'état du service."""
    try:
        yield
    except ServiceError as e:
        record(service, e)
        raise
    except client_error as e:
        error = convert(e)
        record(service, error)
        raise error from e
    except (httpx.TimeoutException, httpx2.TimeoutException) as e:
        error = Unavailable(service, f"pas de réponse à temps ({type(e).__name__})")
        record(service, error)
        raise error from e
    except (httpx.TransportError, httpx2.TransportError) as e:
        error = Unavailable(service, f"injoignable ({type(e).__name__})")
        record(service, error)
        raise error from e
    else:
        record(service)
