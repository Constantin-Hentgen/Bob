"""Dora : boucles de course autour d'un lieu, avec carte et GPX (https://github.com/Constantin-Hentgen/Dora).

`client()` renvoie le client typé de Dora (`dora_routes.DoraClient`) ; tout appel se fait dans `with calls():`, qui
traduit ses erreurs en `bob.services.ServiceError` (lieu introuvable : `NotFound` ; BRouter ou géocodeur hors service :
`Unavailable`). Dora ne garde rien entre deux requêtes : pas de clé d'API.
"""
import contextlib
import functools

from dora_routes.client import DoraClient, DoraError

from ..config import settings
from . import NotConfigured, error_for, translate

NAME = "Dora"
TIMEOUT_S = 60.0   # un peu plus que le budget de Dora (45 s) pour tracer les boucles


def enabled() -> bool:
    return bool(settings.dora_url)


def url() -> str:
    return settings.dora_url


@functools.cache
def client() -> DoraClient:
    """Client partagé (une connexion HTTP réutilisée), créé au premier appel."""
    if not enabled():
        raise NotConfigured(NAME, "DORA_URL vide")
    return DoraClient(settings.dora_url, timeout=TIMEOUT_S)


def calls() -> contextlib.AbstractContextManager[None]:
    """Contexte de tout appel : erreurs traduites en `ServiceError`, état noté pour /health."""
    return translate(NAME, DoraError, lambda e: error_for(NAME, e.status_code, e.detail))


def ping() -> str:
    """Vérifie que Dora répond et que son BRouter est joignable ; message court pour les journaux."""
    with calls():
        health = client().health()
    return f"v{health.get('version')}, BRouter {'joignable' if health.get('brouter', {}).get('reachable') else 'INJOIGNABLE'}"
