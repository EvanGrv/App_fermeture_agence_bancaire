# 10 — Glossaire

Les termes du code qui ne s'expliquent pas d'eux-mêmes. Le vocabulaire est
majoritairement français, à l'image du domaine.

## Les niveaux de données

**Fermeture** (`closure`) — Un événement identifié : une banque, une commune,
une date. C'est l'unité de base. Publiée sur la carte seulement si elle est
géocodée et qu'elle passe la garde d'extraction.

**Fermeture non géocodée** (`closure_unlocated`) — Une fermeture identifiée
mais non publiable : localisation absente, preuve insuffisante, ou hors fenêtre
temporelle. La colonne `raison` dit laquelle. Niveau 2.

**Signal départemental** (`department_signal`) — « La banque X ferme N agences
dans le département Y », sans que les communes soient nommées. Niveau 3.

**Signal vague** (`vague_signal`) — Une annonce nationale non territorialisée :
« la banque X fermera 200 agences en France ». Pas de département attaché.

**Vigilance** — Un signal faible : un article pertinent dont on n'a pas pu
tirer de fermeture publiable. C'est le filet de dernier recours, et de loin le
plus gros volume (~1 600 entrées). Niveau 4.

**Revue de vigilance** (`vigilance_review`) — Le processus qui reprend une
vigilance de score suffisant et lance une recherche web ciblée pour tenter de
la faire **remonter** en fermeture publiée. Soumis à un cooldown de 7 jours.

**Plan** — Un article annonçant une fermeture multiple (« 15 agences dans la
Loire »). L'**éclatement de plan** (*plan explosion*) le convertit en
fermetures individuelles, chacune repassant par la garde d'extraction.

## Les mécanismes

**Préfiltre** (`prefilter`) — Le tri local, sans IA. Deux niveaux : `is_relevant()`
est un test binaire bon marché ; `analyse()` produit un score et les entités
repérées. Un score ≤ `PREFILTER_MIN_SCORE` fait sauter l'appel IA — mais route
l'article en vigilance.

**Contexte compact** — L'extrait de 8 000 caractères maximum construit autour
des phrases pertinentes, envoyé à l'IA **à la place de l'article entier**.
Principal levier de coût du projet.

**Cache d'extraction** — La table `extractions`, indexée par
`(content_hash, extraction_version, model)`. Empêche de repayer l'IA sur un
contenu déjà traité.

**`EXTRACTION_VERSION`** — Le numéro qui invalide ce cache. À incrémenter à
chaque changement de prompt ou de schéma. L'oublier fait servir silencieusement
d'anciens résultats.

**Garde d'extraction** (`extraction_guard`) — Le dernier contrôle avant la
carte. Refuse une fermeture dont la localisation ou les preuves sont
insuffisantes, et renvoie une `raison` exploitable.

**Quarantaine** — La mise à l'écart d'anciens enregistrements La Banque Postale
douteux, au début du run, avant tout nouveau traitement.

**Drilldown** — La passe descendante qui détecte les articles de plan et génère
des requêtes ciblées commune par commune, ensuite injectées comme collecteur
supplémentaire.

**Backfill** — La récupération d'articles anciens (Common Crawl,
`postal_history`). Ne s'active que si la fenêtre dépasse 700 jours.

**Seed** — L'ingestion directe d'une liste d'URLs curées, court-circuitant les
collecteurs. Options `--seed-urls` et `--seed-excel`.

## Les qualifications

**Tier** (A→E) — La qualité d'une source, déduite de son domaine. A = officiel,
B = PQR identifiée, C = complémentaire, D = défaut, E = réseaux sociaux et
annuaires. Précédence A > B > C > E > D. Voir
[04-sources.md](04-sources.md).

**Fiabilité** (`fiabilite`) — Entier de 0 à 5, obtenu en multipliant la
`confidence` du modèle (0.0–1.0) par 5. 1 = rumeur vague, 5 = annonce
officielle confirmée.

**Niveau de preuve** (`evidence_level`) — La nature des preuves croisées :
`officiel+presse`, `presse+référentiel`…

**Statut temporel** (`statut_temporel`) — `a_venir`, `passee` ou `inconnu`,
relativement à la date du run.

**`date_fermeture_approx`** — Vaut `1` quand la date est approchée (« courant
2026 », « semaine précédant le 23/06 ») plutôt qu'exacte.

**Citation** — L'extrait de l'article qui justifie l'enregistrement. C'est ce
qui rend une fermeture auditable : sans citation, on ne peut pas vérifier.

## Le domaine

**PQR** — Presse Quotidienne Régionale. Ouest-France, La Dépêche, L'Est
Républicain… le gisement principal du projet.

**Enseigne** — Une marque bancaire suivie. 13 par défaut, 14 avec le Crédit
Municipal.

**Marque régionale** — Une déclinaison locale ou une ancienne dénomination
(« Crédit Agricole Centre-Est », « Banque Courtois »), rattachée à son enseigne
canonique par l'extracteur.

**LBP** — La Banque Postale. Canal à part dans toute la pipeline : la presse
parle de « bureau de poste » là où le métier voit une agence bancaire, d'où des
collecteurs, des termes et une logique de vérification dédiés.

**Point de contact postal** — L'unité du référentiel officiel La Poste
(~20 000 points). Un bureau peut devenir « agence postale communale » ou
« relais poste » : une transformation, pas toujours une fermeture.

**Référentiel** — Le fond de carte des agences connues (OpenStreetMap + LBP).
Sert de contexte d'affichage et de vérification. **Ce ne sont pas des
fermetures.**

**Code INSEE** — L'identifiant officiel d'une commune. Attention aux
départements sur deux caractères, Corse comprise (`2A`, `2B`), et aux DROM sur
trois (`971`–`976`).

**SIRENE** — Le répertoire des entreprises de l'INSEE, interrogé en fin de run
pour confirmer l'état administratif d'un établissement.

**Légifrance** — Source de textes officiels. Dans ce projet, elle produit des
**vigilances**, jamais des fermetures directement.
