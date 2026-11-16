"""Remy pour les tests : la vraie application Remy, dans le processus, sur une base SQLite temporaire.

Bob parle à Remy par son client typé ; ici ce client passe par un `TestClient` (aucun réseau). L'application n'est
créée qu'au premier appel d'un test : les tests sans nutrition n'en paient pas le coût.
"""
import datetime

import pytest
from fastapi.testclient import TestClient
from remy.client import RemyClient
from remy.service.app import create_app
from remy.service.settings import Settings

from bob.services import STATUS
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
