from backend.context_builder import build_compact_context
from backend.prefilter import analyse


def test_garde_paragraphe_pertinent_coupe_bruit():
    bruit = "La météo sera clémente ce week-end sur toute la région. " * 20
    art = {"titre": "Crédit Agricole", "source": "GN", "date": "2026-01-01", "url": "http://x",
           "texte": bruit + "\n\nLe Crédit Agricole ferme son agence de Tulle en 2026.\n\n" + bruit}
    ctx = build_compact_context(art, analyse(art), max_chars=300)
    assert "Tulle" in ctx
    assert "météo" not in ctx.lower()


def test_conserve_enumeration_communes():
    art = {"titre": "Caisse d'Épargne", "source": "MoneyVox", "date": "", "url": "",
           "texte": "Les agences de Bessines, Saint-Junien, Tulle et Guéret vont fermer."}
    ctx = build_compact_context(art, analyse(art), max_chars=4000)
    for commune in ("Bessines", "Saint-Junien", "Tulle", "Guéret"):
        assert commune in ctx


def test_respecte_max_chars():
    art = {"titre": "BNP ferme", "source": "GN", "date": "", "url": "",
           "texte": ("La BNP ferme son agence. " * 200)}
    ctx = build_compact_context(art, analyse(art), max_chars=200)
    assert len(ctx) <= 200


def test_repli_si_aucune_phrase_pertinente():
    art = {"titre": "Titre neutre", "source": "GN", "date": "", "url": "",
           "texte": "Un texte sans rien de pertinent ici."}
    ctx = build_compact_context(art, analyse(art), max_chars=4000)
    assert "Titre neutre" in ctx  # en-tête + repli sur le texte


# --- Fix B: compaction keeps commune+date paragraphs ---

def test_compaction_garde_paragraphe_commune_sans_terme_banque():
    # A paragraph carrying only a commune+date (no bank/term) should be retained
    # when that commune appears in result.communes, even when body > max_chars.
    bruit = "Beau temps ce week-end sur toute la région. " * 30  # ~1320 chars of noise

    # First paragraph: triggers commune detection (bank+term, no commune name)
    para_trigger = "Le Crédit Agricole va fermer plusieurs agences dans le département."
    # Second paragraph: commune only (no bank, no term) — this is what Fix B must keep
    para_commune = "À Tulle, la décision sera effective au printemps 2026."
    texte = para_trigger + "\n\n" + para_commune + "\n\n" + bruit

    art = {
        "titre": "Crédit Agricole restructure", "source": "GN",
        "date": "2026-01-01", "url": "http://x",
        "texte": texte,
    }
    # max_chars small enough to trigger compaction (header ~80 + para_trigger ~66 = ~146)
    result = analyse(art)
    assert any("Tulle" in c for c in result.communes), "Tulle must be in result.communes"
    ctx = build_compact_context(art, result, max_chars=300)
    assert "Tulle" in ctx, f"commune paragraph must survive compaction, got: {ctx!r}"
    assert "Beau temps" not in ctx, "noise must be stripped"
