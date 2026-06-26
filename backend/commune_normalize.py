"""Normalisation commune administrative / localisation d'agence (Phase 4).

La presse cite souvent un quartier, un bourg ou un lieu-dit ("Coëtquidan")
alors que la commune administrative est différente ("Guer"). La BAN fournit le
rattachement officiel : on conserve la commune administrative comme `commune`,
et on garde la mention d'origine dans `agence_localisation` / `commune_originale`.

La clé d'événement (`closure_id`) utilise alors commune administrative + banque
+ localisation, ce qui désambiguïse deux agences d'une même commune sans
fusionner abusivement.
"""
from __future__ import annotations

from backend.dedup import closure_id, normalise_cle


def appliquer(closure: dict, geo: dict | None) -> dict:
    """Rattache la fermeture à la commune administrative de la BAN.

    Best-effort : sans géo, ou si la BAN confirme déjà la commune, le dict est
    renvoyé inchangé (hors champs déjà présents).
    """
    if not geo:
        return closure
    admin = geo.get("commune")
    original = closure.get("commune")
    if not admin or not original:
        return closure
    if normalise_cle(admin) == normalise_cle(original):
        return closure

    # Désambiguïsateur pour l'id : adresse précise si connue, sinon localisation.
    desambig = closure.get("adresse") or original
    closure["agence_localisation"] = original
    closure["commune_originale"] = original
    closure["commune"] = admin
    closure["id"] = closure_id(closure["banque"], admin, closure["type"], adresse=desambig)
    return closure
