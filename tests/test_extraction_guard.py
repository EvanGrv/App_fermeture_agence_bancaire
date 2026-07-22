from backend import extraction_guard, store


def _closure(**overrides):
    closure = {
        "id": "lbp-test", "banque": "La Banque Postale",
        "commune": "Poitiers", "code_insee": "86194",
        "departement": "86", "type": "fermeture",
        "date_annonce": "2026-06-17",
        "date_fermeture": "2026-08-01", "date_fermeture_approx": 1,
        "statut": "confirmé", "statut_temporel": "a_venir", "fiabilite": 4,
        "lat": 46.5, "lon": 0.3, "citation": "Le bureau fermera",
        "agence_localisation": None,
    }
    closure.update(overrides)
    return closure


def _article(title, text="", department=None):
    return {
        "titre": title, "texte": text, "departement": department,
        "url": "https://example.test/article", "source": "PQR", "date": "2026-06-17",
    }


def _geo(department="86", code="86194"):
    return {"departement": department, "code_insee": code, "lat": 46.5, "lon": 0.3}


def test_rejette_plelan_invente_depuis_un_article_de_lozere():
    decision = extraction_guard.evaluate(
        _closure(commune="Plélan-le-Grand", departement="35"),
        _article(
            '"Ils vident la coquille" : le bureau de poste ferme en août, '
            "ce maire de Lozère dénonce un désengagement"
        ),
        _geo("35", "35223"),
    )
    assert not decision.accepted
    assert "département source 48" in decision.reason


def test_rejette_commune_absente_dune_source_generique():
    decision = extraction_guard.evaluate(
        _closure(commune="Échenoz-la-Méline", departement="70"),
        _article("Cette commune de Loire-Atlantique perd son bureau de poste"),
        _geo("70", "70221"),
    )
    assert not decision.accepted


def test_accepte_commune_administrative_prefixe_dans_le_nom_dagence():
    decision = extraction_guard.evaluate(
        _closure(commune="Poitiers"),
        _article("Le bureau de poste de Poitiers-Sud fermera en août"),
        _geo(),
    )
    assert decision.accepted


def test_rejette_suffixe_de_commune_pris_isolément():
    decision = extraction_guard.evaluate(
        _closure(commune="Bourgneuf", departement="17"),
        _article("Le bureau de poste de Vierzon-Bourgneuf va fermer"),
        _geo("17", "17059"),
    )
    assert not decision.accepted
    assert "absente de la source" in decision.reason


def test_rejette_singulier_pris_dans_un_pluriel():
    decision = extraction_guard.evaluate(
        _closure(commune="Châtillon", departement="92"),
        _article("Le bureau des Châtillons à Reims va fermer"),
        _geo("92", "92020"),
    )
    assert not decision.accepted


def test_accepte_lieu_dit_source_conserve_comme_localisation():
    decision = extraction_guard.evaluate(
        _closure(
            commune="Saint-Nazaire", departement="44",
            agence_localisation="Saint-Marc-sur-Mer",
        ),
        _article("Le bureau de poste de Saint-Marc-sur-Mer fermera définitivement"),
        _geo("44", "44184"),
    )
    assert decision.accepted


def test_rejette_fermeture_temporaire_et_negation():
    temporary = extraction_guard.evaluate(
        _closure(),
        _article("Poitiers : fermeture temporaire du bureau de poste pour travaux"),
        _geo(),
    )
    negated = extraction_guard.evaluate(
        _closure(),
        _article("Poitiers : le bureau de poste ne fermera pas"),
        _geo(),
    )
    assert not temporary.accepted
    assert "temporaire" in temporary.reason
    assert not negated.accepted
    assert "nie ou annule" in negated.reason


def test_ne_rouvrira_pas_reste_un_signal_de_fermeture_definitive():
    decision = extraction_guard.evaluate(
        _closure(),
        _article("Poitiers : fermé définitivement, le bureau ne rouvrira pas"),
        _geo(),
    )
    assert decision.accepted


def test_accepte_fermeture_menacee_nominative():
    decision = extraction_guard.evaluate(
        _closure(statut="projet"),
        _article("Le bureau de poste de Poitiers est menacé de fermeture"),
        _geo(),
    )
    assert decision.accepted


def test_rejette_date_approximative_dont_le_mois_contredit_la_source():
    decision = extraction_guard.evaluate(
        _closure(date_fermeture="2026-06-17", date_fermeture_approx=1),
        _article("Poitiers : le bureau de poste ferme en août"),
        _geo(),
    )
    assert not decision.accepted
    assert "mois de fermeture" in decision.reason


def test_rejette_homonyme_incompatible_avec_le_lieu_en_tete():
    def geocode(commune, _department=None):
        if commune == "Saumur":
            return _geo("49", "49328")
        return None

    decision = extraction_guard.evaluate(
        _closure(commune="Bagneux", departement="92"),
        _article("À Saumur, le bureau de poste de Bagneux va fermer"),
        _geo("92", "92007"),
        geocode_fn=geocode,
    )
    assert not decision.accepted
    assert "lieu d’article Saumur" in decision.reason


def test_quarantaine_un_ancien_marqueur_lbp_temporaire(tmp_path):
    conn = store.init_db(tmp_path / "guard.db")
    store.upsert_closure(conn, _closure(evidence_level="presse+référentiel"))
    store.add_source(conn, "lbp-test", {
        "url": "https://example.test/temporaire",
        "titre": "Poitiers : le bureau de poste ferme temporairement pour travaux",
        "source": "PQR", "date": "2026-06-17",
    })

    recap = extraction_guard.quarantine_existing_lbp(conn)

    assert recap["quarantined"] == 1
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 0
    reason = conn.execute("SELECT raison FROM closures_unlocated").fetchone()[0]
    assert "temporaire" in reason


def test_quarantaine_un_ancien_marqueur_dont_la_commune_nest_pas_dans_le_titre(tmp_path):
    conn = store.init_db(tmp_path / "guard-location.db")
    store.upsert_closure(conn, _closure(
        commune="Bourgneuf", code_insee="17059", departement="17",
        evidence_level="presse+référentiel",
    ))
    store.add_source(conn, "lbp-test", {
        "url": "https://example.test/vierzon-bourgneuf",
        "titre": "Le bureau de poste de Vierzon-Bourgneuf va définitivement fermer",
        "source": "PQR", "date": "2026-06-17",
    })

    recap = extraction_guard.quarantine_existing_lbp(conn)

    assert recap["quarantined"] == 1
    reason = conn.execute("SELECT raison FROM closures_unlocated").fetchone()[0]
    assert "absente de la source" in reason
