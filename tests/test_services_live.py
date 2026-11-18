"""Bob face aux vrais Emile et Dora (job CI « services », BOB_LIVE_SERVICES=1) : clés, versions et erreurs."""
import os

import pytest

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not os.getenv("BOB_LIVE_SERVICES"), reason="services réels non démarrés")]


@pytest.fixture(scope="module")
def adapters():
    from bob.services import emile
    emile.client.cache_clear()
    return emile


def test_emile_answers_with_bobs_key(adapters):
    emile = adapters
    assert emile.enabled() and emile.ping()


def test_errors_come_back_as_bob_service_errors(adapters):
    from bob.services import NotFound
    emile = adapters
    with emile.calls():
        assert emile.client().current_list() is None   # aucune liste encore : pas une erreur
    with pytest.raises(NotFound), emile.calls():
        emile.client().edit_list(check=["Riz"])         # rien à modifier sans liste en cours


def test_a_wrong_key_is_reported_as_unauthorized(adapters):
    from emile.client import Emile

    from bob.config import settings
    from bob.services import Unauthorized
    emile = adapters
    with pytest.raises(Unauthorized), emile.calls():
        Emile(settings.emile_url, "emile_wrong").me()


def test_bob_kitchen_round_trip_on_the_real_emile(adapters):
    from bob.handlers.ui import shopping_markup, shopping_text
    from bob.services import Conflict
    emile = adapters
    with emile.calls():
        kitchen = emile.client()
        first = kitchen.create_list([{"name": "Riz", "quantity": "500 g", "aisle": "🍚 Féculents"}, {"name": "Œufs"}], days=7)
        second = kitchen.create_list([{"name": "Pâtes"}])                       # remplace la première : ses boutons sont périmés
    assert "0/1" in shopping_text(second) and shopping_markup(second).inline_keyboard[-1][0].callback_data == f"s:r:{second.id}"
    with pytest.raises(Conflict), emile.calls():
        kitchen.toggle(first.id, 0)
    with emile.calls():
        assert kitchen.toggle(second.id, 0).items[0].done                       # coché = acheté



def test_dora_answers_and_reports_its_router_honestly():
    """Dora tourne sans BRouter dans la CI : il le dit dans sa santé, et une demande de boucles est « indisponible »,
    jamais une liste vide qui ferait croire qu'il n'y a pas de boucle."""
    from bob.services import Unavailable
    from bob.services import dora
    dora.client.cache_clear()
    assert dora.enabled() and "BRouter INJOIGNABLE" in dora.ping()
    with pytest.raises(Unavailable), dora.calls():
        dora.client().find_loops(start={"lat": 48.84, "lon": 2.44}, distance_km=8, lang="fr")
