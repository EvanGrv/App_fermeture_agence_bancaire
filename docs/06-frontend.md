# 06 — Frontend

## Le parti pris

Trois fichiers, aucun framework, aucune étape de build, aucune dépendance npm.

```
frontend/
  index.html   543 lignes   structure et gabarits des 9 vues
  app.js      2040 lignes   chargement, filtres, rendu, carte
  style.css   1764 lignes   thème sombre, grilles, composants
index.html                  redirection racine vers /frontend
vercel.json                 en-têtes de cache pour /data/export/
```

Ouvrir `frontend/index.html` derrière n'importe quel serveur de fichiers
suffit. C'est délibéré : le site doit survivre sans chaîne d'outillage, et
n'importe qui doit pouvoir le modifier avec un éditeur de texte.

La seule dépendance externe est **Leaflet**, chargé par CDN, pour les fonds de
carte.

## Le flux d'exécution

```
chargement de la page
      │
      ▼
fetch("../data/export/data.json")       ← le seul appel réseau
      │
      ▼
état global : items + filtres actifs
      │
      ├─ l'utilisateur change un filtre ──┐
      │                                   │
      ▼                                   │
renderAll()  ◀────────────────────────────┘
      │
      ├─ renderStats()      cartes de chiffres
      ├─ renderResults()    liste latérale
      ├─ renderArticles()   vue Articles
      ├─ renderDepartments()vue Départements
      ├─ renderTimeline()   vue Évolution
      ├─ renderHome()       accueil
      ├─ renderAgencies()   tableau
      ├─ renderAlerts()     vigilances
      ├─ renderPlans()      bandeau des plans
      └─ renderSettings()   paramètres
```

Le modèle est volontairement naïf : un état global, et `renderAll()` qui
recalcule tout à chaque changement de filtre. Avec quelques milliers d'items
c'est instantané, et ça évite toute machinerie de synchronisation.

## Les vues

La navigation latérale bascule la classe `active` entre des `<section
id="view-*">`. Chaque bouton porte un attribut `data-view`.

| Vue | `data-view` | Contenu |
|---|---|---|
| Accueil | `home` | Chiffres clés, derniers résultats, alertes récentes |
| Carte | `map` | Carte Leaflet des fermetures géocodées (**niveau 1 uniquement**) |
| Agences | `agencies` | Tableau des fermetures |
| Articles | `articles` | Couverture presse par région et département |
| Départements | `departments` | Carte choroplèthe + détail départemental |
| Évolution | `timeline` | Séries temporelles |
| Sources | `sources` | Sources utilisées et leur tier |
| Alertes | `alerts` | Vigilances (niveau 4) |
| Paramètres | `settings` | Réglages, et déclenchement de la pipeline via `app_server.py` |

**La carte n'affiche que le niveau 1.** Les niveaux 2 à 4 apparaissent dans les
vues Départements et Alertes. C'est l'application directe du principe « la
carte reste stricte » — ne le contournez pas en ajoutant des points issus de
`closures_unlocated`.

## Les filtres

Barre commune à toutes les vues, appliquée en amont de chaque rendu : banque,
statut, type, fiabilité, département, période, statut temporel, plus une
recherche plein texte. `#reset-filters` remet tout à zéro,
`#download-excel` exporte la sélection courante.

## Modifier le frontend

**Ajouter un champ affiché.** Il doit exister dans `data.json` : commencez par
`export.build_payload()`, régénérez l'export, puis affichez-le. Le front ne
peut rien inventer.

**Ajouter une vue.** Un `<button class="nav-link" data-view="ma-vue">` dans la
nav, une `<section id="view-ma-vue" class="page">` dans le workspace, une
fonction `renderMaVue()` appelée depuis `renderAll()`.

**Attention aux formats.** Le front suppose des dates ISO et des codes
département sur deux caractères (`"01"`, pas `1`) — Corse comprise (`2A`,
`2B`) et DROM sur trois (`971`…). Un code non normalisé casse silencieusement
les jointures cartographiques.

## Tests

`tests/test_frontend_smoke.py` (210 lignes) vérifie la cohérence entre le HTML
et le JS : que chaque `data-view` a bien sa section, et que les identifiants
manipulés par `app.js` existent. Ça n'exécute pas le JS, mais ça attrape les
désynchronisations les plus courantes.

## Déploiement

Vercel sert le dépôt en statique. `vercel.json` définit `cleanUrls`,
`trailingSlash: false` et un `Cache-Control: max-age=300` sur
`/data/export/*` — c'est ce qui fait que le site reflète les nouvelles données
dans les cinq minutes suivant le commit du bot.

Il n'y a **pas de backend en production**. Les routes `/api/pipeline/*` de
l'onglet Paramètres n'existent que si vous lancez `app_server.py` en local.
