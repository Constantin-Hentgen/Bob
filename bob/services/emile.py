"""Emile : liste de courses, recettes, boîtes repas (nombre) et agenda courses
(https://github.com/Constantin-Hentgen/Emile).

`client()` renvoie le client typé d'Emile (`emile.client.Emile`) ; tout appel se fait dans `with calls():`, qui
traduit ses erreurs en `bob.services.ServiceError` (avec le code stable d'Emile : `stale_list`, `no_current_list`…).
"""
import contextlib
import functools

from emile.client import ApiError, Emile

from ..config import settings
from . import NotConfigured, error_for, translate

NAME = "Emile"


def enabled() -> bool:
    return settings.emile_enabled


def url() -> str:
    return settings.emile_url


@functools.cache
def client() -> Emile:
    """Client partagé (une connexion HTTP réutilisée), créé au premier appel."""
    if not enabled():
        raise NotConfigured(NAME, "EMILE_API_KEY manquante")
    return Emile(settings.emile_url, settings.emile_api_key, timeout=settings.http_timeout)


def calls() -> contextlib.AbstractContextManager[None]:
    """Contexte de tout appel : erreurs traduites en `ServiceError`, état noté pour /health."""
    return translate(NAME, ApiError, lambda e: error_for(NAME, e.status, e.detail, code=e.error))


def ping() -> str:
    """Vérifie l'accès avec la clé de Bob (foyer de la clé) ; message court pour les journaux."""
    with calls():
        household = client().household()
    return f"foyer « {household.name} »"
