# Cycle 2c-ii — Escalade Sonnet pilotée par le contenu (Design)

Date : 2026-07-01
Statut : spec de sous-cycle après 2c-i.

## Contexte

2c-i a remplacé l'extraction single-closure par `ExtractionResult` :
`article_type`, `closures[]`, `department_signals[]`, `vague_signals[]`,
`confidence`, `needs_sonnet`. Le pipeline principal consomme déjà ce JSON riche
et le persiste dans `extractions.result_json`.

Aujourd'hui, `extract_structured()` utilise Sonnet uniquement comme fallback
technique sur erreur API. Le champ `needs_sonnet` et la `confidence` globale ne
sont pas encore exploités.

## But

Ajouter une escalade **contenu** Haiku → Sonnet quand Haiku signale que
l'article est ambigu ou fragile. L'objectif est de payer Sonnet seulement sur les
articles où il peut récupérer des fermetures manquées ou clarifier un article
liste/plan.

## Règle d'escalade

`extract_structured()` appelle d'abord Haiku. Si le résultat Haiku remplit au
moins une condition ci-dessous, et si `ANTHROPIC_FALLBACK_MODEL` est activé, il
relance le même article avec Sonnet :

- `result.needs_sonnet is True`
- `result.article_type == "ambiguous"`
- `result.confidence < STRUCTURED_SONNET_MIN_CONFIDENCE` (défaut `0.65`)
- `article_type == "list_closures"` mais `closures[]` est vide
- `article_type == "department_signal"` et `department_signals[]` est vide

Pas d'escalade si le modèle courant est déjà le fallback, ou si
`STRUCTURED_SONNET_ESCALATION_ENABLED=0`.

## Prompt Sonnet

Sonnet reçoit le même contexte compact que Haiku, avec une consigne additionnelle :

- relire précisément l'article ;
- résoudre les ambiguïtés ;
- extraire toutes les agences nommées ;
- ne pas inventer d'adresse/commune ;
- mettre `needs_sonnet=false` sauf ambiguïté persistante.

## Choix du résultat

Pour 2c-ii, le résultat Sonnet remplace le résultat Haiku quand l'escalade est
déclenchée et que Sonnet répond sans erreur. En cas d'erreur Sonnet, on garde le
résultat Haiku, afin de ne pas perdre une extraction partielle.

## Cache

Le comportement d'extraction change : un contenu qui produisait un résultat
Haiku faible peut maintenant produire un résultat Sonnet enrichi. On bump donc
`EXTRACTION_VERSION` de `2` à `3`.

Le cache continue d'être stocké sous le modèle primaire (`ANTHROPIC_MODEL`) via
`extract_cached_with_status`. C'est acceptable pour 2c-ii : le JSON riche final
est persisté, et l'information utile pour le Cycle 3 est dans `result_json`.

## Hors périmètre

- Pas de table d'audit des coûts Sonnet.
- Pas de stockage explicite `closures_unlocated` / `department_signals` (Cycle 3).
- Pas de modification du fallback OpenAI legacy.
- Pas de relance pipeline production dans ce sous-cycle.

## Tests attendus

- `should_escalate_structured()` retourne True pour `needs_sonnet`,
  `ambiguous`, confidence basse, liste vide, signal départemental vide.
- `extract_structured()` appelle Haiku puis Sonnet quand Haiku est ambigu.
- `extract_structured()` n'appelle pas Sonnet si l'escalade est désactivée.
- Si Sonnet échoue après escalade contenu, le résultat Haiku est conservé.
- Le legacy `extract()` reste inchangé.
- `EXTRACTION_VERSION` vaut `3` par défaut.
