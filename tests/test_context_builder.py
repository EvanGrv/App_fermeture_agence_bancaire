from backend.context_builder import build_compact_context
from backend.prefilter import analyse


def _ctx(article, max_chars=None):
    r = analyse(article)
    return build_compact_context(article, r, max_chars=max_chars)


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
