"""Emile pour les tests : la vraie application, dans le processus, sur une base SQLite temporaire ; Dora simulé.

Bob parle à chaque service par son client typé ; ici ce client passe par un `TestClient` (aucun réseau). L'application
n'est créée qu'au premier appel d'un test : les tests sans cuisine n'en paient pas le coût.
"""
import pytest
from fastapi.testclient import TestClient
from emile.client import Emile
from emile.service.app import create_app as create_emile_app
from emile.service.settings import Settings as EmileSettings

from bob.services import STATUS
from bob.services import emile as emile_service

ADMIN_KEY = "bob-tests-admin-key"


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
    """Chaque test a son Emile vide ; `emile()` donne le client typé, pour préparer ou vérifier des données.
    Les tests marqués `live` parlent aux vrais services (job CI « services ») : rien n'est remplacé."""
    if request.node.get_closest_marker("live"):
        yield None
        return
    local = LocalEmile(tmp_path)
    monkeypatch.setattr(emile_service, "client", local)
    monkeypatch.setattr(emile_service, "enabled", lambda: True)
    STATUS.clear()
    yield local
    local.close()


class FakeDora:
    """Dora sans BRouter : le vrai client typé, branché sur une réponse préparée par le test (`loops`, `status`).
    `requests` garde le corps JSON de chaque appel, tel que Dora le reçoit."""

    def __init__(self):
        self.requests: list[dict] = []
        self.loops: list[dict] = [fake_loop()]
        self.place: dict | None = None
        self.status = 200

    def __call__(self):
        import httpx
        from dora_routes.client import DoraClient

        def handle(request: httpx.Request) -> httpx.Response:
            import json
            body = json.loads(request.content)
            self.requests.append(body)
            if self.status != 200:
                return httpx.Response(self.status, json={"detail": "fake error"})
            start = body.get("start") or {"lat": self.place["lat"], "lon": self.place["lon"]}
            return httpx.Response(200, json={"start": start, "place": self.place, "target_km": body["distance_km"],
                                             "loops": self.loops})
        return DoraClient("http://dora.test", transport=httpx.MockTransport(handle))


def fake_loop(km=10.1, caption="10,1 km · 70 % bitume · 3 traversées", novelty=None, n=1) -> dict:
    """Une boucle comme Dora la renvoie avec ?include=gpx&include=png."""
    import base64
    return {"id": f"loop{n}", "distance_km": km, "climb_m": 12, "bearing": 90.0,
            "shares": {"deserted": 0.5, "paved": 0.7, "crowded": 0.1, "busy": 0.0, "marked": 0.0},
            "crossings": 3, "novelty": novelty, "caption": caption,
            "geojson": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[2.3, 48.8], [2.31, 48.81]]}},
            "gpx_url": f"http://dora.test/v1/loops/loop{n}.gpx", "png_url": f"http://dora.test/v1/loops/loop{n}.png",
            "gpx_base64": base64.b64encode(b"<gpx/>").decode(), "png_base64": base64.b64encode(b"png").decode()}


@pytest.fixture
def dora(monkeypatch):
    """Faux Dora pour les tests de /routes et /newroute."""
    from bob.services import dora as dora_service
    fake = FakeDora()
    monkeypatch.setattr(dora_service, "client", fake)
    return fake
