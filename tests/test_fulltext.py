"""Tests pour backend/fulltext.py — module de récupération du texte intégral."""
from backend.fulltext import fetch_text


# HTML réaliste avec assez de contenu pour que trafilatura extraie le corps
_ARTICLE_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Fermeture agence Crédit Agricole à Limoges</title>
</head>
<body>
  <header><nav>Accueil | Finance | Régions</nav></header>
  <main>
    <article>
      <h1>Le Crédit Agricole ferme son agence du centre-ville de Limoges</h1>
      <p class="date">25 juin 2026</p>
      <p>
        Le Crédit Agricole Centre Ouest a annoncé ce mardi la fermeture définitive
        de son agence située rue Jean-Jaurès à Limoges, prévue pour le 30 septembre 2026.
        Cette décision s'inscrit dans le cadre du plan de rationalisation du réseau
        bancaire régional, qui vise à concentrer les services sur des agences plus grandes
        et mieux équipées.
      </p>
      <p>
        Selon le directeur régional, les clients concernés seront redirigés vers
        l'agence de la place Denis-Dussoubs, distante de seulement 400 mètres.
        Des conseillers seront disponibles pour accompagner la transition.
      </p>
      <p>
        Cette fermeture représente la troisième suppression d'agence dans la Haute-Vienne
        depuis le début de l'année, une tendance observée dans toute la France depuis 2023.
      </p>
    </article>
  </main>
  <footer>© 2026 Presse Locale</footer>
</body>
</html>
"""


def test_fetch_text_extrait_le_corps(tmp_path):
    """Un fetch injecté renvoyant un HTML réaliste → le corps de l'article est extrait."""
    def fetch_html(url):
        return _ARTICLE_HTML

    result = fetch_text("https://example.com/article", fetch=fetch_html, cache_dir=tmp_path)

    assert isinstance(result, str)
    assert len(result) > 0
    # La phrase clé doit apparaître dans le texte extrait
    assert "Crédit Agricole" in result


def test_fetch_text_echec_renvoie_vide(tmp_path):
    """Un fetch qui lève une exception → fetch_text retourne une chaîne vide (best-effort)."""
    def fetch_raises(url):
        raise RuntimeError("Connexion refusée")

    result = fetch_text("https://example.com/inaccessible", fetch=fetch_raises, cache_dir=tmp_path)

    assert result == ""


def test_fetch_text_utilise_cache(tmp_path):
    """Le deuxième appel avec la même URL ne rappelle pas fetch (cache disque)."""
    call_count = []

    def fetch_spy(url):
        call_count.append(url)
        return _ARTICLE_HTML

    url = "https://example.com/article-cache"
    result1 = fetch_text(url, fetch=fetch_spy, cache_dir=tmp_path)
    result2 = fetch_text(url, fetch=fetch_spy, cache_dir=tmp_path)

    assert len(call_count) == 1, f"fetch appelé {len(call_count)} fois au lieu de 1"
    assert result1 == result2
