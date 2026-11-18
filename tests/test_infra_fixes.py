"""Écritures CalDAV vérifiées, parsing BRouter, budget de temps des boucles, docs FastAPI, défauts de config."""
import datetime
import threading

import pytest
from caldav.lib.error import NotFoundError

from bob import calendar_store as cs
from bob.config import UTC

H = datetime.timedelta(hours=1)


class Obj:
    def __init__(self, cal, uid, data):
        self.cal, self.uid, self.data = cal, uid, data

    def save(self):
        self.cal.store[self.uid] = self.cal.mangle(self.data)

    def delete(self):
        if not self.cal.keep_on_delete:
            self.cal.store.pop(self.uid, None)


class FakeCal:
    """Agenda en mémoire ; `mangle` permet de simuler une écriture perdue côté serveur."""
    def __init__(self):
        self.store, self.keep_on_delete, self.mangle = {}, False, lambda d: d

    def add_event(self, ics):
        uid = next(l[4:] for l in ics.splitlines() if l.startswith("UID:"))
        self.store[uid] = self.mangle(ics)

    def get_event_by_uid(self, uid):
        if uid not in self.store:
            raise NotFoundError(uid)
        return Obj(self, uid, self.store[uid])

    def search(self, **_):
        return [Obj(self, u, d) for u, d in self.store.items()]


@pytest.fixture
def cal(monkeypatch):
    fake = FakeCal()
    monkeypatch.setattr(cs, "get_calendar", lambda: fake)
    return fake


def future(hours=24):
    return (cs.now_utc() + datetime.timedelta(hours=hours)).replace(microsecond=0)


def test_create_returns_uid_and_read_back_times(cal):
    s = future()
    res = cs.create_event("Sortie", s, s + H, None)
    assert res["uid"].endswith("@running-coach") and res["uid"] in cal.store
    assert abs((res["start"] - s).total_seconds()) < 1 and abs((res["end"] - s - H).total_seconds()) < 1


def test_create_refuses_past_and_bad_range(cal):
    past = cs.now_utc() - datetime.timedelta(days=2)
    with pytest.raises(ValueError, match="passé"):
        cs.create_event("x", past, past + H, None)
    s = future()
    with pytest.raises(ValueError, match="postérieur"):
        cs.create_event("x", s, s, None)
    assert not cal.store


def test_create_readback_mismatch_raises(cal):
    s = future()
    cal.mangle = lambda d: d.replace(f"DTSTART:{s:%Y%m%dT%H%M%S}Z", f"DTSTART:{s + 3 * H:%Y%m%dT%H%M%S}Z")   # début décalé
    with pytest.raises(RuntimeError):
        cs.create_event("x", s, s + H, None)


def test_update_keeps_duration_and_bumps_sequence(cal):
    s = future()
    uid = cs.create_event("Sortie", s, s + 2 * H, None)["uid"]
    new = s + datetime.timedelta(hours=5)
    res = cs.update_event(uid, start=new)
    assert abs((res["start"] - new).total_seconds()) < 1
    assert abs((res["end"] - res["start"] - 2 * H).total_seconds()) < 1
    assert int(cs.parse_vevent(cal.store[uid])[1]["SEQUENCE"]) == 1
    cs.update_event(uid, summary="Fractionné")
    assert int(cs.parse_vevent(cal.store[uid])[1]["SEQUENCE"]) == 2


def test_update_past_event_refused(cal):
    past = cs.now_utc() - datetime.timedelta(days=2)
    uid = "old@running-coach"
    cal.add_event(cs.build_event(uid, "Vieux", past, past + H, "x"))
    with pytest.raises(PermissionError):
        cs.update_event(uid, summary="Nouveau")
    with pytest.raises(LookupError):
        cs.update_event("inconnu@x", summary="a")


def test_update_readback_mismatch_raises(cal):
    s = future()
    uid = cs.create_event("Sortie", s, s + H, None)["uid"]
    cal.mangle = lambda d: d.replace("Fractionné", "Sortie")   # titre perdu côté serveur
    with pytest.raises(RuntimeError, match="titre"):
        cs.update_event(uid, summary="Fractionné")


def test_delete_removes_and_verifies(cal):
    s = future()
    uid = cs.create_event("Sortie", s, s + H, None)["uid"]
    res = cs.delete_event(uid)
    assert res["uid"] == uid and uid not in cal.store


def test_delete_still_present_raises(cal):
    s = future()
    uid = cs.create_event("Sortie", s, s + H, None)["uid"]
    cal.keep_on_delete = True
    with pytest.raises(RuntimeError, match="toujours présent"):
        cs.delete_event(uid)


def test_delete_past_event_refused(cal):
    past = cs.now_utc() - datetime.timedelta(days=2)
    cal.add_event(cs.build_event("old@running-coach", "Vieux", past, past + H, "x"))
    with pytest.raises(PermissionError):
        cs.delete_event("old@running-coach")
    assert "old@running-coach" in cal.store


def test_calendar_client_is_per_thread(monkeypatch):
    made = []

    class Client:
        def __init__(self, **kw):
            made.append(self)

        def calendar(self, url):
            return object()

    monkeypatch.setattr(cs.caldav, "DAVClient", Client)
    monkeypatch.setattr(cs, "_local", threading.local())
    a = cs.get_calendar()
    assert cs.get_calendar() is a
    seen = []
    t = threading.Thread(target=lambda: seen.append(cs.get_calendar()))
    t.start()
    t.join()
    assert seen[0] is not a and len(made) == 2


# --- App et config -----------------------------------------------------------

def test_app_docs_disabled():
    from bob.app import app
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None


