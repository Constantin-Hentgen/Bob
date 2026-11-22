"""Couche des services voisins (Dora) : traduction des erreurs, état pour /health, déploiement."""
import re
import tomllib
from pathlib import Path

import httpx
import httpx2
import pytest
import yaml

from bob import services
from bob.services import Conflict, Invalid, NotFound, Unauthorized, Unavailable
from bob.services import dora as dora_service

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_status():
    services.STATUS.clear()
    yield
    services.STATUS.clear()


@pytest.mark.parametrize(("status", "cls"), [(401, Unauthorized), (404, NotFound), (409, Conflict), (422, Invalid),
                                             (400, Invalid), (503, Unavailable)])
def test_http_errors_become_service_errors(status, cls):
    from dora_routes.client import DoraError
    with pytest.raises(cls) as caught, dora_service.calls():
        raise DoraError(status, "must be positive")
    assert caught.value.service == "Dora" and caught.value.detail == "must be positive"


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"),
                                 httpx2.ConnectError("refused")])
def test_network_errors_mean_unavailable_and_mark_the_service_down(exc):
    with pytest.raises(Unavailable), dora_service.calls():
        raise exc
    assert services.STATUS["Dora"]["ok"] is False and services.STATUS["Dora"]["error"]


def test_a_normal_error_answer_still_means_the_service_is_up():
    from dora_routes.client import PlaceNotFoundError
    with pytest.raises(NotFound), dora_service.calls():
        raise PlaceNotFoundError(404, "no such place")
    assert services.STATUS["Dora"] == {"ok": True, "error": None, "at": services.STATUS["Dora"]["at"]}


def test_health_lists_only_the_configured_services(monkeypatch):
    from bob import app as app_module
    monkeypatch.setattr(dora_service, "enabled", lambda: False)
    assert app_module.services_health() == {}
    monkeypatch.setattr(dora_service, "enabled", lambda: True)
    assert app_module.services_health() == {"dora": {"ok": None, "error": None, "at": None}}
    with dora_service.calls():
        pass
    assert app_module.services_health()["dora"]["ok"] is True


def test_settings_default_to_the_stack_service_names(monkeypatch):
    from bob import config
    monkeypatch.delenv("DORA_URL", raising=False)
    assert config.Settings.from_env().dora_url == "http://dora:8000"
    monkeypatch.setenv("DORA_URL", "http://routes:9000/")
    assert config.Settings.from_env().dora_url == "http://routes:9000"


def test_no_food_service_is_left():
    """#94 : Bob ne parle plus ni à Remy ni à Emile ; rien dans le stack, les dépendances ni les réglages."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = " ".join(sources["project"]["dependencies"] + sources["dependency-groups"]["dev"]).lower()
    for name in ("remy", "emile"):
        assert name not in compose["services"] and name not in sources["tool"]["uv"]["sources"] and name not in deps
        assert f"{name}-data" not in (compose.get("volumes") or {})
    from bob import config
    assert not any("emile" in f or "remy" in f for f in config.Settings.__dataclass_fields__)
    assert not (ROOT / "bob" / "services" / "emile.py").exists() and not (ROOT / "bob" / "handlers" / "kitchen.py").exists()


def test_dora_and_its_router_are_built_from_the_client_version_and_stay_private():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["sources"]
    version = re.search(r"/v([\d.]+)\.tar\.gz$", sources["dora-routes"]["url"]).group(1)
    assert compose["dora"]["build"].endswith(f"#v{version}") and compose["dora"]["image"] == f"dora:{version}"
    assert compose["brouter"]["build"]["context"].endswith(f"#v{version}")
    segments = compose["segments"]   # télécharge puis reste « healthy » : le stack reste au vert
    assert "dora-segments --ok-if-present" in segments["command"][-1] and segments["healthcheck"]["test"][-1] == "/tmp/ready"
    assert compose["brouter"]["depends_on"]["segments"]["condition"] == "service_healthy"
    for name in ("dora", "brouter"):   # construites, jamais tirées : sinon « re-pull » de Portainer échoue
        assert compose[name]["pull_policy"] == "build"
    for name in ("dora", "brouter", "segments"):
        assert "ports" not in compose[name], f"{name} ne doit pas être publié sur l'hôte"
    assert "dora" in compose["bob"]["depends_on"]


def test_dora_errors_become_bob_service_errors():
    from dora_routes.client import DoraError, PlaceNotFoundError, ServiceUnavailableError
    for error, expected in ((PlaceNotFoundError(404, "no such place"), NotFound),
                            (ServiceUnavailableError(503, "BRouter down"), Unavailable),
                            (DoraError(422, "bad request"), Invalid)):
        with pytest.raises(expected), dora_service.calls():
            raise error
