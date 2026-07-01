import config

def test_chemins_sous_racine():
    assert config.DB_PATH.parent == config.ROOT / "data"
    assert config.DATA_JSON == config.EXPORT_DIR / "data.json"

def test_modele_par_defaut():
    assert config.ANTHROPIC_MODEL == "claude-haiku-4-5"
    assert config.ANTHROPIC_FALLBACK_MODEL == "claude-sonnet-4-6"
    assert config.ANTHROPIC_FALLBACK_ENABLED is True
    assert config.EXTRACTION_VERSION == 3

def test_listes_non_vides():
    assert len(config.ENSEIGNES) >= 5
    assert "fermeture" in [t.lower() for t in config.TERMES_FERMETURE]
    assert len(config.LOCAL_RSS_FEEDS) >= 3
    assert all(feed["label"] and feed["url"].startswith("https://") for feed in config.LOCAL_RSS_FEEDS)
    assert config.DEPARTEMENTS["35"] == "Ille-et-Vilaine"
    assert len(config.DEPARTEMENTS) >= 96
