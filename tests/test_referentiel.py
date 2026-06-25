import json
from pathlib import Path

import backend.store as store
from backend import referentiel

FIXT = Path(__file__).parent / "fixtures" / "overpass_banks_sample.json"


def _fetch_overpass(url, **kwargs):
    assert "overpass-api.de/api/interpreter" in url
    assert "data" in kwargs
    return json.loads(FIXT.read_text(encoding="utf-8"))


def test_fetch_osm_banques_parse_et_inclut_banque_postale():
    branches = referentiel.fetch_osm_banques(fetch=_fetch_overpass)
    assert len(branches) == 4
    assert branches[0]["osm_id"] == "node/101"
    assert branches[0]["banque"] == "BNP Paribas"
    assert branches[0]["departement"] == "75"
    assert branches[1]["banque"] == "Crédit Agricole Centre-Est"
    assert branches[2]["banque"] == "La Banque Postale"
    assert branches[2]["departement"] == "31"
    assert branches[3]["osm_id"] == "way/204"
    assert {b["source"] for b in branches} == {"OSM"}
    assert any(b["banque"] == "La Banque Postale" for b in branches)


def test_compter_par_departement():
    branches = referentiel.fetch_osm_banques(fetch=_fetch_overpass)
    assert referentiel.compter_par_departement(branches) == {"75": 1, "69": 1, "31": 1, "29": 1}


def test_upsert_referentiel(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    branche = referentiel.fetch_osm_banques(fetch=_fetch_overpass)[0]
    store.upsert_referentiel(conn, branche)
    store.upsert_referentiel(conn, {**branche, "commune": "Paris 2e"})
    row = conn.execute(
        "SELECT banque, commune, departement, source FROM referentiel WHERE osm_id=?",
        (branche["osm_id"],),
    ).fetchone()
    assert row == ("BNP Paribas", "Paris 2e", "75", "OSM")
