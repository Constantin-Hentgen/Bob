import datetime

import pytest

from bob import weather_alerts as wa
from bob.config import TZ, settings
from bob.weather_alerts import Hour


def at(day, hour, minute=0):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def hourly(day, rain_hours=(), prob=80, mm=1.2, temp=12.0, feels=None, gust=20.0, code=3, **by_hour):
    """Prévision horaire sur 24 h : pluie aux heures listées, sec ailleurs ; `by_hour` surcharge une heure."""
    hours = []
    for h in range(24):
        rainy = h in rain_hours
        hour = Hour(at(day, h), prob if rainy else 5, mm if rainy else 0.0, temp, feels if feels is not None else temp, gust, code)
        for field, value in by_hour.get(f"h{h}", {}).items():
            setattr(hour, field, value)
        hours.append(hour)
    return hours


def event(uid, start, end, summary="Footing", **extra):
    return {"uid": uid, "summary": summary, "start": start.isoformat(), "end": end.isoformat(), "description": "", **extra}


@pytest.fixture(autouse=True)
def alert_settings():
    values = {"rain_probability": 60, "rain_min_mm": 0.3, "rain_skip_keywords": ["repos", "rest", "off"],
              "heat_alert_c": 28.0, "gust_alert_kmh": 50.0, "freeze_alert_c": 1.0}
    saved = {k: getattr(settings, k) for k in values}
    for k, v in values.items():
        object.__setattr__(settings, k, v)
    yield
    for k, v in saved.items():
        object.__setattr__(settings, k, v)


NOW = at(10, 8)
FORECASTS = {"Maison": hourly(10, {18, 19}), "Travail": hourly(10)}


def hazards(forecast, start=at(10, 18), end=at(10, 19)):
    cond = wa.conditions(forecast, start, end)
    return cond.hazards() if cond else {}


def test_rain_on_the_slot_only_where_it_rains():
    assert set(hazards(FORECASTS["Maison"], at(10, 18, 30), at(10, 19, 30))) == {"pluie"}
    assert hazards(FORECASTS["Travail"]) == {}


def test_heat_wind_and_ice_hazards():
    assert set(hazards(hourly(10, feels=31.0))) == {"chaleur"}
    assert set(hazards(hourly(10, gust=65.0))) == {"vent"}
    assert set(hazards(hourly(10, temp=-1.0, h7={"mm": 0.5}))) == {"verglas"}   # sol mouillé dans les 12 h avant
    assert hazards(hourly(10, temp=-1.0)) == {}                                  # froid mais sec : pas de verglas
    assert set(hazards(hourly(10, temp=0.5, code=73))) == {"verglas"}            # neige


@pytest.mark.parametrize("ev", [
    event("rest", at(10, 8), at(10, 23), summary="Repos"),                 # mot-clé + trop long
    event("rest2", at(10, 18), at(10, 19), summary="Jour OFF"),           # mot-clé
    event("allday", at(10, 0), at(11, 0), summary="Trail", all_day=True), # journée entière
])
def test_non_training_events_are_ignored(ev):
    assert wa.session_lines([ev], {"Maison": hourly(10, set(range(24)))}, NOW) == []


def test_keyword_is_matched_as_whole_word():
    ev = event("c", at(10, 18), at(10, 19), summary="Footing depuis l'office")
    assert len(wa.session_lines([ev], FORECASTS, NOW)) == 1


def test_thresholds():
    assert hazards(hourly(10, {18}, prob=90, mm=0.1)) == {}   # probable mais négligeable
    assert hazards(hourly(10, {18}, prob=30, mm=2.0)) == {}   # abondant mais improbable


def test_place_resolution():
    places = ["Maison", "Travail"]
    assert wa.resolve_place({"location": "travail"}, places) == "Travail"
    assert wa.resolve_place({"summary": "Fractionné au Travail"}, places) == "Travail"
    assert wa.resolve_place({"summary": "Footing"}, places) == "Maison"


# --- Météo heure par heure (#41) --------------------------------------------

def test_night_rain_does_not_mark_an_evening_session_wet():
    from bob import weather
    night_rain = {"Maison": hourly(10, {2, 3, 4}, mm=2.0), "Travail": hourly(10)}
    lines = wa.session_lines([event("a", at(10, 18), at(10, 19), location="Maison")], night_rain, NOW)
    assert len(lines) == 1 and "Maison) : sec" in lines[0] and "pluie" not in lines[0]
    assert weather.rain_spans(night_rain["Maison"], datetime.date(2026, 11, 10)) == [(2, 5, 6.0)]
    assert weather.format_spans([(2, 5, 6.0), (17, 18, 0.4)]) == "02h–05h (6 mm), 17h–18h (0.4 mm)"


def test_session_lines_rain_on_the_slot_skips_rest_and_past_sessions():
    events = [event("a", at(10, 18), at(10, 19)),                       # pluie 18-19h à la maison
              event("b", at(10, 12), at(10, 13), summary="Repos"),       # pas une séance
              event("c", at(10, 6), at(10, 7))]                          # déjà passée
    lines = wa.session_lines(events, FORECASTS, NOW)
    assert len(lines) == 1
    assert lines[0].startswith("Footing (") and "☔ pluie 80 %, 1.2 mm" in lines[0] and lines[0].count("pluie") == 1


def test_forecast_text_lists_rain_hours_and_sessions():
    from bob import weather
    saved = settings.weather_locations
    object.__setattr__(settings, "weather_locations", [("Maison", 48.8, 2.3)])
    try:
        _check_forecast_text(weather)
    finally:
        object.__setattr__(settings, "weather_locations", saved)


def _check_forecast_text(weather):
    daily = {"time": ["2026-11-10"], "weathercode": [61], "temperature_2m_min": [4.0], "temperature_2m_max": [11.0],
             "precipitation_sum": [2.4], "precipitation_probability_max": [80], "windspeed_10m_max": [20.0]}
    text = weather.forecast_text(([daily], {"Maison": FORECASTS["Maison"]}),
                                 [event("a", at(10, 18), at(10, 19))], NOW)
    assert "pluie 2.4 mm (80 %) : 18h–20h (2.4 mm)" in text
    assert "Sur tes séances" in text and "Footing (" in text
    dry = weather.forecast_text(([daily], {"Maison": hourly(10)}), [], NOW)
    assert "sec heure par heure" in dry and "Sur tes séances" not in dry
    assert weather.forecast_text(None) == "non configurée"
