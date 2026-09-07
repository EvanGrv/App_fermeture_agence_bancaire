# 04 — Sources et collecteurs

## Le contrat d'un collecteur

Tout module de [`backend/collectors/`](../backend/collectors/) expose une
fonction `collect()` qui renvoie une liste de dictionnaires :

```python
{
    "url":    "https://...",   # identifiant de déduplication
    "titre":  "...",
    "texte":  "...",           # résumé ou chapô ; la pipeline complètera
    "source": "Ouest-France",
    "date":   "2026-03-14",    # ISO 8601 ou RFC 2822
}
```

Trois règles valables pour tous :

1. **Ne jamais lever d'exception vers l'appelant.** Une clé manquante, un quota
   épuisé, un service en panne → log et liste vide. La pipeline capture aussi
   de son côté, mais un collecteur bien élevé se désactive proprement.
2. **Respecter son plafond.** Chaque collecteur a des limites configurables
   (pages, articles, requêtes). Elles existent pour borner coût et durée.
3. **Ne pas filtrer sur le fond.** Le tri est le travail du préfiltre. Un
   collecteur ratisse, il ne juge pas.

## Les collecteurs actifs

Ordre d'appel dans `run.py` :

| Module | Source | Clé requise | Notes |
|---|---|---|---|
| `google_news` | Google News RSS | non | Le pilier. Attention aux unités de `when:` (voir plus bas) |
| `local_feeds` | RSS de PQR | non | Actu.fr, Ouest-France, Ici, La Dépêche |
| `mediacloud` | API MediaCloud | `MEDIACLOUD_API_KEY` | Collections françaises `34412146`, `38379799` |
| `event_registry` | API Event Registry | `EVENT_REGISTRY_API_KEY` | Filtré sur la France |
| `postal_web` | Recherche web ciblée | via providers | Spécialisé bureaux de poste, 8 requêtes/run |
| `postal_history` | Backfill LBP | via providers | **Ne s'exécute que si la fenêtre ≥ 700 jours** |
| `common_crawl` | Index Common Crawl | non | Backfill profond, même seuil de 700 jours |
| `gdelt` | GDELT | non | Throttle de 12 s imposé par le service |
| `official` | Communiqués de banques | non | Tier A |
| `legifrance` | API Légifrance | `LEGIFRANCE_CLIENT_ID/SECRET` | Produit des vigilances, pas des fermetures |
| `web_search` | Recherche web générique | via providers | Passe par le registre de providers |

Deux modules du même dossier ne sont **pas** des collecteurs de la boucle :

- `laposte_open_data` — appelé séparément par `run.py` pour synchroniser le
  réseau officiel et enrichir les fermetures LBP.
- `sg_locator` — injecte des fermetures Société Générale déjà vérifiées.
- `news_queries` — module utilitaire partagé, construit les requêtes.

Et un module est un **stub non implémenté** :

- `presse_pro` — squelette pour d'éventuels accès à la presse professionnelle
  sous licence. Il journalise « adaptateurs non implémentés » et renvoie une
  liste vide. Il n'est câblé nulle part. Conservé comme point d'accroche.

## Les providers de recherche web

`backend/search_providers/registry.py` agrège plusieurs moteurs derrière une
interface unique `search(query, since, limit)`, déduplique par URL, et capture
les erreurs provider par provider.

| Provider | Clé | Actif par défaut |
|---|---|---|
| `brave` | `BRAVE_SEARCH_API_KEY` | oui |
| `bing` | `BING_SEARCH_API_KEY` | non |
| `local_sitemap` | aucune | oui en CI, non en local |

`local_sitemap` explore les sitemaps et flux de domaines de presse listés dans
`LOCAL_SITEMAP_DOMAINS`. Il ne coûte rien en API mais beaucoup en requêtes
HTTP — d'où sa désactivation par défaut en local
(`LOCAL_SITEMAP_ENABLED=0`).

La sélection se fait par `WEB_SEARCH_PROVIDERS`, une liste ordonnée séparée par
des virgules.

## Le tiering des sources

[`backend/source_tier.py`](../backend/source_tier.py) classe chaque URL par
domaine, de A à E. Ce tier alimente le calcul de fiabilité et l'affichage.

| Tier | Signification | Exemples |
|---|---|---|
| **A** | Communiqué officiel | domaines de banques, `*.gouv.fr`, tout hôte contenant `mairie` |
| **B** | PQR identifiée | Ouest-France, La Dépêche, L'Est Républicain… |
| **C** | Bonne source complémentaire | France 3 régions, France Bleu, actu.fr, ici.fr |
| **D** | Autre presse, agrégateur, **défaut** | inclut `news.google.com` et toute URL vide ou non parseable |
| **E** | Réseaux sociaux, annuaires, avis | Google Maps, pages d'avis |

Précédence : **A > B > C > E > D**. D est le défaut, pas le pire : une URL
inconnue est « presse non identifiée », pas « source douteuse ».

## Pièges connus

**Les unités de Google News.** Dans l'opérateur `when:`, `m` signifie
**minutes**, pas mois. `h`=heures, `d`=jours, `y`=années. Un mois s'écrit donc
`30d`. Une erreur ici réduit silencieusement la fenêtre à quelques minutes —
le run réussit et ne trouve rien.

**Les collecteurs de backfill ne se déclenchent pas toujours.**
`common_crawl` et `postal_history` exigent une fenêtre d'au moins 700 jours.
Sur un `--lookback-days 60`, ils ne s'exécutent tout simplement pas. Ce n'est
pas une panne.

**Le silence n'est pas une erreur.** Un collecteur sans clé API journalise sa
désactivation et rend une liste vide. Lisez la sortie console avant de
conclure à un bug.

**Common Crawl ne fait pas de recherche plein texte.** L'index ne permet que de
cibler des domaines et des motifs d'URL. Le collecteur récupère des candidats
par domaine puis valide le contenu localement — d'où son rendement faible et
ses plafonds serrés.

## Ajouter une source

1. Créer `backend/collectors/ma_source.py` avec une fonction `collect()`
   respectant le contrat ci-dessus.
2. Ajouter ses réglages dans `config.py`, préfixés du nom de la source, avec
   un interrupteur `MA_SOURCE_ENABLED` et des plafonds.
3. Créer `tests/test_ma_source.py` avec une fixture dans `tests/fixtures/` —
   **aucun test ne doit accéder au réseau**.
4. L'importer et l'ajouter à la liste `collectors` de `run.py`.
5. Si elle mérite un tier autre que D, l'ajouter au bon ensemble de domaines
   dans `source_tier.py`.
6. Répercuter les nouvelles variables dans `.github/workflows/update-data.yml`
   et dans [08-configuration.md](08-configuration.md).
