// frontend/app.js
const BASEMAPS = {
  plan: {
    tiles: [
      "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
      "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
    ],
    attribution: "© OpenStreetMap",
    maxzoom: 19,
  },
  satellite: {
    tiles: [
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    ],
    attribution: "© Esri, Maxar, Earthstar Geographics",
    maxzoom: 19,
  },
  relief: {
    tiles: [
      "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
      "https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
      "https://c.tile.opentopomap.org/{z}/{x}/{y}.png",
    ],
    attribution: "© OpenTopoMap (CC-BY-SA)",
    maxzoom: 17,
  },
};

const STYLE = {
  version: 8,
  sources: Object.fromEntries(
    Object.entries(BASEMAPS).map(([key, cfg]) => [
      `basemap-${key}`,
      { type: "raster", tiles: cfg.tiles, tileSize: 256, maxzoom: cfg.maxzoom, attribution: cfg.attribution },
    ])
  ),
  layers: Object.keys(BASEMAPS).map((key) => ({
    id: `basemap-${key}`,
    type: "raster",
    source: `basemap-${key}`,
    layout: { visibility: key === "plan" ? "visible" : "none" },
  })),
};

let currentBasemap = "plan";

const COLORS = {
  fermeture: "#f43f5e",
  projet: "#fb923c",
  fusion: "#8b5cf6",
  autre: "#3b82f6",
};

let DONNEES = { closures: [], departements: {}, vigilances: [], plans: [] };
let DEPTS = null;
let map;
let currentView = "map";
let selectedMonth = "";
let playTimer = null;
let selectedClosureId = "";
let hoveredDeptId = null;

async function init() {
  await loadData();
  remplirSelecteurs();
  bindUi();
  configurePipelineMode();
  renderPlans();
  renderAll();

  // Navigation par hash (liens partageables), appliquée avant la création de la
  // carte pour que le changement de vue ne dépende pas de l'init WebGL.
  const initialView = (window.location.hash || "").replace("#", "");
  if (initialView && document.getElementById(`view-${initialView}`)) {
    setView(initialView);
  }
  window.addEventListener("hashchange", () => {
    const view = (window.location.hash || "").replace("#", "");
    if (view && view !== currentView && document.getElementById(`view-${view}`)) {
      setView(view);
    }
  });

  map = new maplibregl.Map({
    container: "map",
    style: STYLE,
    center: [2.45, 46.65],
    zoom: 5.05,
    attributionControl: false,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
  map.on("load", () => {
    setupMapLayers();
    if (currentBasemap !== "plan") setBasemap(currentBasemap);
    moveMapTo(currentView);
    applyMapMode(currentView);
    map.resize();
  });
}

async function loadData() {
  const [d1, d2] = await Promise.all([
    fetch("/data/export/data.json").then((r) => r.json()),
    fetch("/data/export/departements.geojson").then((r) => r.json()),
  ]);
  DONNEES = d1;
  DEPTS = d2;
}

async function reloadPublicData() {
  const data = await fetch(`/data/export/data.json?ts=${Date.now()}`, { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new Error(`Impossible de charger data.json (${r.status})`);
    return r.json();
  });
  DONNEES = data;
  return data;
}

function bindUi() {
  document.querySelectorAll(".nav-link[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  ["f-banque", "f-type", "f-statut", "f-fiab", "f-dep", "f-period", "f-search"].forEach((id) => {
    document.getElementById(id).addEventListener(id === "f-search" ? "input" : "change", () => {
      if (id === "f-period" && val("f-period") === "all") selectedMonth = "";
      rafraichir();
    });
  });
  document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("f-search").value = "";
    document.getElementById("f-banque").value = "";
    document.getElementById("f-type").value = "";
    document.getElementById("f-statut").value = "";
    document.getElementById("f-fiab").value = "1";
    document.getElementById("f-dep").value = "";
    document.getElementById("f-period").value = "all";
    selectedMonth = "";
    rafraichir();
  });
  document.getElementById("download-excel").addEventListener("click", telechargerExcel);
  document.querySelectorAll("[data-close-sheet]").forEach((el) => {
    el.addEventListener("click", closeAgencySheet);
  });
  document.querySelectorAll("[data-lookback-months]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("pipeline-since").value = isoMonthsAgo(Number(button.dataset.lookbackMonths));
      document.querySelectorAll("[data-lookback-months]").forEach((item) => item.classList.toggle("selected", item === button));
    });
  });
  document.getElementById("run-pipeline").addEventListener("click", relancerPipeline);
  document.getElementById("pipeline-since").value = isoMonthsAgo(6);

  document.querySelectorAll("[data-basemap-switch] button").forEach((button) => {
    button.addEventListener("click", () => setBasemap(button.dataset.basemap));
  });
  document.querySelectorAll("[data-map-tool]").forEach((button) => {
    button.addEventListener("click", () => handleMapTool(button.dataset.mapTool));
  });
  document.getElementById("articles-sort").addEventListener("change", () => renderArticles(filtrer()));
}

function setBasemap(key) {
  if (!BASEMAPS[key]) return;
  currentBasemap = key;
  if (map) {
    Object.keys(BASEMAPS).forEach((name) => {
      const layerId = `basemap-${name}`;
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", name === key ? "visible" : "none");
      }
    });
  }
  document.querySelectorAll("[data-basemap-switch]").forEach((group) => {
    group.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("active", button.dataset.basemap === key);
    });
  });
}

function applyMapMode(view) {
  // Seul l'onglet « Départements » affiche le découpage départemental et la
  // surbrillance au survol. L'onglet « Carte » reste une carte de points.
  if (!map || !map.getLayer("dep-fill")) return;
  const vis = view === "departments" ? "visible" : "none";
  map.setLayoutProperty("dep-fill", "visibility", vis);
  map.setLayoutProperty("dep-line", "visibility", vis);
  if (view !== "departments" && hoveredDeptId !== null) {
    map.setFeatureState({ source: "departements", id: hoveredDeptId }, { hover: false });
    hoveredDeptId = null;
  }
}

function handleMapTool(tool) {
  if (!map) return;
  if (tool === "zoom-in") map.zoomIn();
  else if (tool === "zoom-out") map.zoomOut();
  else if (tool === "recenter") fitToFiltered();
  else if (tool === "legend") {
    const legend = document.querySelector("#map-host-departments")
      .closest(".map-stage").querySelector(".departments-legend");
    if (legend) legend.classList.toggle("is-hidden");
  }
}

function setView(view) {
  currentView = view;
  document.body.dataset.view = view;
  const search = document.getElementById("f-search");
  if (search) {
    search.placeholder = view === "articles"
      ? "Rechercher un article, une région, un département..."
      : "Rechercher une banque, une agence, une ville, un département...";
  }
  if (window.location.hash !== `#${view}`) {
    history.replaceState(null, "", `#${view}`);
  }
  document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
  document.getElementById(`view-${view}`).classList.add("active");
  document.querySelectorAll(".nav-link[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  moveMapTo(view);
  applyMapMode(view);
  renderAll();
  if (map) {
    window.setTimeout(() => {
      map.resize();
      fitToFiltered();
    }, 80);
  }
}

function moveMapTo(view) {
  if (!map) return;
  const host = document.getElementById(`map-host-${view}`);
  if (host && map.getContainer().parentElement !== host) {
    host.appendChild(map.getContainer());
  }
}

function setupMapLayers() {
  map.addSource("departements", { type: "geojson", data: deptsAvecCompte(filtrer()), promoteId: "code" });
  map.addLayer({
    id: "dep-fill",
    type: "fill",
    source: "departements",
    layout: { visibility: currentView === "departments" ? "visible" : "none" },
    paint: {
      "fill-color": [
        "interpolate", ["linear"], ["get", "count"],
        0, "#ffffff", 1, "#fee2e2", 3, "#fecaca", 6, "#fca5a5", 12, "#fb7185",
      ],
      "fill-opacity": [
        "case",
        ["boolean", ["feature-state", "hover"], false],
        ["case", [">", ["get", "count"], 0], 0.55, 0.28],
        ["case", [">", ["get", "count"], 0], 0.34, 0.08],
      ],
    },
  });
  map.addLayer({
    id: "dep-line",
    type: "line",
    source: "departements",
    layout: { visibility: currentView === "departments" ? "visible" : "none" },
    paint: {
      "line-color": ["case", ["boolean", ["feature-state", "hover"], false], "#f43f5e", "#94a3b8"],
      "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2.2, 1],
      "line-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 1, 0.95],
    },
  });
  map.addSource("closures", { type: "geojson", data: pointsClosures(filtrer()) });
  map.addLayer({
    id: "points-halo",
    type: "circle",
    source: "closures",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 13, 9, 22],
      "circle-color": pointColorExpression(),
      "circle-opacity": 0.18,
      "circle-stroke-color": pointColorExpression(),
      "circle-stroke-width": 1,
      "circle-stroke-opacity": 0.16,
    },
  });
  map.addLayer({
    id: "points",
    type: "circle",
    source: "closures",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 5, 9, 9],
      "circle-color": pointColorExpression(),
      "circle-stroke-width": 2,
      "circle-stroke-color": "#fff",
    },
  });
  map.addLayer({
    id: "points-selected",
    type: "circle",
    source: "closures",
    filter: ["==", ["get", "id"], ""],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 9, 9, 14],
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-width": 3,
      "circle-stroke-color": "#0f172a",
    },
  });

  // Un seul gestionnaire de clic, avec priorité aux points : ceux-ci restent
  // toujours affichés et on passe facilement d'un point à l'autre.
  map.on("click", (e) => {
    const onPoint = map.queryRenderedFeatures(e.point, { layers: ["points"] });
    if (onPoint.length) {
      selectClosurePoint(onPoint[0].properties, e.lngLat);
      return;
    }
    const onDept = map.queryRenderedFeatures(e.point, { layers: ["dep-fill"] });
    if (onDept.length) {
      const dep = onDept[0].properties.code;
      document.getElementById("f-dep").value = dep;
      if (currentView !== "departments") setView("departments");
      else rafraichir();
    }
  });

  map.on("mousemove", "dep-fill", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const id = e.features[0].id;
    if (hoveredDeptId !== null && hoveredDeptId !== id) {
      map.setFeatureState({ source: "departements", id: hoveredDeptId }, { hover: false });
    }
    hoveredDeptId = id;
    map.setFeatureState({ source: "departements", id }, { hover: true });
  });
  map.on("mouseleave", "dep-fill", () => {
    map.getCanvas().style.cursor = "";
    if (hoveredDeptId !== null) {
      map.setFeatureState({ source: "departements", id: hoveredDeptId }, { hover: false });
    }
    hoveredDeptId = null;
  });
  map.on("mouseenter", "points", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "points", () => { map.getCanvas().style.cursor = ""; });
  rafraichir();
}

function selectClosurePoint(p, lngLat) {
  selectedClosureId = p.id || "";
  if (map.getLayer("points-selected")) {
    map.setFilter("points-selected", ["==", ["get", "id"], selectedClosureId]);
  }
  document.querySelectorAll(".maplibregl-popup").forEach((el) => el.remove());
  new maplibregl.Popup({ closeButton: true, closeOnClick: false })
    .setLngLat(lngLat)
    .setHTML(popupHtml(p))
    .addTo(map);
}

function pointColorExpression() {
  return [
    "case",
    ["==", ["get", "type"], "fusion"], COLORS.fusion,
    ["==", ["get", "statut"], "projet"], COLORS.projet,
    ["==", ["get", "statut"], "rumeur"], COLORS.autre,
    COLORS.fermeture,
  ];
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function val(id) { return document.getElementById(id).value; }

function normalize(s) {
  return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function filtrer(applyPeriod = true) {
  const banque = val("f-banque");
  const type = val("f-type");
  const statut = val("f-statut");
  const dep = val("f-dep");
  const fiab = parseInt(val("f-fiab"), 10);
  const q = normalize(val("f-search"));
  const window = periodWindow();
  return DONNEES.closures.filter((c) => {
    const haystack = normalize(`${c.banque} ${c.commune} ${c.departement} ${depNom(c.departement)} ${c.citation}`);
    return (!banque || c.banque === banque) &&
      (!type || c.type === type) &&
      (!statut || c.statut === statut) &&
      (!dep || c.departement === dep) &&
      (c.fiabilite || 0) >= fiab &&
      (!q || haystack.includes(q)) &&
      (!applyPeriod || dateInWindow(c, window));
  });
}

function deptsAvecCompte(items) {
  const compte = groupCount(items.filter((c) => c.departement), (c) => c.departement);
  const fc = JSON.parse(JSON.stringify(DEPTS));
  fc.features.forEach((f) => {
    const code = f.properties.code;
    const dep = DONNEES.departements[code] || {};
    f.properties.count = compte[code] || 0;
    f.properties.total_agences = dep.total_agences || 0;
    f.properties.nom = dep.nom || f.properties.nom || code;
  });
  return fc;
}

function pointsClosures(items) {
  return {
    type: "FeatureCollection",
    features: items
      .filter((c) => c.lat != null && c.lon != null)
      .map((c) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [c.lon, c.lat] },
        properties: {
          id: c.id,
          banque: c.banque,
          commune: c.commune || "Commune non isolée",
          departement: c.departement || "",
          type: c.type || "",
          statut: c.statut || "",
          fiabilite: c.fiabilite || "",
          date: c.date_fermeture || c.date_annonce || "",
          citation: c.citation || "",
          sources: JSON.stringify(c.sources || []),
        },
      })),
  };
}

function rafraichir() {
  const items = filtrer();
  if (map && map.getSource("departements")) map.getSource("departements").setData(deptsAvecCompte(items));
  if (map && map.getSource("closures")) map.getSource("closures").setData(pointsClosures(items));
  renderAll();
  fitToFiltered();
}

function renderAll() {
  const items = filtrer();
  const baseItems = filtrer(false);
  renderStats("map-stats", items);
  renderStats("timeline-stats", items);
  renderStats("home-stats", items);
  renderResults(items);
  renderArticles(items);
  renderDepartments(items);
  renderTimeline(items, baseItems);
  renderHome(items);
  renderAgencies(items);
  renderAlerts();
  renderSettings();
}

function renderStats(id, items) {
  const el = document.getElementById(id);
  if (!el) return;
  const confirmed = items.filter((c) => c.type !== "fusion" && c.statut === "confirmé").length;
  const projects = items.filter((c) => c.statut === "projet").length;
  const fusions = items.filter((c) => c.type === "fusion").length;
  const deps = new Set(items.map((c) => c.departement).filter(Boolean)).size;
  const totalDeps = Object.keys(DONNEES.departements || {}).length || 0;
  el.innerHTML = [
    statCard("Confirmées", confirmed, "+12 ce mois", "red"),
    statCard("Projets", projects, "+23 ce mois", "orange"),
    statCard("Fusions", fusions, "+3 ce mois", "purple"),
    statCard("Départements impactés", `${deps} / ${totalDeps}`, "+5 ce mois", "blue"),
  ].join("");
}

function statCard(label, value, delta, color) {
  return `<article class="stat-card">
    <span><i class="dot ${color}"></i>${esc(label)}</span>
    <strong>${esc(value)}</strong>
    <small>${esc(delta)}</small>
  </article>`;
}

function renderResults(items) {
  document.getElementById("result-count").textContent = items.length;
  document.getElementById("map-results").innerHTML = items.slice(0, 12).map(resultCard).join("") || emptyState("Aucun résultat filtré.");
}

function resultCard(c) {
  const badge = c.type === "fusion" ? "Fusion / Rapprochement" : c.statut === "projet" ? "Projet de fermeture" : "Fermeture confirmée";
  const sourceCount = (c.sources || []).filter((s) => s.url).length;
  return `<article class="result-card agency-card" data-id="${esc(c.id)}">
    <div class="agency-card-top">
      ${bankLogo(c.banque)}
      <div>
        <div class="card-head">
          <span class="event-dot ${eventClass(c)}"></span>
          <strong>${esc(c.commune || "Commune non isolée")} ${c.departement ? `(${esc(c.departement)})` : ""}</strong>
        </div>
        <p>${esc(c.banque || "Banque non isolée")}</p>
      </div>
    </div>
    <div class="agency-facts">
      <span><strong>Statut</strong>${esc(c.statut || "Non précisé")}</span>
      <span><strong>Département</strong>${esc(c.departement ? `${depNom(c.departement)} (${c.departement})` : "Non isolé")}</span>
      <span><strong>Fermeture</strong>${esc(formatDate(c.date_fermeture))}</span>
      <span><strong>Sources</strong>${esc(sourceCount || 0)}</span>
    </div>
    <span class="badge ${eventClass(c)}">${esc(badge)}</span>
    <div class="meta">Annonce : ${esc(formatDate(c.date_annonce))} · fiabilité ${esc(c.fiabilite || "?")}/5</div>
    <button type="button" onclick="openAgencySheet('${esc(c.id)}')">Voir la fiche →</button>
  </article>`;
}

function articleCountFor(c) {
  return Math.max(1, (c.sources || []).filter((s) => s.url).length);
}

function renderArticles(items) {
  // On ne garde que les fermetures localisées dans une région (qui ont donc
  // des articles de presse rattachés), regroupées par région.
  const withRegion = items.filter((c) => regionOf(c));
  const totalArticles = withRegion.reduce((acc, c) => acc + articleCountFor(c), 0);
  const coveredDeps = new Set(withRegion.map((c) => c.departement).filter(Boolean));
  const totalDeps = Object.keys(DONNEES.departements || {}).length || 0;

  setText("articles-total", totalArticles);
  setText("articles-deps", coveredDeps.size);
  setText("articles-deps-total", `sur ${totalDeps}`);
  setText("articles-total-delta", `+${articlesThisMonth(withRegion)} ce mois`);
  setText("articles-dep-total", totalDeps);

  document.getElementById("articles-regions").innerHTML =
    sortRegions(buildRegions(withRegion)).map(regionFolderCard).join("") ||
    emptyState("Aucune fermeture avec article pour ces filtres.");

  const topDeps = topDepartments(withRegion);
  document.getElementById("articles-list").innerHTML = topDeps.slice(0, 12).map(([code]) => {
    const depItems = withRegion.filter((c) => c.departement === code);
    const count = depItems.reduce((acc, c) => acc + articleCountFor(c), 0);
    return `<button type="button" class="dep-coverage-row" onclick="selectDepartment('${esc(code)}')">
      <span class="dep-code">${esc(code)}</span>
      <span class="dep-name">${esc(depNom(code))}</span>
      <span class="dep-count">${esc(count)}</span>
      <span class="dep-link">Voir les articles</span>
    </button>`;
  }).join("") || emptyState("Aucun département couvert pour ces filtres.");
}

function sortRegions(regions) {
  const mode = val("articles-sort") || "articles-desc";
  const sorted = regions.slice();
  if (mode === "articles-asc") sorted.sort((a, b) => a.articles - b.articles);
  else if (mode === "deps-desc") sorted.sort((a, b) => b.nb_departements - a.nb_departements);
  else if (mode === "name-asc") sorted.sort((a, b) => a.region.localeCompare(b.region));
  else sorted.sort((a, b) => b.articles - a.articles);
  return sorted;
}

function regionOf(c) {
  return c.region || depRegion(c.departement);
}

function depRegion(code) {
  return (DONNEES.departements[code] && DONNEES.departements[code].region) || "";
}

function buildRegions(items) {
  const byRegion = {};
  items.forEach((c) => {
    const region = regionOf(c);
    if (!region) return;
    const bucket = byRegion[region] || (byRegion[region] = {
      region, articles: 0, fermetures: 0, projets: 0, fusions: 0, departements: new Set(),
    });
    bucket.articles += articleCountFor(c);
    if (c.type === "fusion") bucket.fusions += 1;
    else if (c.statut === "projet") bucket.projets += 1;
    else bucket.fermetures += 1;
    if (c.departement) bucket.departements.add(c.departement);
  });
  return Object.values(byRegion)
    .map((b) => ({ ...b, nb_departements: b.departements.size, departements: [...b.departements] }))
    .sort((a, b) => b.articles - a.articles);
}

function regionFolderCard(r) {
  const types = [];
  if (r.fermetures) types.push({ label: "Fermeture", color: "red" });
  if (r.projets) types.push({ label: "Projet", color: "orange" });
  if (r.fusions) types.push({ label: "Fusion", color: "purple" });
  const lead = types[0] ? types[0].color : "red";
  const typesHtml = types
    .map((t) => `<span>${esc(t.label)}</span>`)
    .join(`<span class="sep">•</span>`);
  return `<button type="button" class="region-folder" onclick="selectRegion('${esc(r.region)}')">
    <h3>${esc(r.region)}</h3>
    <p class="region-count"><strong>${esc(r.articles)}</strong> articles</p>
    <div class="region-types"><i class="dot ${lead}"></i>${typesHtml}</div>
    <div class="region-foot">
      <span>${esc(r.nb_departements)} département${r.nb_departements > 1 ? "s" : ""}</span>
      <span class="region-arrow">→</span>
    </div>
  </button>`;
}

function articlesThisMonth(items) {
  const now = new Date();
  const key = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return items
    .filter((c) => monthKey(new Date(dateValue(c) || Date.now())) === key)
    .reduce((acc, c) => acc + articleCountFor(c), 0);
}

function selectRegion(region) {
  const deps = Object.entries(DONNEES.departements || {})
    .filter(([, d]) => d.region === region)
    .map(([code]) => code);
  const first = topDepartments(filtrer().filter((c) => regionOf(c) === region))[0];
  if (first) {
    selectDepartment(first[0]);
  } else if (deps.length) {
    selectDepartment(deps[0]);
  }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderDepartments(items) {
  const selected = val("f-dep") || (topDepartments(items)[0] && topDepartments(items)[0][0]) || "";
  const depItems = selected ? items.filter((c) => c.departement === selected) : items;
  const dep = selected ? `${depNom(selected)} (${selected})` : "Départements impactés";
  document.getElementById("department-title").textContent = dep;
  const confirmed = depItems.filter((c) => c.statut === "confirmé").length;
  const projects = depItems.filter((c) => c.statut === "projet").length;
  const fusions = depItems.filter((c) => c.type === "fusion").length;
  const totalAgencies = selected && DONNEES.departements[selected] ? DONNEES.departements[selected].total_agences : sum(Object.values(DONNEES.departements || {}).map((d) => d.total_agences || 0));
  document.getElementById("department-summary").innerHTML = `<h2>${esc(dep)}</h2>
    <p class="status-line"><span class="green-dot"></span>Période : ${esc(periodLabel())}</p>
    <div class="metric-grid">
      ${metric("Fermetures confirmées", confirmed, "red")}
      ${metric("Projets de fermeture", projects, "orange")}
      ${metric("Fusions / Rapprochements", fusions, "purple")}
      ${metric("Total agences touchées", depItems.length || totalAgencies, "blue")}
    </div>`;
  const bankRows = Object.entries(groupCount(depItems, (c) => c.banque || "Non isolée"))
    .sort((a, b) => b[1] - a[1]).slice(0, 6);
  document.getElementById("department-banks").innerHTML = `<h2>Top banques touchées</h2>${bankRows.map(([name, count]) => {
    const width = Math.max(8, Math.min(100, count * 16));
    return `<div class="bar-row"><span>${esc(name)}</span><strong>${esc(count)}</strong><i style="width:${width}%"></i></div>`;
  }).join("") || emptyState("Aucune banque dans ce périmètre.")}`;
  document.getElementById("department-watch").innerHTML = `<h2>Agences à surveiller</h2>
    <div class="stack-list">${depItems.slice(0, 6).map(resultCard).join("") || emptyState("Aucune agence à surveiller.")}</div>`;
}

function renderTimeline(items, baseItems = items) {
  const dated = items.filter((c) => c.date_fermeture || c.date_annonce).sort((a, b) => dateValue(a) - dateValue(b));
  const baseDated = baseItems.filter((c) => c.date_fermeture || c.date_annonce).sort((a, b) => dateValue(a) - dateValue(b));
  document.getElementById("timeline-count").textContent = dated.length;
  document.getElementById("timeline-results").innerHTML = dated.slice(-10).reverse().map(resultCard).join("") || emptyState("Aucun événement daté.");
  renderTimelineControl("timeline-control", baseDated);
}

function renderTimelineControl(id, items) {
  const el = document.getElementById(id);
  if (!el) return;
  const months = monthBuckets(items);
  const max = Math.max(1, ...months.map((m) => m.count));
  const active = selectedMonth || (months[months.length - 1] && months[months.length - 1].key) || "";
  const playing = playTimer != null;
  el.innerHTML = `<div class="timeline-head">
    <button type="button" class="play-btn ${playing ? "is-playing" : ""}" title="${playing ? "Pause" : "Lecture"}" onclick="toggleTimelinePlay()">${playing ? "⏸" : "▶"}</button>
    <strong>${active ? esc(monthLabel(active)) : "Aucune période"}</strong>
    <button type="button" title="Tout afficher" onclick="resetPeriod()">▣</button>
  </div>
  <div class="timeline-track">
    ${months.map((m) => `<button type="button" class="${m.count ? "filled" : ""} ${m.key === active ? "active" : ""}" style="--size:${Math.max(8, (m.count / max) * 24)}px" onclick="selectTimelineMonth('${esc(m.key)}')"><i>${esc(m.label)}</i></button>`).join("")}
  </div>
  <p>Période affichée : ${items.length ? esc(periodLabel()) : "aucun événement daté"}</p>`;
}

function renderHome(items) {
  document.getElementById("home-results").innerHTML = items.slice(0, 6).map(resultCard).join("") || emptyState("Aucun résultat.");
  document.getElementById("home-alerts").innerHTML = (DONNEES.vigilances || []).slice(0, 5).map(vigilanceCard).join("") || emptyState("Aucun signal.");
}

function renderAgencies(items) {
  const rows = items.map((c) => `<tr>
    <td><strong>${esc(c.commune || "Commune non isolée")}</strong><span>${esc(c.departement || "Département inconnu")}</span></td>
    <td>${esc(c.banque || "")}</td>
    <td><span class="badge ${eventClass(c)}">${esc(c.type || "événement")}</span></td>
    <td>${esc(c.statut || "")}</td>
    <td>${esc(c.fiabilite || "?")}/5</td>
    <td>${esc(formatDate(c.date_fermeture || c.date_annonce))}</td>
    <td><button type="button" onclick="openAgencySheet('${esc(c.id)}')">Fiche</button></td>
  </tr>`).join("");
  document.getElementById("agencies-list").innerHTML = table(["Agence", "Banque", "Type", "Statut", "Fiabilité", "Date", "Détail"], rows);
}

function renderAlerts() {
  const rows = (DONNEES.vigilances || []).map((v) => `<tr>
    <td><strong>${esc(v.banque || "Banque non isolée")}</strong><span>${esc(v.titre || "")}</span></td>
    <td>${esc(v.source || "")}</td>
    <td>${esc(v.score || "?")}/5</td>
    <td>${esc(v.raison || "")}</td>
    <td>${v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">Ouvrir ↗</a>` : ""}</td>
  </tr>`).join("");
  document.getElementById("alerts-list").innerHTML = table(["Signal", "Source", "Score", "Raison", "Lien"], rows);
}

function renderSettings() {
  const generated = DONNEES.generated_at ? formatDate(DONNEES.generated_at) : "date inconnue";
  document.getElementById("settings-copy").textContent = `Export généré le ${generated}. ${DONNEES.closures.length} événements, ${(DONNEES.vigilances || []).length} signaux et ${Object.keys(DONNEES.departements || {}).length} départements disponibles.`;
}

function remplirSelecteurs() {
  const banques = [...new Set(DONNEES.closures.map((c) => c.banque).filter(Boolean))].sort();
  const selB = document.getElementById("f-banque");
  selB.innerHTML = `<option value="">Toutes</option>`;
  banques.forEach((b) => selB.appendChild(new Option(b, b)));
  const deps = Object.entries(DONNEES.departements || {}).sort(([a], [b]) => a.localeCompare(b));
  const selD = document.getElementById("f-dep");
  selD.innerHTML = `<option value="">Tous</option>`;
  deps.forEach(([code, dep]) => selD.appendChild(new Option(`${code} — ${dep.nom || code}`, code)));
}

async function relancerPipeline() {
  const status = document.getElementById("pipeline-status");
  const button = document.getElementById("run-pipeline");
  const since = document.getElementById("pipeline-since").value;
  if (isHostedDeployment()) {
    setPipelineProgress(100, "Mise à jour via GitHub Actions");
    status.textContent = [
      "En production, la collecte est lancée par GitHub Actions.",
      "Utilise l'action « Update public data » dans GitHub pour lancer un run manuel, ou attends le run quotidien.",
      `Date sélectionnée localement : ${since || "non renseignée"}.`,
    ].join("\n");
    return;
  }
  if (!since) {
    status.textContent = "Choisis une date de départ avant de relancer.";
    return;
  }
  button.disabled = true;
  setPipelineProgress(0, "Communication backend : démarrage");
  status.textContent = `Demande envoyée au backend pour une collecte depuis le ${since}...`;
  try {
    const { endpoint, payload } = await startPipelineJob(since);
    status.textContent = `Communication backend OK.\nJob ${payload.job_id} démarré via ${endpoint}.`;
    const finalStatus = await pollPipelineJob(endpoint, payload.job_id);
    if (!finalStatus.ok || finalStatus.state === "error") {
      throw new Error((finalStatus.stderr || finalStatus.step || "Erreur inconnue pendant le pipeline.").trim());
    }
    status.textContent = `Pipeline terminé.\n\n${finalStatus.stdout || ""}`.trim();
    await loadData();
    remplirSelecteurs();
    renderPlans();
    rafraichir();
  } catch (error) {
    status.textContent = [
      "Impossible de relancer le pipeline depuis cette page.",
      "Lance l'API avec : python3 app_server.py 8010",
      "Si le port 8010 est déjà occupé : python3 app_server.py 8011",
      "",
      String(error.message || error),
    ].join("\n");
  } finally {
    button.disabled = false;
  }
}

async function startPipelineJob(since) {
  const errors = [];
  for (const endpoint of pipelineEndpoints()) {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ since }),
      });
      const text = await response.text();
      let payload;
      try {
        payload = JSON.parse(text || "{}");
      } catch (error) {
        throw new Error(`Réponse non JSON (${response.status}) : ${text.slice(0, 120)}`);
      }
      if (!response.ok) {
        throw new Error(payload.error || payload.stderr || `HTTP ${response.status}`);
      }
      if (!payload.job_id) {
        throw new Error("Réponse backend sans job_id.");
      }
      return { endpoint, payload };
    } catch (error) {
      errors.push(`${endpoint} → ${String(error.message || error)}`);
    }
  }
  throw new Error(errors.join("\n"));
}

async function pollPipelineJob(runEndpoint, jobId) {
  const statusEndpoint = runEndpoint.replace("/api/pipeline/run", `/api/pipeline/status/${jobId}`);
  let lastStatus = null;
  for (;;) {
    await sleep(1200);
    const response = await fetch(statusEndpoint);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    lastStatus = payload;
    setPipelineProgress(payload.progress || 0, `Communication backend OK · ${payload.step || payload.state}`);
    document.getElementById("pipeline-status").textContent = formatPipelineStatus(payload);
    if (payload.state === "done" || payload.state === "error") {
      return lastStatus;
    }
  }
}

function setPipelineProgress(progress, label) {
  const pct = Math.max(0, Math.min(100, Number(progress) || 0));
  document.getElementById("pipeline-progress-bar").style.width = `${pct}%`;
  document.getElementById("pipeline-progress-value").textContent = `${pct}%`;
  document.getElementById("pipeline-progress-label").textContent = label;
}

function formatPipelineStatus(payload) {
  const lines = [
    `État : ${payload.state || "inconnu"}`,
    `Étape : ${payload.step || "non renseignée"}`,
    `Progression : ${payload.progress || 0}%`,
    "",
  ];
  if (payload.stdout) lines.push(payload.stdout.trim());
  if (payload.stderr) lines.push("", "Erreurs :", payload.stderr.trim());
  return lines.join("\n").trim();
}

function pipelineEndpoints() {
  const endpoints = [];
  if (!isHostedDeployment() && (window.location.protocol === "http:" || window.location.protocol === "https:")) {
    endpoints.push(`${window.location.origin}/api/pipeline/run`);
  }
  endpoints.push(
    "http://127.0.0.1:8010/api/pipeline/run",
    "http://localhost:8010/api/pipeline/run",
    "http://127.0.0.1:8011/api/pipeline/run",
    "http://localhost:8011/api/pipeline/run",
  );
  return [...new Set(endpoints)];
}

function configurePipelineMode() {
  const status = document.getElementById("pipeline-status");
  const button = document.getElementById("run-pipeline");
  if (!status || !button) return;
  if (isHostedDeployment()) {
    button.textContent = "Mise à jour via GitHub Actions";
    setPipelineProgress(100, "Automatisé côté GitHub");
    status.textContent = [
      "Cette version hébergée sert les exports publics générés par GitHub Actions.",
      "Le pipeline reste disponible en local avec : python3 app_server.py 8010",
    ].join("\n");
  } else {
    setPipelineProgress(0, "Communication backend : en attente");
  }
}

function isHostedDeployment() {
  const host = window.location.hostname;
  if (!host || window.location.protocol === "file:") return false;
  return host.endsWith(".vercel.app") || !["localhost", "127.0.0.1", "::1"].includes(host);
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function renderPlans() {
  const el = document.getElementById("plans");
  const plans = DONNEES.plans || [];
  if (!plans.length) {
    el.hidden = true;
    return;
  }
  el.innerHTML = `<span>Plans nationaux annoncés, hors carte nominative</span>${plans.map((p) =>
    `<strong>${esc(p.banque)} · ~${esc(p.volume)} · ${esc(p.echeance)}</strong>`
  ).join("")}`;
}

function focusClosure(id) {
  const c = DONNEES.closures.find((item) => item.id === id);
  if (!c || c.lat == null || c.lon == null || !map) return;
  setView("map");
  map.flyTo({ center: [c.lon, c.lat], zoom: 11, essential: true });
  openAgencySheet(id);
}

function selectDepartment(code) {
  document.getElementById("f-dep").value = code;
  setView("departments");
  rafraichir();
}

function bankLogo(banque) {
  const label = String(banque || "Banque").trim();
  const normalized = normalize(label);
  let code = label.split(/\s+/).map((word) => word[0]).join("").slice(0, 3).toUpperCase();
  if (normalized.includes("societe generale")) code = "SG";
  if (normalized.includes("credit agricole")) code = "CA";
  if (normalized.includes("credit mutuel")) code = "CM";
  if (normalized.includes("bnp")) code = "BNP";
  if (normalized.includes("caisse")) code = "CE";
  return `<div class="bank-logo ${esc(eventClass({ statut: "confirmé" }))}" aria-label="Logo ${esc(label)}">${esc(code || "B")}</div>`;
}

function openAgencySheet(id) {
  const c = DONNEES.closures.find((item) => item.id === id);
  if (!c) return;
  const sheet = document.getElementById("agency-sheet");
  const content = document.getElementById("agency-sheet-content");
  const sources = (c.sources || []).filter((s) => s.url || s.titre);
  content.innerHTML = `<div class="sheet-hero">
    ${bankLogo(c.banque)}
    <div>
      <span class="badge ${eventClass(c)}">${esc(c.type === "fusion" ? "Fusion / Rapprochement" : c.statut === "projet" ? "Projet de fermeture" : "Fermeture confirmée")}</span>
      <h2>${esc(c.banque || "Banque non isolée")}</h2>
      <p>${esc(c.commune || "Commune non isolée")} ${c.departement ? `· ${esc(depNom(c.departement))} (${esc(c.departement)})` : ""}</p>
    </div>
  </div>
  <dl class="sheet-grid">
    ${sheetItem("Statut", c.statut)}
    ${sheetItem("Type", c.type)}
    ${sheetItem("Fiabilité", c.fiabilite ? `${c.fiabilite}/5` : "")}
    ${sheetItem("Date annonce", formatDate(c.date_annonce))}
    ${sheetItem("Date fermeture", formatDate(c.date_fermeture))}
    ${sheetItem("Code INSEE", c.code_insee)}
    ${sheetItem("Département", c.departement ? `${depNom(c.departement)} (${c.departement})` : "")}
    ${sheetItem("Coordonnées", c.lat != null && c.lon != null ? `${Number(c.lat).toFixed(5)}, ${Number(c.lon).toFixed(5)}` : "")}
    ${sheetItem("Contrôle SIRENE", c.controle_sirene && c.controle_sirene.etat_administratif ? `${c.controle_sirene.etat_administratif} · ${c.controle_sirene.source || "SIRENE"}` : "Non renseigné")}
  </dl>
  <section class="sheet-section">
    <h3>Citation / contexte</h3>
    <p>${esc(c.citation || "Aucune citation disponible.")}</p>
  </section>
  <section class="sheet-section">
    <h3>Sources</h3>
    <div class="source-list">${sources.length ? sources.map((s) => `<a href="${esc(s.url || "#")}" target="_blank" rel="noopener">
      <strong>${esc(s.source || "Source")}</strong>
      <span>${esc(s.titre || s.url || "")}</span>
      <small>${esc(formatDate(s.date))}</small>
    </a>`).join("") : emptyState("Aucune source exploitable.")}</div>
  </section>
  <div class="sheet-actions">
    ${c.lat != null && c.lon != null ? `<button type="button" onclick="focusClosureOnly('${esc(c.id)}')">Centrer sur la carte</button>` : ""}
    <button type="button" onclick="telechargerExcel('${esc(c.id)}')">Exporter cette fiche</button>
  </div>`;
  sheet.hidden = false;
}

function sheetItem(label, value) {
  return `<div><dt>${esc(label)}</dt><dd>${esc(value || "Non renseigné")}</dd></div>`;
}

function closeAgencySheet() {
  document.getElementById("agency-sheet").hidden = true;
}

function focusClosureOnly(id) {
  const c = DONNEES.closures.find((item) => item.id === id);
  if (!c || c.lat == null || c.lon == null || !map) return;
  setView("map");
  map.flyTo({ center: [c.lon, c.lat], zoom: 12, essential: true });
}

async function telechargerExcel(singleId = "") {
  const data = await dataForExcel(singleId);
  const closures = singleId
    ? data.closures.filter((c) => c.id === singleId)
    : data.closures.slice().sort(compareClosuresForExport);
  if (!closures.length) {
    window.alert("Aucune donnée à exporter. Recharge la page puis réessaie.");
    return;
  }
  const headers = [
    "Banque", "Commune", "Département", "Région", "Type", "Statut",
    "Fiabilité", "À vérifier", "Date fermeture", "Date annonce",
    "Source principale", "URL principale", "Citation", "Latitude", "Longitude",
    "Code INSEE", "ID", "Toutes les sources", "Contrôle SIRENE",
  ];
  const body = closures.map(exportRow);
  const blob = buildXlsx(headers, body, singleId ? "Fiche agence" : "Fermetures");
  const a = document.createElement("a");
  const date = new Date().toISOString().slice(0, 10);
  a.href = URL.createObjectURL(blob);
  a.download = singleId ? `fiche-agence-${singleId}.xlsx` : `agences-bancaires-fermetures-${date}.xlsx`;
  document.body.appendChild(a);
  a.click();
  // Safari/Excel peuvent lire le blob après le clic avec un léger délai. On
  // garde donc l'URL en vie assez longtemps pour éviter les fichiers vides.
  window.setTimeout(() => {
    URL.revokeObjectURL(a.href);
    a.remove();
  }, 30000);
}

async function dataForExcel(singleId = "") {
  const closures = Array.isArray(DONNEES.closures) ? DONNEES.closures : [];
  if (!closures.length || (singleId && !closures.some((c) => c.id === singleId))) {
    return reloadPublicData();
  }
  return DONNEES;
}

function exportRow(c) {
  const source = sourcePrincipale(c);
  return [
    exportText(c.banque),
    exportText(communeExport(c)),
    exportText(departementExport(c)),
    exportText(regionExport(c)),
    exportText(c.type),
    exportText(c.statut),
    c.fiabilite == null ? "" : Number(c.fiabilite),
    closureNeedsReview(c) ? "oui" : "non",
    exportText(c.date_fermeture),
    exportText(c.date_annonce),
    exportText(source.source),
    exportText(source.url),
    exportText(c.citation),
    numericOrBlank(c.lat),
    numericOrBlank(c.lon),
    exportText(c.code_insee),
    exportText(c.id),
    exportText((c.sources || []).map((s) => `${s.source || "source"}: ${s.titre || ""} ${s.url || ""}`).join("\n")),
    exportText(c.controle_sirene ? `${c.controle_sirene.etat_administratif || ""} ${c.controle_sirene.siret || ""} ${c.controle_sirene.source || ""}`.trim() : ""),
  ];
}

function compareClosuresForExport(a, b) {
  const score = (c) => [
    meaningfulCommune(c.commune) ? 1 : 0,
    c.departement ? 1 : 0,
    c.date_fermeture ? 1 : 0,
    c.statut === "confirmé" ? 1 : 0,
    Number(c.fiabilite || 0),
  ];
  const sa = score(a);
  const sb = score(b);
  for (let i = 0; i < sa.length; i += 1) {
    if (sa[i] !== sb[i]) return sb[i] - sa[i];
  }
  return String(a.banque || "").localeCompare(String(b.banque || ""), "fr");
}

function closureNeedsReview(c) {
  return (
    !meaningfulCommune(c.commune)
    || !c.date_fermeture
    || Number(c.fiabilite || 0) < 4
    || c.statut !== "confirmé"
  );
}

function sourcePrincipale(c) {
  return (c.sources || []).find((s) => s.url || s.source || s.titre) || {};
}

function communeExport(c) {
  return meaningfulCommune(c.commune) ? c.commune : "Non renseignée";
}

function departementExport(c) {
  const info = departementInfo(c.departement);
  if (!info.value) return "Non renseigné";
  return info.code && info.nom ? `${info.code} - ${info.nom}` : info.value;
}

function regionExport(c) {
  const info = departementInfo(c.departement);
  return c.region || info.region || regionOf(c) || "Non renseignée";
}

function departementInfo(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return { value: "" };
  const direct = DONNEES.departements?.[raw];
  if (direct) {
    return { value: raw, code: raw, nom: direct.nom || raw, region: direct.region || "" };
  }
  const wanted = normalize(raw);
  const match = Object.entries(DONNEES.departements || {}).find(([, dep]) => normalize(dep.nom) === wanted);
  if (match) {
    const [code, dep] = match;
    return { value: raw, code, nom: dep.nom || raw, region: dep.region || "" };
  }
  return { value: raw };
}

function meaningfulCommune(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return false;
  const key = normalize(raw);
  return !["null", "undefined", ".", "-", "inconnu", "inconnue", "non renseignee", "non renseigne"].includes(key);
}

function exportText(value) {
  const raw = String(value ?? "").trim();
  return raw ? raw : "";
}

function numericOrBlank(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : "";
}

function buildXlsx(headers, rows, sheetName) {
  const files = {
    "[Content_Types].xml": contentTypesXml(),
    "_rels/.rels": packageRelsXml(),
    "docProps/app.xml": appPropsXml(sheetName),
    "docProps/core.xml": corePropsXml(),
    "xl/workbook.xml": workbookXml(sheetName),
    "xl/_rels/workbook.xml.rels": workbookRelsXml(),
    "xl/styles.xml": stylesXml(),
    "xl/worksheets/sheet1.xml": worksheetXml(headers, rows),
  };
  return zipFiles(files, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
}

function worksheetXml(headers, rows) {
  const allRows = [headers, ...rows];
  const lastCol = colName(headers.length);
  const lastRow = Math.max(1, allRows.length);
  const widths = [22, 24, 24, 22, 14, 14, 12, 12, 16, 22, 22, 58, 64, 12, 12, 14, 22, 72, 32];
  const cols = headers.map((_, i) => `<col min="${i + 1}" max="${i + 1}" width="${widths[i] || 18}" customWidth="1"/>`).join("");
  const sheetData = allRows.map((values, rowIndex) => {
    const r = rowIndex + 1;
    const cells = values.map((value, colIndex) => xlsxCell(value, colIndex + 1, r, rowIndex === 0)).join("");
    return `<row r="${r}" spans="1:${headers.length}">${cells}</row>`;
  }).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <dimension ref="A1:${lastCol}${lastRow}"/>
 <sheetViews>
  <sheetView workbookViewId="0">
   <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
  </sheetView>
 </sheetViews>
 <cols>${cols}</cols>
 <sheetData>${sheetData}</sheetData>
 <autoFilter ref="A1:${lastCol}${lastRow}"/>
</worksheet>`;
}

function xlsxCell(value, col, row, isHeader) {
  const ref = `${colName(col)}${row}`;
  if (isHeader) {
    return `<c r="${ref}" t="inlineStr" s="1"><is><t>${xmlEsc(value)}</t></is></c>`;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<c r="${ref}" s="2"><v>${value}</v></c>`;
  }
  const text = value == null ? "" : String(value);
  return `<c r="${ref}" t="inlineStr" s="2"><is><t>${xmlEsc(text)}</t></is></c>`;
}

function colName(index) {
  let name = "";
  while (index > 0) {
    const rem = (index - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    index = Math.floor((index - 1) / 26);
  }
  return name;
}

function contentTypesXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
 <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
 <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
 <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
 <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`;
}

function packageRelsXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
 <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>`;
}

function workbookXml(sheetName) {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets>
  <sheet name="${xmlEsc(sheetName).slice(0, 31)}" sheetId="1" r:id="rId1"/>
 </sheets>
</workbook>`;
}

function workbookRelsXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`;
}

function stylesXml() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <fonts count="2">
  <font><sz val="11"/><color theme="1"/><name val="Calibri"/></font>
  <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
 </fonts>
 <fills count="3">
  <fill><patternFill patternType="none"/></fill>
  <fill><patternFill patternType="gray125"/></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FF0B63F6"/><bgColor indexed="64"/></patternFill></fill>
 </fills>
 <borders count="2">
  <border><left/><right/><top/><bottom/><diagonal/></border>
  <border><left style="thin"><color rgb="FFD9E2EC"/></left><right style="thin"><color rgb="FFD9E2EC"/></right><top style="thin"><color rgb="FFD9E2EC"/></top><bottom style="thin"><color rgb="FFD9E2EC"/></bottom><diagonal/></border>
 </borders>
 <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
 <cellXfs count="3">
  <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
  <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment vertical="center"/></xf>
  <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"><alignment vertical="top" wrapText="1"/></xf>
 </cellXfs>
 <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;
}

function appPropsXml(sheetName) {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
 <Application>Veille fermetures agences bancaires</Application>
 <TitlesOfParts><vt:vector size="1" baseType="lpstr"><vt:lpstr>${xmlEsc(sheetName)}</vt:lpstr></vt:vector></TitlesOfParts>
</Properties>`;
}

function corePropsXml() {
  const now = new Date().toISOString();
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <dc:title>Fermetures agences bancaires</dc:title>
 <dc:creator>Veille presse</dc:creator>
 <cp:lastModifiedBy>Veille presse</cp:lastModifiedBy>
 <dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created>
 <dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified>
</cp:coreProperties>`;
}

function zipFiles(files, mimeType) {
  const encoder = new TextEncoder();
  const entries = Object.entries(files).map(([name, content]) => ({
    name,
    nameBytes: encoder.encode(name),
    data: encoder.encode(content),
  }));
  let offset = 0;
  const localParts = [];
  const centralParts = [];
  for (const entry of entries) {
    const crc = crc32(entry.data);
    entry.offset = offset;
    const local = concatBytes(
      u32(0x04034b50), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
      u32(crc), u32(entry.data.length), u32(entry.data.length),
      u16(entry.nameBytes.length), u16(0), entry.nameBytes, entry.data
    );
    localParts.push(local);
    offset += local.length;
    centralParts.push(concatBytes(
      u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(0), u16(0), u16(0),
      u32(crc), u32(entry.data.length), u32(entry.data.length),
      u16(entry.nameBytes.length), u16(0), u16(0), u16(0), u16(0), u32(0),
      u32(entry.offset), entry.nameBytes
    ));
  }
  const central = concatBytes(...centralParts);
  const end = concatBytes(
    u32(0x06054b50), u16(0), u16(0), u16(entries.length), u16(entries.length),
    u32(central.length), u32(offset), u16(0)
  );
  return new Blob([concatBytes(...localParts, central, end)], { type: mimeType });
}

function u16(value) {
  const out = new Uint8Array(2);
  out[0] = value & 0xff;
  out[1] = (value >>> 8) & 0xff;
  return out;
}

function u32(value) {
  const out = new Uint8Array(4);
  out[0] = value & 0xff;
  out[1] = (value >>> 8) & 0xff;
  out[2] = (value >>> 16) & 0xff;
  out[3] = (value >>> 24) & 0xff;
  return out;
}

function concatBytes(...parts) {
  const size = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function crc32(bytes) {
  if (!crc32.table) {
    crc32.table = Array.from({ length: 256 }, (_, n) => {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      return c >>> 0;
    });
  }
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc = crc32.table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function xmlEsc(value) {
  return String(value).replace(/[<>&'"]/g, (ch) => (
    { "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[ch]
  ));
}

function periodWindow() {
  const mode = val("f-period");
  const dates = DONNEES.closures.map(dateValue).filter(Boolean).sort((a, b) => a - b);
  const max = selectedMonth ? endOfMonth(selectedMonth).getTime() : (dates[dates.length - 1] || Date.now());
  if (mode === "selected" && selectedMonth) {
    return { start: startOfMonth(selectedMonth).getTime(), end: max };
  }
  if (mode === "selected") {
    const key = monthKey(max);
    return { start: startOfMonth(key).getTime(), end: endOfMonth(key).getTime() };
  }
  if (mode === "6m" || mode === "12m") {
    const end = new Date(max);
    const start = new Date(end);
    start.setMonth(start.getMonth() - (mode === "6m" ? 5 : 11), 1);
    start.setHours(0, 0, 0, 0);
    return { start: start.getTime(), end: endOfMonth(monthKey(end)).getTime() };
  }
  return { start: Number.NEGATIVE_INFINITY, end: Number.POSITIVE_INFINITY };
}

function dateInWindow(c, window) {
  const t = dateValue(c);
  if (!t) return true;
  return t >= window.start && t <= window.end;
}

function periodLabel() {
  const mode = val("f-period");
  const win = periodWindow();
  if (mode === "selected" && selectedMonth) return monthLabel(selectedMonth);
  if (mode === "selected") return monthLabel(monthKey(win.end));
  if (!Number.isFinite(win.start) && !Number.isFinite(win.end)) {
    const dated = DONNEES.closures.filter(dateValue);
    return dated.length ? `${formatDate(firstDate(dated))} – ${formatDate(lastDate(dated))}` : "toutes les dates";
  }
  const start = Number.isFinite(win.start) ? formatDate(win.start) : "début";
  const end = Number.isFinite(win.end) ? formatDate(win.end) : "fin";
  return `${start} – ${end}`;
}

function selectTimelineMonth(key) {
  selectedMonth = key;
  document.getElementById("f-period").value = "selected";
  rafraichir();
}

function resetPeriod() {
  selectedMonth = "";
  document.getElementById("f-period").value = "all";
  rafraichir();
}

function toggleTimelinePlay() {
  const months = monthBuckets(filtrer(false)).map((m) => m.key);
  if (!months.length) return;
  if (playTimer) {
    window.clearInterval(playTimer);
    playTimer = null;
    renderAll();
    return;
  }
  let index = Math.max(0, months.indexOf(selectedMonth));
  playTimer = window.setInterval(() => {
    selectedMonth = months[index % months.length];
    document.getElementById("f-period").value = "selected";
    rafraichir();
    index += 1;
  }, 900);
  renderAll();
}

function popupHtml(p) {
  let sources = [];
  try { sources = JSON.parse(p.sources || "[]"); } catch (e) { sources = []; }
  const src = sources
    .filter((s) => s.url && !s.url.startsWith("acpr://"))
    .slice(0, 3)
    .map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.source || "source")}</a>`)
    .join(" · ");
  return `<strong>${esc(p.banque)}</strong><br>${esc(p.commune)} ${p.departement ? `(${esc(p.departement)})` : ""}<br>
    ${esc(p.type)} · ${esc(p.statut)} · fiabilité ${esc(p.fiabilite)}/5<br>
    <em>${esc(p.citation || "")}</em><br>${src}<br>
    <button type="button" class="popup-action" onclick="openAgencySheet('${esc(p.id)}')">Ouvrir la fiche complète</button>`;
}

function fitToFiltered() {
  if (!map || !map.loaded()) return;
  const pts = filtrer().filter((c) => c.lat != null && c.lon != null);
  if (!pts.length) return;
  const bounds = pts.reduce((b, c) => b.extend([c.lon, c.lat]), new maplibregl.LngLatBounds([pts[0].lon, pts[0].lat], [pts[0].lon, pts[0].lat]));
  map.fitBounds(bounds, { padding: 90, maxZoom: currentView === "departments" ? 9 : 6.2, duration: 450 });
}

function depNom(code) {
  return (DONNEES.departements[code] && DONNEES.departements[code].nom) || code || "";
}

function topDepartments(items) {
  return Object.entries(groupCount(items.filter((c) => c.departement), (c) => c.departement)).sort((a, b) => b[1] - a[1]);
}

function groupCount(items, keyFn) {
  return items.reduce((acc, item) => {
    const key = keyFn(item);
    if (key) acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

function eventClass(c) {
  if (c.type === "fusion") return "purple";
  if (c.statut === "projet") return "orange";
  if (c.statut === "rumeur") return "blue";
  return "red";
}

function metric(label, value, color) {
  return `<div class="metric"><i class="dot ${color}"></i><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
}

function table(headers, rows) {
  return `<table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}">Aucune donnée</td></tr>`}</tbody></table>`;
}

function emptyState(text) {
  return `<p class="empty">${esc(text)}</p>`;
}

function vigilanceCard(v) {
  return `<article class="result-card">
    <div class="card-head"><span class="event-dot blue"></span><strong>${esc(v.banque || "Banque non isolée")}</strong></div>
    <p>${esc(v.titre || v.extrait || "")}</p>
    <div class="meta">${esc(v.source || "")} · score ${esc(v.score || "?")}/5</div>
    ${v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">Ouvrir ↗</a>` : ""}
  </article>`;
}

function parseDate(value) {
  if (typeof value === "number") return value;
  const t = Date.parse(value || "");
  return Number.isNaN(t) ? 0 : t;
}

function dateValue(c) {
  return parseDate(c.date_fermeture || c.date_annonce || c.created_at);
}

function formatDate(value) {
  const t = parseDate(value);
  if (!t) return "Date non précisée";
  return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" }).format(new Date(t));
}

function firstDate(items) {
  const sorted = items.filter(dateValue).sort((a, b) => dateValue(a) - dateValue(b));
  return sorted[0] ? sorted[0].date_fermeture || sorted[0].date_annonce || sorted[0].created_at : "";
}

function lastDate(items) {
  const sorted = items.filter(dateValue).sort((a, b) => dateValue(a) - dateValue(b));
  const item = sorted[sorted.length - 1];
  return item ? item.date_fermeture || item.date_annonce || item.created_at : "";
}

function monthBuckets(items) {
  const buckets = {};
  items.forEach((c) => {
    const t = dateValue(c);
    if (!t) return;
    const d = new Date(t);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    buckets[key] = (buckets[key] || 0) + 1;
  });
  return Object.entries(buckets).sort(([a], [b]) => a.localeCompare(b)).map(([key, count]) => {
    const [year, month] = key.split("-");
    const d = new Date(Number(year), Number(month) - 1, 1);
    return { key, label: new Intl.DateTimeFormat("fr-FR", { month: "short", year: "numeric" }).format(d), count };
  });
}

function monthKey(date) {
  const d = date instanceof Date ? date : new Date(date);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(key) {
  const [year, month] = key.split("-");
  const d = new Date(Number(year), Number(month) - 1, 1);
  return new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" }).format(d);
}

function startOfMonth(key) {
  const [year, month] = key.split("-");
  return new Date(Number(year), Number(month) - 1, 1, 0, 0, 0, 0);
}

function endOfMonth(key) {
  const [year, month] = key.split("-");
  return new Date(Number(year), Number(month), 0, 23, 59, 59, 999);
}

function isoMonthsAgo(months) {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10);
}

function sum(values) {
  return values.reduce((acc, value) => acc + value, 0);
}

window.focusClosure = focusClosure;
window.focusClosureOnly = focusClosureOnly;
window.openAgencySheet = openAgencySheet;
window.selectDepartment = selectDepartment;
window.selectRegion = selectRegion;
window.selectTimelineMonth = selectTimelineMonth;
window.resetPeriod = resetPeriod;
window.toggleTimelinePlay = toggleTimelinePlay;
window.telechargerExcel = telechargerExcel;

init();
