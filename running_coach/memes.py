"""Mèmes de réaction cultes : ceux que tout le monde s'envoie (Reddit, Twitter, Discord), pas des GIF au hasard.

Un GIF fait rire quand on reconnaît le mème ET qu'il colle pile à la situation. Le coach choisit donc dans ce
catalogue au lieu de décrire une scène en mots-clés (ce qui ramenait des GIF génériques). Chaque mème pointe vers des
GIF GIPHY précis, choisis et vérifiés à la main (la version canonique du mème) : pas de recherche, pas de surprise.
S'il ne trouve pas de mème qui colle : pas de GIF.
"""

import random

from .config import settings

MEDIA_URL = "https://media.giphy.com/media/{id}/giphy.mp4"   # MP4 léger (< 2 Mo), lu par Telegram comme un GIF


# id → (quand l'envoyer, GIF GIPHY de ce mème, langue du bot requise ou None)
MEMES: dict[str, tuple[str, list[str], str | None]] = {
    "this_is_fine": ("tout part en vrille mais on fait comme si de rien n'était : déluge le jour de la sortie longue, "
                     "semaine surchargée, frigo vide, chaos", ["9M5jK4GXmD5o1irGrF", "QMHoU66sBXqqLqYvGO"], None),
    "leo_cheers": ("félicitations : record, objectif atteint, séance clé réussie, semaine bouclée",
                   ["yziuK6WtDFMly", "QMkPpxPDYY0fu", "8Iv5lqKwKsZ2g"], None),
    "success_kid": ("petite victoire du quotidien : levé à l'heure, séance faite malgré la flemme, tups prêts",
                    ["6brH8dM3zeMyA"], None),
    "homer_bushes": ("séance esquivée en douce, retour discret après plusieurs jours sans nouvelles",
                     ["lGqCfaLbpv28xE4vc3", "jUwpNzg9IcyrK", "xfAgILDksDJJu"], None),
    "forrest_gump": ("il ne s'arrête plus de courir : grosse série de jours, volume énorme, sortie très longue",
                     ["9rRacglGbs68E", "KEXxJgir4BxFZ7bYsC", "YRPFyXxSrnwqRsrHFf"], None),
    "phoebe_running": ("footing joyeux et sans pression, courir n'importe comment mais heureux",
                       ["DdkR5dtHkwGrK", "w99LKRX7fpclO"], None),
    "spongebob_tired": ("complètement rincé, jambes en bois après une grosse séance ou une course",
                        ["3o6wO0TfTg6qQKiHcs", "l4FBcipb88dc5nxh6", "3ofSBnYbEPePeigIMg"], None),
    "surprised_pikachu": ("conséquence prévisible qui surprend quand même : courbatures après avoir forcé, "
                          "fringale après avoir sauté un repas", ["6nWhy3ulBL7GSCvKw6", "3kzJvEciJa94SMW3hN"], None),
    "gandalf_shall_not_pass": ("repos imposé : pas de séance aujourd'hui, on bloque le surentraînement",
                               ["njYrp176NQsHS", "P726XW1pK3Luo"], None),
    "drake_hotline_bling": ("dédain amusé pour une mauvaise option : le fractionné sous la grêle, la salade sans rien",
                            ["3o85xosW6qQsCsZ3Ve"], None),
    "michael_scott_no": ("refus catégorique et dramatique : courir sous la grêle, remplacer les pâtes par du céleri",
                         ["hyyV7pnbE0FqLNBAzs", "6gLyE15StAs3C", "SAXIrMi5Glnby"], None),
    "rocky_training": ("motivation avant une séance dure ou une course, mode guerrier",
                       ["382KHGeAfisOk", "1wXberbwfS4rKW8Uxo"], None),
    "terminator_back": ("retour après une pause, une blessure ou des vacances", ["RfEbMBTPQ7MOY", "JDKxRN0Bvmm2c"], None),
    "over_9000": ("chiffre énorme : kilomètres, dénivelé, calories, tups cuisinés", ["9YijTMczuJFhjjuJE8", "ixYRj3H9HOzWE"], None),
    "mind_blown": ("stat ou progrès bluffant : allure qui chute, VMA en hausse", ["SDogLD4FOZMM8"], None),
    "deal_with_it": ("record ou course réussie avec assurance, la classe", ["qrwthQPPQrtEk", "Nx2Lx1RmLadtC"], None),
    "rock_eyebrow": ("sceptique : plan ambitieux, excuse douteuse, « juste un petit carré de chocolat »",
                     ["ACZqfCpSGhG8h6HRV6", "xUOxf34uHq8VolxF7y"], None),
    "just_do_it": ("pousser à y aller quand il hésite ou repousse la séance",
                   ["jndc0TQq9fvK8", "24xRxrDCLxhT2", "UqZ4imFIoljlr5O2sM"], None),
    "joey_food": ("on ne touche pas à sa nourriture, gros repas mérité, trop mangé, faim de loup après la sortie",
                  ["3ohc0VvRxWciBmE6wE", "zm0wMAolIdDvG", "ToMjGpQirN8FU0BZibC"], None),
    "homer_drool": ("envie irrésistible de manger, plat qui fait saliver", ["12N4jTCSVRyKje", "ZIaHApfoneZZ6"], None),
    "baby_yoda_sip": ("récupération tranquille, jour de repos savouré, chill",
                      ["Wn74RUT0vjnoU98Hnt", "TIdrdXLCIbLGAazGyL", "4k4pxbTamKLLxE3HXT"], None),
    "confused_travolta": ("perdu : séance introuvable, plus de tups, on cherche où courir",
                          ["sU511xfb7ORqw", "6uGhT1O4sxpi8"], None),
    "side_eye_monkey": ("situation gênante : séance ratée qu'on préfère ne pas commenter, excuse bancale",
                        ["WRuBiZKB6xgsS9DrFA", "H5C8CevNMbpBqNqFjl"], None),
    "crying_jordan": ("petite déception à dédramatiser : objectif manqué de peu, séance annulée par la pluie",
                      ["O5LNujPh9G58SehmTP", "3o6EhNnoVpx2LbfVnO"], None),
    "mr_bean_waiting": ("attendre : que la pluie s'arrête, que le run se synchronise, que les pâtes cuisent",
                        ["QBd2kLB5qDmysEXre9", "huOJB3RmQpx2FGt4Se"], None),
    "minions_celebrate": ("joie explosive, bonne nouvelle, la semaine s'annonce top", ["1MTLxzwvOnvmE", "pX8pS6MIvtH7ues1Vq"], None),
    "kaamelott_pas_faux": ("répondre à une explication trop technique (zones, VMA, macros) qu'on n'a pas comprise",
                           ["XknChYwfPnp04"], "fr"),
}


def available() -> dict[str, tuple[str, list[str], str | None]]:
    """Les mèmes compréhensibles dans la langue du bot (Kaamelott ne parle qu'aux francophones)."""
    return {k: v for k, v in MEMES.items() if v[2] in (None, settings.language)}


def catalogue() -> str:
    """Liste lue par le modèle : « id : quand »."""
    return "\n".join(f"- {key} : {when}" for key, (when, __, __) in available().items())


def url(meme: str) -> str:
    """Une des versions canoniques du mème (au hasard, pour varier)."""
    return MEDIA_URL.format(id=random.choice(MEMES[meme][1]))
