# Cycle 2c-i — Nouveau schéma d'extraction Haiku + mapping (Design)

Date : 2026-07-01
Statut : approuvé sur le principe. Spec détaillé d'un sous-cycle (sections 11 + 13, partie extraction).

## Contexte

Sous-cycle du Cycle 2. Ordre : 2a fulltext/cache (fait) → 2b préfiltre+contexte (fait)
→ **2c-i nouveau schéma Haiku + mapping (ce spec)** → 2c-ii escalade Sonnet contenu.

Aujourd'hui `extractor.extract()` renvoie **un** closure (`Extraction`, schéma
single-closure) ou `None` ; le pipeline géocode/valide/upsert un closure ; les
articles-listes sont traités à part par le pass regex `drilldown.fermetures_depuis_plan`
(no-IA) ; le fallback Sonnet/OpenAI est piloté par **erreur API**.

Principe transverse : « lire large, ne rien perdre, payer peu ». Le JSON riche
doit rester **persisté** pour le Cycle 3.

## But

1. Produire un **schéma d'extraction riche** (article_type, closures[],
   department_signals[], vague_signals[], needs_sonnet, confidence) via Haiku.
2. **Explosion native des articles-listes** : `article_type=list_closures` →
   `closures[]` multi (section 13), plus besoin du regex pour l'IA.
3. **Mapper** ce schéma vers le stockage actuel (closures + vigilances) sans
   changer le schéma DB (tiers explicites = Cycle 3).
4. **Persister le JSON riche** dans le cache d'extraction (2a) pour le Cycle 3.

## Périmètre

- **2c-i couvre** : modèles Pydantic + prompt + `extract_structured()` ; module de
  mapping `ingest_map` ; intégration pipeline (boucle closures[] + routage signaux) ;
  bump `EXTRACTION_VERSION` ; mise à jour du schéma `openai_fallback`.
- **2c-i ne couvre PAS** : escalade Sonnet pilotée par le contenu (**2c-ii**) —
  2c-i garde le fallback Sonnet **sur erreur API** uniquement ; les tiers de
  stockage explicites (**Cycle 3**) ; le retrait du pass regex drilldown
  (**conservé intact**, filet no-IA) ; la migration du chemin `vigilance_review`
  (garde l'ancien `extract()`, réconciliation différée).
- **Compat** : l'ancien `Extraction`/`extract()` est **conservé** (utilisé par
  `vigilance_review`) le temps de la migration.

## Persistance du JSON riche (exigence clé)

`extract_structured` renvoie toujours un `ExtractionResult` sérialisable (jamais
`None` en cas de succès, y compris `out_of_scope`). Dans le pipeline, il est
appelé via `extract_cached` (2a), qui stocke déjà `json.dumps(result)` dans
`extractions.result_json`. Donc **le JSON riche complet est persisté sans
modifier le cache** ; le Cycle 3 lira `extractions.result_json`. Effet de bord
bénéfique : même les `out_of_scope` sont cachés → pas de re-paiement IA.

**Bump `EXTRACTION_VERSION` 1 → 2** : le schéma/prompt change, le cache 2a
s'invalide proprement (clé `content_hash+extraction_version+model`).

## Schéma (modèles Pydantic dans `extractor.py`)

```python
class ClosureItem(BaseModel):
    bank: str
    agency_label: str = ""
    commune: str
    departement: str | None = None
    region: str | None = None
    address: str = ""
    closure_date: str | None = None            # ISO YYYY-MM-DD si connue
    date_precision: Literal["exact","month","year","approximate","unknown"] = "unknown"
    status: Literal["confirmed","announced","contested","threatened","unclear"]
    closure_type: Literal["closure","regroupement","transfer","merge","threatened_closure"]
    is_physical_agency: bool = True
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""

class DeptSignal(BaseModel):
    bank: str
    departement: str | None = None
    count: int | None = None
    communes_mentioned: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: str = ""

class VagueSignal(BaseModel):
    bank: str = ""
    scope: Literal["regional","national","unknown"] = "unknown"
    count: int | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: str = ""

class ExtractionResult(BaseModel):
    article_type: Literal["single_closure","list_closures","department_signal",
                          "regional_signal","national_signal","social_hr",
                          "out_of_scope","ambiguous"]
    source_reliability: Literal["primary","local_press","national_press","aggregator","weak"] = "weak"
    closures: list[ClosureItem] = Field(default_factory=list)
    department_signals: list[DeptSignal] = Field(default_factory=list)
    vague_signals: list[VagueSignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)   # confiance globale (nécessaire à 2c-ii)
    needs_sonnet: bool = False
    reason: str = ""
```

**Toutes les listes Pydantic utilisent `Field(default_factory=list)`** (jamais `= []`).

`extract_structured(article, client, model=config.ANTHROPIC_MODEL, aujourdhui=None,
floor=None) -> ExtractionResult` : Haiku primaire via `client.messages.parse`
(retries transitoires existants), fallback Sonnet **sur erreur API** (comme
aujourd'hui) ; fallback profond OpenAI → `extract_openai_structured` (et non le
legacy `extract_openai`). Renvoie l'`ExtractionResult` (les décisions de
rétention/filtrage temporel sont faites au **mapping**, pas dans l'extracteur).

## Mapping (`backend/ingest_map.py`)

`map_result(result: dict, article: dict, aujourdhui: str) -> tuple[list[dict], list[dict]]`
→ `(closures_internes, vigilances)`.

**closures[] → dict closure interne** (uniquement si `is_physical_agency` et `commune`) :

| champ interne | source | règle |
|---|---|---|
| `banque` | `bank` | `normalise_banque` ; ignorer si banque inconnue |
| `commune` | `commune` | |
| `agence_localisation` | `agency_label` | |
| `adresse` | `address` | |
| `type` | `closure_type` | merge/regroupement → `fusion` ; closure/transfer/threatened_closure → `fermeture` |
| `statut` | `status` | confirmed→`confirmé` ; announced→`projet` ; contested/threatened/unclear→`rumeur` |
| `fiabilite` | `confidence` | `round(confidence*5)` borné 0-5 |
| `date_fermeture` | `closure_date` | |
| `date_fermeture_approx` | `date_precision` | exact→0 ; sinon→1 |
| `statut_temporel` | dérivé | `closure_date` future→`a_venir`, passée→`deja_fermee` ; sinon status announced/threatened→`a_venir`, autres→`inconnu` |
| `citation` | `evidence` | |
| `departement`,`code_insee`,`lat`,`lon` | — | remplis par le géocodage pipeline |
| `id` | — | `closure_id(banque, commune, type)` |

Le mapping ne fait que **traduire** (pas de décision de rétention). Le filtrage
temporel et la validation sont appliqués **par closure dans le pipeline**, en
réutilisant `extractor._retenir_fermeture(statut_temporel, date_fermeture, floor,
aujourdhui)` et `validation.fermeture_publiable(...)` : un closure non retenu /
non publiable est routé en **vigilance** (jamais perdu), pas jeté.

**department_signals[] et vague_signals[] → dict vigilance** (routés en vigilances,
rien ne se perd) :

| champ vigilance | dept_signal | vague_signal |
|---|---|---|
| `id` | hash(url+bank+departement+"dept") | hash(url+bank+scope+"vague") |
| `banque` | `normalise_banque(bank)` | idem |
| `departement` | `departement` | `None` |
| `titre` | `article.titre` | `article.titre` |
| `extrait` | `evidence` | `evidence` |
| `url`/`source`/`date` | article | article |
| `score` | `round(confidence*5)` | `round(confidence*5)` |
| `raison` | `"signal départemental (count=…, communes=…)"` | `"signal vague ({scope}, count=…)"` |

## Intégration pipeline (`run_pipeline`)

Remplace la consommation « un closure » par :

```
result = extract_cached(art, structured_extractor_fn, conn)   # dict ExtractionResult, ou None (erreur/soft-skip)
if result is None:
    vigilance_fn(art, "extraction indisponible")   # comme aujourd'hui
    continue
closures, vigilances = ingest_map.map_result(result, art, aujourdhui)
for v in vigilances:
    store.upsert_vigilance(conn, v); recap["vigilances"] += 1
if not closures:
    # department/regional/national/social/out_of_scope : signaux déjà routés
    continue
for c in closures:
    if not extractor._retenir_fermeture(c["statut_temporel"], c.get("date_fermeture"), floor, aujourdhui):
        vigilance_fn(art, "fermeture hors fenêtre temporelle"); recap["vigilances"] += 1; continue
    # géocodage + validation + commune_normalize + upsert : logique EXISTANTE, par closure
    # (si non publiable -> vigilance, comme aujourd'hui)
    ...
    recap["fermetures"] += 1
```

`structured_extractor_fn = lambda art: extract_structured(art, client=client, floor=…).model_dump()`
(le `.model_dump()` rend le résultat JSON-sérialisable pour le cache).

**Câblage `run.py`** : le pipeline principal doit brancher le nouvel extracteur
structuré — remplacer `extractor_fn=lambda art: extract(art, client=client, floor=since_date)`
par `extractor_fn=lambda art: extract_structured(art, client=client, floor=since_date).model_dump()`.
Le chemin `vigilance_review` (run.py) **garde** `extract` (legacy) — non migré en 2c-i.

## `openai_fallback`

**Ne pas remplacer** `extract_openai()` legacy — il reste le fallback profond de
l'ancien `extract()` (utilisé par `vigilance_review`). On **ajoute** à côté :
- `_schema_structured()` : JSON schema dédié pour `ExtractionResult` ;
- `extract_openai_structured(article, aujourdhui, ...) -> ExtractionResult` :
  même logique (budget, usage, POST) que `extract_openai` mais avec le schéma
  structuré et `ExtractionResult.model_validate`.

Ainsi les deux chemins coexistent : `extract()` → `extract_openai` (legacy),
`extract_structured()` → `extract_openai_structured` (nouveau). Aucune régression
sur le fallback existant.

## Gestion d'erreurs

- `extract_structured` : retries transitoires + fallback Sonnet sur erreur API
  (inchangé) ; sur échec définitif, lève (capté par `extract_cached` → statut
  `error` réessayable de 2a).
- `map_result` : pur, best-effort (aucune exception ; entrées incomplètes ignorées).
- Banque inconnue / `is_physical_agency=false` / commune vide → closure ignoré
  (pas d'upsert), mais un signal peut rester en vigilance.

## Tests (TDD)

`tests/test_extractor.py` (étendre) :
1. Parsing d'un `ExtractionResult` `single_closure` (client mocké) → 1 closure.
2. `list_closures` avec 3 agences → 3 `ClosureItem`.
3. `out_of_scope` → `ExtractionResult` non-None, closures/​signaux vides.
4. Fallback Sonnet sur erreur API transitoire (mock qui lève puis réussit).

`tests/test_ingest_map.py` (créer) :
5. Mapping closure_type/status/confidence → type/statut/fiabilite (table ci-dessus).
6. `statut_temporel` dérivé : date future→a_venir, passée→deja_fermee, absente+announced→a_venir, absente+confirmed→inconnu.
7. `is_physical_agency=false` → closure ignoré.
8. banque inconnue → closure ignoré.
9. `department_signals[]` → vigilance avec `departement` + `score`.
10. `vague_signals[]` → vigilance `departement=None`.

`tests/test_pipeline.py` (étendre) :
11. article `list_closures` (extracteur mocké) → N closures upsertées + sources.
12. article `department_signal` (closures vide, dept_signal présent) → 0 closure,
    1 vigilance créée.
13. le JSON riche est persisté : après extraction, `extractions.result_json`
    contient `article_type` (lecture directe de la table).

`tests/test_openai_fallback.py` (étendre) :
14. `extract_openai_structured` (POST mocké) parse un `ExtractionResult` ; le
    legacy `extract_openai`/`_schema()` reste inchangé (test existant vert).

Fixtures : `ExtractionResult` en clair ; clients mockés ; conn `:memory:`.

## Critères de réussite 2c-i

- Un article-liste est explosé nativement par l'IA en N closures.
- department/vague signals atterrissent en vigilances (rien perdu).
- Le JSON riche complet est lisible dans `extractions.result_json` (Cycle 3-ready).
- `EXTRACTION_VERSION=2` ; le cache 2a se réinvalide proprement.
- Aucun test existant cassé (ancien `extract()` conservé pour `vigilance_review`).
