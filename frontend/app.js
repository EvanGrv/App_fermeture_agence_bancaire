// frontend/app.js
const STYLE = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

let DONNEES = { closures: [], departements: {} };
let DEPTS = null;
let map;

async function init() {
  map = new maplibregl.Map({
    container: "map",
    style: STYLE,
    center: [2.5, 46.6],
    zoom: 5,
  });
  map.addControl(new maplibregl.NavigationControl(), "top-right");

  const [d1, d2] = await Promise.all([
    fetch("../data/export/data.json").then((r) => r.json()),
    fetch("../data/export/departements.geojson").then((r) => r.json()),
  ]);
  DONNEES = d1;
  DEPTS = d2;
  renderPlans();

  map.on("load", () => {
    map.addSource("departements", { type: "geojson", data: deptsAvecCompte(filtrer()) });
    map.addLayer({
      id: "dep-fill", type: "fill", source: "departements",
      paint: {
        "fill-color": [
          "interpolate", ["linear"], ["get", "count"],
          0, "#f2f0f7", 1, "#cbc9e2", 3, "#9e9ac8", 6, "#756bb1", 12, "#54278f",
        ],
        "fill-opacity": 0.55,
      },
    });
    map.addLayer({
      id: "dep-line", type: "line", source: "departements",
      paint: { "line-color": "#777", "line-width": 0.4 },
    });
    map.addSource("closures", { type: "geojson", data: pointsClosures(filtrer()) });
    map.addLayer({
      id: "points", type: "circle", source: "closures",
      paint: {
        "circle-radius": 6,
        "circle-color": ["match", ["get", "type"], "fermeture", "#d6336c", "fusion", "#1c7ed6", "#888"],
        "circle-stroke-width": 1, "circle-stroke-color": "#fff",
      },
    });
    map.on("click", "points", (e) => {
      new maplibregl.Popup()
        .setLngLat(e.lngLat)
        .setHTML(popupHtml(e.features[0].properties))
        .addTo(map);
    });
    map.on("mouseenter", "points", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "points", () => { map.getCanvas().style.cursor = ""; });

    remplirSelecteurs();
    ["f-banque", "f-type", "f-statut", "f-fiab", "f-dep"].forEach((id) =>
      document.getElementById(id).addEventListener("change", rafraichir)
    );
    rafraichir();
  });
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function val(id) { return document.getElementById(id).value; }

function filtrer() {
  const banque = val("f-banque"), type = val("f-type"), statut = val("f-statut"), dep = val("f-dep");
  const fiab = parseInt(val("f-fiab"), 10);
  return DONNEES.closures.filter((c) =>
    (!banque || c.banque === banque) &&
    (!type || c.type === type) &&
    (!statut || c.statut === statut) &&
    (!dep || c.departement === dep) &&
    (c.fiabilite || 0) >= fiab
  );
}

function deptsAvecCompte(items) {
  const compte = {};
  items.forEach((c) => { if (c.departement) compte[c.departement] = (compte[c.departement] || 0) + 1; });
  const fc = JSON.parse(JSON.stringify(DEPTS));
  fc.features.forEach((f) => { f.properties.count = compte[f.properties.code] || 0; });
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
          banque: c.banque, commune: c.commune, departement: c.departement || "",
          type: c.type, statut: c.statut, fiabilite: c.fiabilite,
          citation: c.citation || "", sources: JSON.stringify(c.sources || []),
        },
      })),
  };
}

function rafraichir() {
  const items = filtrer();
  if (map.getSource("departements")) map.getSource("departements").setData(deptsAvecCompte(items));
  if (map.getSource("closures")) map.getSource("closures").setData(pointsClosures(items));
  const liste = document.getElementById("liste");
  liste.innerHTML = `<p>${items.length} résultat(s)</p>`;
  items.forEach((c) => {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `<h3>${esc(c.banque)} — ${esc(c.commune)}</h3>
      <span class="badge ${esc(c.type)}">${esc(c.type)}</span>
      <div class="meta">${esc(c.departement || "?")} · ${esc(c.statut)} · fiab ${esc(c.fiabilite)}</div>`;
    div.addEventListener("click", () => {
      if (c.lon != null && c.lat != null) map.flyTo({ center: [c.lon, c.lat], zoom: 11 });
    });
    liste.appendChild(div);
  });
}

function renderPlans() {
  const el = document.getElementById("plans");
  if (!el) return;
  const plans = DONNEES.plans || [];
  if (!plans.length) { el.innerHTML = ""; return; }
  const items = plans
    .map((p) => `<strong>${esc(p.banque)}</strong> ~${esc(p.volume)} (${esc(p.echeance)})`)
    .join(" · ");
  el.innerHTML = `<span class="plans-label">Plans nationaux annoncés (non nominatifs, hors carte) :</span> ${items}`;
}

function remplirSelecteurs() {
  const banques = [...new Set(DONNEES.closures.map((c) => c.banque))].sort();
  const selB = document.getElementById("f-banque");
  banques.forEach((b) => {
    const o = document.createElement("option");
    o.value = b; o.textContent = b; selB.appendChild(o);
  });
  const deps = [...new Set(DONNEES.closures.map((c) => c.departement).filter(Boolean))].sort();
  const selD = document.getElementById("f-dep");
  deps.forEach((d) => {
    const nom = (DONNEES.departements[d] && DONNEES.departements[d].nom) || d;
    const o = document.createElement("option");
    o.value = d; o.textContent = `${d} — ${nom}`; selD.appendChild(o);
  });
}

function popupHtml(p) {
  let sources = [];
  try { sources = JSON.parse(p.sources || "[]"); } catch (e) { sources = []; }
  const src = sources
    .filter((s) => s.url && !s.url.startsWith("acpr://"))
    .map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.source || "source")}</a>`)
    .join(" · ");
  return `<strong>${esc(p.banque)}</strong><br>${esc(p.commune)} (${esc(p.departement || "?")})<br>
    ${esc(p.type)} · ${esc(p.statut)} · fiabilité ${esc(p.fiabilite)}<br>
    <em>${esc(p.citation || "")}</em><br>${src}`;
}

init();
