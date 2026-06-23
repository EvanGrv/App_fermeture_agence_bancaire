from backend import geocode

BAN_OK = {"features": [
    {"geometry": {"coordinates": [-1.6778, 48.1173]},
     "properties": {"city": "Rennes"}}
]}
BAN_VIDE = {"features": []}

def test_parse_ban():
    assert geocode.parse_ban(BAN_OK) == (48.1173, -1.6778)  # (lat, lon)

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
    assert a == b == (48.1173, -1.6778)
    assert len(appels) == 1  # second appel servi par le cache

def test_geocode_echec_retourne_none():
    res = geocode.geocode_commune("Xyz", "99", fetch=lambda url: BAN_VIDE, cache={})
    assert res is None
