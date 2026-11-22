"""Bob face au vrai Dora (job CI « services », BOB_LIVE_SERVICES=1) : version et erreurs."""
import os

import pytest

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not os.getenv("BOB_LIVE_SERVICES"), reason="services réels non démarrés")]


def test_dora_answers_and_reports_its_router_honestly():
    """Dora tourne sans BRouter dans la CI : il le dit dans sa santé, et une demande de boucles est « indisponible »,
    jamais une liste vide qui ferait croire qu'il n'y a pas de boucle."""
    from bob.services import Unavailable
    from bob.services import dora
    dora.client.cache_clear()
    assert dora.enabled() and "BRouter INJOIGNABLE" in dora.ping()
    with pytest.raises(Unavailable), dora.calls():
        dora.client().find_loops(start={"lat": 48.84, "lon": 2.44}, distance_km=8, lang="fr")
