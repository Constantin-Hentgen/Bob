"""Remy : journal des repas, profil, besoins et bilans nutritionnels (https://github.com/Constantin-Hentgen/Remy).

`client()` renvoie le client typé de Remy (`remy.client.RemyClient`) ; tout appel se fait dans `with calls():`,
qui traduit ses erreurs en `bob.services.ServiceError`.
"""
import contextlib
import functools

from remy.client import RemyClient, RemyError

from ..config import settings
from . import NotConfigured, error_for, translate

NAME = "Remy"


def enabled() -> bool:
    return settings.remy_enabled


def url() -> str:
    return settings.remy_url


@functools.cache
def client() -> RemyClient:
    """Client partagé (une connexion HTTP réutilisée), créé au premier appel."""
    if not enabled():
        raise NotConfigured(NAME, "REMY_API_KEY manquante")
    return RemyClient(settings.remy_url, settings.remy_api_key, timeout=settings.http_timeout)


def calls() -> contextlib.AbstractContextManager[None]:
    """Contexte de tout appel : erreurs traduites en `ServiceError`, état noté pour /health."""
    return translate(NAME, RemyError, lambda e: error_for(NAME, e.status_code, e.detail))


def ping() -> str:
    """Vérifie l'accès avec la clé de Bob (lecture du profil) ; message court pour les journaux."""
    with calls():
        profile = client().profile()
    return f"profil {'renseigné' if profile.weight_kg else 'vide'}"
