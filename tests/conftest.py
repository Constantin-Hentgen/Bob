"""Remy et Emile pour les tests : les vraies applications, dans le processus, sur une base SQLite temporaire.

Bob parle à chaque service par son client typé ; ici ce client passe par un `TestClient` (aucun réseau). Chaque
application n'est créée qu'au premier appel d'un test : les tests sans nutrition ni cuisine n'en paient pas le coût.
"""
import datetime

import pytest
from fastapi.testclient import TestClient
from emile.client import Emile
from emile.service.app import create_app as create_emile_app
from emile.service.settings import Settings as EmileSettings
from remy.client import RemyClient
from remy.service.app import create_app
from remy.service.settings import Settings

from bob.services import STATUS
from bob.services import emile as emile_service
from bob.services import remy as remy_service

ADMIN_KEY = "bob-tests-admin-key"
# Horloge de Remy : après toutes les dates des tests (un repas « dans le futur » est refusé par Remy)
REMY_NOW = datetime.datetime(2027, 1, 1, 12, 0, tzinfo=datetime.UTC)


class LocalRemy:
    """Une instance de Remy propre à un test, avec l'athlète de Bob (Europe/Paris, français)."""

    def __init__(self, tmp_path):
        self._tmp_path = tmp_path
        self.app = None
        self.client: RemyClient | None = None

    def __call__(self) -> RemyClient:
        if self.client is None:
            settings = Settings(database_url=f"sqlite:///{self._tmp_path / 'remy.db'}", remy_admin_key=ADMIN_KEY,
                                remy_off_enabled=False, _env_file=None)
            self.app = create_app(settings)
            self.app.state.clock = lambda: REMY_NOW
            admin = TestClient(self.app, headers={"Authorization": f"Bearer {ADMIN_KEY}"})
            created = admin.post("/v1/admin/users", json={"name": "athlete", "timezone": "Europe/Paris", "lang": "fr"})
            assert created.status_code == 201, created.text
            key = created.json()["api_key"]["key"]
            self.client = RemyClient(http=TestClient(self.app, headers={"Authorization": f"Bearer {key}"}))
        return self.client

    def close(self) -> None:
        if self.app is not None:
            self.app.state.engine.dispose()


@pytest.fixture(autouse=True)
def remy(request, tmp_path, monkeypatch):
    """Chaque test a son Remy vide ; `remy()` donne le client typé, pour préparer ou vérifier des données.
    Les tests marqués `live` parlent aux vrais services (job CI « services ») : rien n'est remplacé."""
    if request.node.get_closest_marker("live"):
        yield None
        return
    local = LocalRemy(tmp_path)
    monkeypatch.setattr(remy_service, "client", local)
    monkeypatch.setattr(remy_service, "enabled", lambda: True)
    STATUS.clear()
    yield local
    local.close()


class LocalEmile:
    """Une instance d'Emile propre à un test : le foyer de Bob (Europe/Paris, français, 3 boîtes)."""

    def __init__(self, tmp_path, language="fr"):
        self._tmp_path = tmp_path
        self._language = language
        self.app = None
        self.client: Emile | None = None

    def __call__(self) -> Emile:
        if self.client is None:
            settings = EmileSettings(database_url=f"sqlite:///{self._tmp_path / 'emile.db'}", admin_key=ADMIN_KEY + "-emile",
                                     _env_file=None)
            self.app = create_emile_app(settings)
            with TestClient(self.app, headers={"Authorization": f"Bearer {settings.admin_key.get_secret_value()}"}) as admin:
                user = admin.post("/v1/admin/users", json={"name": "bob"}).json()
                key = admin.post(f"/v1/admin/users/{user['id']}/keys", json={}).json()["key"]
                made = admin.post("/v1/admin/households", json={"name": "Home", "timezone": "Europe/Paris", "language": self._language,
                                                                "meal_boxes": 3, "members": [user["id"]]})
                assert made.status_code == 201, made.text
            self.client = Emile("http://emile.test", key, http=TestClient(self.app))
        return self.client

    def close(self) -> None:
        if self.app is not None:
            self.app.state.db.engine.dispose()


@pytest.fixture(autouse=True)
def emile(request, tmp_path, monkeypatch):
    """Chaque test a son Emile vide ; `emile()` donne le client typé, pour préparer ou vérifier des données."""
    if request.node.get_closest_marker("live"):
        yield None
        return
    local = LocalEmile(tmp_path)
    monkeypatch.setattr(emile_service, "client", local)
    monkeypatch.setattr(emile_service, "enabled", lambda: True)
    yield local
    local.close()
