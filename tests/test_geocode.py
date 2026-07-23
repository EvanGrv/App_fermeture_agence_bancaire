from backend import geocode

BAN_OK = {"features": [
    {"geometry": {"coordinates": [-1.6778, 48.1173]},
     "properties": {"city": "Rennes", "citycode": "35238", "postcode": "35000"}}
]}
BAN_VIDE = {"features": []}
BAN_VILLEPINTE = {"features": [
    {"geometry": {"coordinates": [2.54, 48.96]},
     "properties": {"city": "Villepinte", "name": "Villepinte",
                    "citycode": "93078", "postcode": "93420"}},
    {"geometry": {"coordinates": [2.09, 43.28]},
     "properties": {"city": "Villepinte", "name": "Villepinte",
                    "citycode": "11434", "postcode": "11150"}},
]}


def test_parse_ban():
    r = geocode.parse_ban(BAN_OK)
    assert r["lat"] == 48.1173 and r["lon"] == -1.6778
    assert r["code_insee"] == "35238"
    assert r["departement"] == "35"


def test_parse_ban_derive_drom():
    payload = {"features": [{"geometry": {"coordinates": [55.45, -20.88]},
                             "properties": {"citycode": "97411", "postcode": "97400"}}]}
    assert geocode.parse_ban(payload)["departement"] == "974"


def test_parse_ban_vide():
    assert geocode.parse_ban(BAN_VIDE) is None


def test_geocode_utilise_cache():
    appels = []
    def fetch(url):
        appels.append(url)
        return BAN_OK
    cache = {}
    a = geocode.geocode_commune("Rennes", "35", fetch=fetch, cache=cache)
    b = geocode.geocode_commune("Rennes", "35", fetch=fetch, cache=cache)
    assert a == b
    assert a["departement"] == "35"
    assert len(appels) == 1  # second appel servi par le cache


def test_geocode_echec_retourne_none():
    res = geocode.geocode_commune("Xyz", "99", fetch=lambda url: BAN_VIDE, cache={})
    assert res is None


def test_geocode_refuse_commune_homonyme_sans_departement():
    geo = geocode.geocode_commune(
        "Villepinte", fetch=lambda _url: BAN_VILLEPINTE, cache={}
    )
    assert geo["ambiguous"] is True
    assert {item["departement"] for item in geo["candidates"]} == {"11", "93"}


def test_geocode_resout_commune_homonyme_avec_departement_source():
    geo = geocode.geocode_commune(
        "Villepinte", "11", fetch=lambda _url: BAN_VILLEPINTE, cache={}
    )
    assert geo["code_insee"] == "11434"
    assert geo["departement"] == "11"


def test_geocode_adresse():
    r = geocode.geocode_adresse("11 rue des Alliés, 24360 Piégut-Pluviers",
                                fetch=lambda url: BAN_OK, cache={})
    assert r["lat"] == 48.1173 and r["lon"] == -1.6778
    assert r["departement"] == "35"  # dérivé du citycode de la réponse simulée


def test_geocode_adresse_cache():
    appels = []
    def fetch(url):
        appels.append(url)
        return BAN_OK
    cache = {}
    geocode.geocode_adresse("1 rue X", fetch=fetch, cache=cache)
    geocode.geocode_adresse("1 rue X", fetch=fetch, cache=cache)
    assert len(appels) == 1


# --- Fallback municipality -> recherche large (Coëtquidan -> Guer) -----------

BAN_GUER = {"features": [
    {"geometry": {"coordinates": [-2.1167, 47.9167]},
     "properties": {"name": "Coëtquidan", "city": "Guer",
                    "citycode": "56075", "postcode": "56380"}}
]}


def _fetch_coetquidan(url):
    # La recherche municipality échoue (Coëtquidan n'est pas une commune),
    # mais la recherche large rattache à la commune administrative Guer.
    if "type=municipality" in url:
        return BAN_VIDE
    return BAN_GUER


def test_geocode_commune_ou_lieu_fallback_rattache_commune_administrative():
    geo = geocode.geocode_commune_ou_lieu(
        "Coëtquidan", "56", fetch=_fetch_coetquidan, cache={})
    assert geo is not None
    assert geo["commune"] == "Guer"
    assert geo["code_insee"] == "56075"
    assert geo["departement"] == "56"


def test_geocode_commune_ou_lieu_municipality_prioritaire():
    # Quand la commune existe en municipality, pas de fallback.
    appels = []
    def fetch(url):
        appels.append(url)
        return BAN_OK
    geo = geocode.geocode_commune_ou_lieu("Rennes", "35", fetch=fetch, cache={})
    assert geo["commune"] == "Rennes"
    assert all("type=municipality" in u for u in appels)


def test_geocode_commune_ou_lieu_tente_prefixe_prudent_avant_recherche_large():
    appels = []

    def fetch(url):
        appels.append(url)
        if "q=Guer" in url and "type=municipality" in url:
            return BAN_GUER
        return BAN_VIDE

    geo = geocode.geocode_commune_ou_lieu("Guer-Coëtquidan", "56", fetch=fetch, cache={})
    assert geo["commune"] == "Guer"
    assert any("q=Guer" in url and "type=municipality" in url for url in appels)
    assert not any("q=Guer-Co" in url and "limit=1" in url and "type=municipality" not in url
                   for url in appels)
