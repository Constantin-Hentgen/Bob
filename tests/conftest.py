"""Dora simulé pour les tests : le vrai client typé, branché sur une réponse préparée par le test."""
import pytest

from bob.services import STATUS


@pytest.fixture(autouse=True)
def clean_service_status():
    STATUS.clear()


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
