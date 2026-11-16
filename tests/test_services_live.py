"""Bob face aux vrais Remy et Emile (job CI « services », BOB_LIVE_SERVICES=1) : clés, versions et erreurs."""
import os

import pytest

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not os.getenv("BOB_LIVE_SERVICES"), reason="services réels non démarrés")]


@pytest.fixture(scope="module")
def adapters():
    from bob.services import emile, remy
    remy.client.cache_clear()
    emile.client.cache_clear()
    return remy, emile


def test_both_services_answer_with_bobs_keys(adapters):
    remy, emile = adapters
    assert remy.enabled() and emile.enabled()
    assert remy.ping() and emile.ping()


def test_errors_come_back_as_bob_service_errors(adapters):
    from bob.services import NotFound
    remy, emile = adapters
    with emile.calls():
        assert emile.client().current_list() is None   # aucune liste encore : pas une erreur
    with pytest.raises(NotFound), remy.calls():
        remy.client().delete_meal(999_999)


def test_a_wrong_key_is_reported_as_unauthorized(adapters):
    from emile.client import Emile
    from remy.client import RemyClient

    from bob.config import settings
    from bob.services import Unauthorized
    remy, emile = adapters
    with pytest.raises(Unauthorized), remy.calls():
        RemyClient(settings.remy_url, "remy_wrong").profile()
    with pytest.raises(Unauthorized), emile.calls():
        Emile(settings.emile_url, "emile_wrong").me()


def test_bob_nutrition_round_trip_on_the_real_remy(adapters):
    import datetime

    from bob import nutrition
    from bob.config import TZ
    at = datetime.datetime.now(TZ) - datetime.timedelta(hours=1)
    meal, dup, unmatched = nutrition.log_meal("Riz poulet", at, items=[{"food": "riz blanc cuit", "grams": 200}])
    assert dup is None and not unmatched and meal["kcal"] > 0
    again, dup, __ = nutrition.log_meal("Riz poulet", at)
    assert again is None and dup["id"] == meal["id"]                       # doublon : rien de gardé
    assert [m["id"] for m in nutrition.meals_since(at.date())] == [meal["id"]]
    snap = nutrition.snapshot([], at.date())
    assert snap.today.meals == 1 and "profil incomplet" in nutrition.energy_context(snap, at.date())
    assert nutrition.remove_meal(meal["id"])["text"] == "Riz poulet"
