from backend import geocode

BAN_OK = {"features": [
    {"geometry": {"coordinates": [-1.6778, 48.1173]},
     "properties": {"city": "Rennes", "citycode": "35238", "postcode": "35000"}}
]}
BAN_VIDE = {"features": []}


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
