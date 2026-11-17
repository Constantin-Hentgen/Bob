"""Boucles de course : choix du lieu et de la distance depuis la séance ou les arguments. Le tracé lui-même (BRouter,
« jamais faite », sélection, GPX, carte, légendes) est le travail de Dora, testé dans son dépôt ; ce que Bob lui
demande et ce qu'il fait de la réponse est testé dans test_bot_features.py (/newroute)."""
from bob import commands

PLACES = [("maison", 48.80, 2.30), ("travail", 48.85, 2.35)]


def test_route_request_uses_todays_session_then_arguments():
    run = {"summary": "🏃 Footing facile 6,5 km", "location": "Travail"}
    assert commands.route_request([], PLACES, [run]) == ("travail", (48.85, 2.35), 6.5)
    assert commands.route_request(["maison", "10"], PLACES, [run]) == ("maison", (48.80, 2.30), 10.0)
    assert commands.route_request(["8km"], PLACES, []) == ("maison", (48.80, 2.30), 8.0)   # pas de séance : 1er lieu
    assert commands.route_request(["90"], PLACES, [])[2] == 30.0                         # bornée


def test_parse_route_args_distance_surface_and_free_text_place():
    ask = commands.parse_route_args(["10", "route", "à", "bois", "de", "vincennes"], PLACES)
    assert (ask.km, ask.surface, ask.place, ask.query) == (10.0, "route", None, "bois de vincennes")
    ask = commands.parse_route_args(["trail", "travail", "8km"], PLACES)
    assert (ask.km, ask.surface, ask.place, ask.query) == (8.0, "nature", ("travail", 48.85, 2.35), "")
    ask = commands.parse_route_args([], PLACES)
    assert (ask.km, ask.surface, ask.place, ask.query) == (None, None, None, "")


def test_fill_from_session_uses_next_session_place_or_address():
    import datetime
    from bob.config import TZ
    now = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=TZ)
    done = {"summary": "🏃 Footing 5 km", "location": "maison", "start": "2026-11-10T07:00:00+01:00", "end": "2026-11-10T08:00:00+01:00"}
    later = {"summary": "🏃 Sortie longue 14 km", "location": "Parc de Sceaux", "start": "2026-11-11T09:00:00+01:00",
             "end": "2026-11-11T10:30:00+01:00"}
    ask = commands.fill_from_session(commands.parse_route_args([], PLACES), PLACES, [done, later], now)
    assert (ask.km, ask.query, ask.place) == (14.0, "Parc de Sceaux", None)     # séance passée ignorée ; adresse à géocoder
    forced = commands.fill_from_session(commands.parse_route_args(["travail", "6"], PLACES), PLACES, [later], now)
    assert (forced.km, forced.place[0], forced.query) == (6.0, "travail", "")    # ce qui est donné l'emporte


def test_next_session_skips_summaries_bib_pickups_and_races():
    week = {"summary": "📊 S47 20km", "start": "2026-11-16T08:00:00+01:00", "end": "2026-11-16T08:30:00+01:00"}
    bib = {"summary": "🎽 Retrait dossard — veille 10km des Lumières", "start": "2026-11-16T09:00:00+01:00",
           "end": "2026-11-16T09:30:00+01:00"}
    race = {"summary": "🏁 COURSE 10km des Lumières", "start": "2026-11-16T10:00:00+01:00", "end": "2026-11-16T11:00:00+01:00"}
    rest = {"summary": "🧘 Récup post-course", "start": "2026-11-16T11:00:00+01:00", "end": "2026-11-16T11:30:00+01:00"}
    run = {"summary": "🏃 4,5 km faciles + 4 lignes droites", "location": "Travail",
           "start": "2026-11-17T12:00:00+01:00", "end": "2026-11-17T13:00:00+01:00"}
    assert commands.next_session([week, bib, race, rest, run]) is run
    ask = commands.fill_from_session(commands.RouteAsk(), PLACES, [week, bib, race, rest, run])
    assert (ask.km, ask.place[0], ask.session) == (4.5, "travail", run)
    assert commands.session_line(run).startswith("Pour ta séance de mardi 12:00 (🏃 4,5 km faciles")
    given = commands.fill_from_session(commands.RouteAsk(place=PLACES[0], km=8.0), PLACES, [run])
    assert given.session is None   # tout est donné : la séance n'y est pour rien


def test_session_distance_from_description_or_duration_and_pace():
    assert commands.session_km({"summary": "🏃 Footing", "description": "🏃 Footing facile 6,5 km\n⏱ 45 min"}) == 6.5
    assert commands.session_km({"summary": "🏃 Footing 45 min", "description": "allure 7:00-7:30/km"}) == 6.2
    assert commands.session_km({"summary": "🏃 Footing 39 min", "description": "Échauffement 15 min"}) == 6.0
    assert commands.session_km({"summary": "🏃 Fractionné", "description": "Échauffement 15 min"}) is None
