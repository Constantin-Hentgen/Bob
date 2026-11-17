"""Couche des services voisins (Remy, Emile) : traduction des erreurs, état pour /health, déploiement."""
import re
import tomllib
from pathlib import Path

import httpx
import httpx2
import pytest
import yaml
from emile.client import ApiError
from remy.client import RemyError

from bob import services
from bob.services import Conflict, Invalid, NotConfigured, NotFound, Unauthorized, Unavailable
from bob.services import dora as dora_service
from bob.services import emile as emile_service
from bob.services import remy as remy_service

ROOT = Path(__file__).resolve().parent.parent
REAL_REMY_CLIENT = remy_service.client   # avant que conftest.py ne le remplace par un Remy local


@pytest.fixture(autouse=True)
def _clean_status():
    services.STATUS.clear()
    yield
    services.STATUS.clear()


@pytest.mark.parametrize(("status", "cls"), [(401, Unauthorized), (403, Unauthorized), (404, NotFound),
                                             (409, Conflict), (422, Invalid), (400, Invalid), (503, Unavailable)])
def test_remy_http_errors_become_service_errors(status, cls):
    with pytest.raises(cls) as caught, remy_service.calls():
        raise RemyError(status, [{"loc": ["body", "grams"], "msg": "must be positive"}])
    assert caught.value.service == "Remy" and caught.value.detail == "must be positive"


def test_emile_errors_keep_their_stable_code():
    with pytest.raises(Conflict) as caught, emile_service.calls():
        raise ApiError(409, "stale_list", "the list was replaced")
    assert caught.value.code == "stale_list" and caught.value.detail == "the list was replaced"


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"),
                                 httpx2.ConnectError("refused")])
def test_network_errors_mean_unavailable_and_mark_the_service_down(exc):
    with pytest.raises(Unavailable), remy_service.calls():
        raise exc
    assert services.STATUS["Remy"]["ok"] is False and services.STATUS["Remy"]["error"]


def test_a_normal_error_answer_still_means_the_service_is_up():
    with pytest.raises(NotFound), emile_service.calls():
        raise ApiError(404, "no_current_list", "no list yet")
    assert services.STATUS["Emile"] == {"ok": True, "error": None, "at": services.STATUS["Emile"]["at"]}
    with remy_service.calls():
        pass
    assert services.STATUS["Remy"]["ok"] is True


def test_a_service_without_api_key_is_not_configured(monkeypatch):
    monkeypatch.setattr(remy_service, "enabled", lambda: False)
    REAL_REMY_CLIENT.cache_clear()
    with pytest.raises(NotConfigured), remy_service.calls():
        REAL_REMY_CLIENT()


def test_health_lists_only_the_configured_services(monkeypatch):
    from bob import app as app_module
    monkeypatch.setattr(remy_service, "enabled", lambda: True)
    monkeypatch.setattr(emile_service, "enabled", lambda: False)
    monkeypatch.setattr(dora_service, "enabled", lambda: False)
    assert app_module.services_health() == {"remy": {"ok": None, "error": None, "at": None}}
    with remy_service.calls():
        pass
    assert app_module.services_health()["remy"]["ok"] is True


def test_settings_default_to_the_stack_service_names(monkeypatch):
    from bob import config
    for name in ("REMY_URL", "REMY_API_KEY", "EMILE_URL", "EMILE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    s = config.Settings.from_env()
    assert (s.remy_url, s.emile_url) == ("http://remy:8000", "http://emile:8000")
    assert not s.remy_enabled and not s.emile_enabled
    monkeypatch.setenv("REMY_API_KEY", "remy_x")
    monkeypatch.setenv("EMILE_URL", "http://groceries:9000/")
    s = config.Settings.from_env()
    assert s.remy_enabled and s.emile_url == "http://groceries:9000"


def test_compose_runs_the_services_privately_at_the_client_versions():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["sources"]
    for name in ("remy", "emile"):
        service = compose[name]
        assert "ports" not in service, f"{name} ne doit pas être publié sur l'hôte"
        image_version = service["image"].rsplit(":", 1)[1]
        client_version = re.search(r"/v([\d.]+)\.tar\.gz$", sources[name]["url"]).group(1)
        assert image_version == client_version, f"{name} : image {image_version} ≠ client {client_version}"
        assert name in compose["bob"]["depends_on"]


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
