import config

def test_chemins_sous_racine():
    assert config.DB_PATH.parent == config.ROOT / "data"
    assert config.DATA_JSON == config.EXPORT_DIR / "data.json"

def test_modele_par_defaut():
    assert config.ANTHROPIC_MODEL == "claude-opus-4-8"

def test_listes_non_vides():
    assert len(config.ENSEIGNES) >= 5
    assert "fermeture" in [t.lower() for t in config.TERMES_FERMETURE]
    assert config.DEPARTEMENTS["35"] == "Ille-et-Vilaine"
    assert len(config.DEPARTEMENTS) >= 96
