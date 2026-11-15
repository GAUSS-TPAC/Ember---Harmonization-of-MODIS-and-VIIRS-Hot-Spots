/* Ember frontend: no build step, talks to the FastAPI backend on the same origin. */
(function () {
  "use strict";
  const API = "";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const VIRIDIS = ["#440154", "#482475", "#414487", "#355f8d", "#2a788e", "#21918c", "#22a884", "#44bf70", "#7ad151", "#bddf26", "#fde725"];
  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- state
  let geometry = null;          // GeoJSON polygon drawn or built from the bbox
  let lastRequest = null;
  let lastResult = null;
  let seriesChart = null, climChart = null;
  let cellLayer = null;

  // ---------------------------------------------------------------- map
  const map = L.map("map", { zoomControl: true }).setView([5.0, 11.5], 6);
  const dark = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Tiles &copy; Esri, HERE, Garmin, OpenStreetMap contributors", maxZoom: 16,
  }).addTo(map);
  const streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors", maxZoom: 19,
  });
  L.control.layers({ "Dark (Esri)": dark, "Streets (OSM)": streets }, null, { position: "topright", collapsed: true }).addTo(map);
  const drawn = new L.FeatureGroup().addTo(map);
  map.addControl(new L.Control.Draw({
    draw: { polyline: false, circle: false, circlemarker: false, marker: false,
      rectangle: { shapeOptions: { color: "#ff7a1a", weight: 2 } },
      polygon: { shapeOptions: { color: "#ff7a1a", weight: 2 }, allowIntersection: false } },
    edit: { featureGroup: drawn, remove: true },
  }));
  map.on(L.Draw.Event.CREATED, (e) => { drawn.clearLayers(); drawn.addLayer(e.layer); setGeometryFromLayer(e.layer); });
  map.on(L.Draw.Event.EDITED, (e) => e.layers.eachLayer(setGeometryFromLayer));
  map.on(L.Draw.Event.DELETED, () => { geometry = null; });

  function setGeometryFromLayer(layer) {
    geometry = layer.toGeoJSON().geometry;
    const b = layer.getBounds();
    $("south").value = b.getSouth().toFixed(3); $("west").value = b.getWest().toFixed(3);
    $("north").value = b.getNorth().toFixed(3); $("east").value = b.getEast().toFixed(3);
    setStatus("Area set from the map. Click “Analyze fire history”.");
  }

  function applyBbox() {
    const s = +$("south").value, w = +$("west").value, n = +$("north").value, e = +$("east").value;
    if (!(s < n && w < e)) return setStatus("South must be below North and West below East.", true);
    drawn.clearLayers();
    const rect = L.rectangle([[s, w], [n, e]], { color: "#ff7a1a", weight: 2 });
    drawn.addLayer(rect);
    geometry = rect.toGeoJSON().geometry;
    map.fitBounds(rect.getBounds(), { padding: [20, 20] });
    setStatus("Bounding box applied.");
  }

  // ---------------------------------------------------------------- helpers
  function setStatus(msg, isError) { const el = $("status"); el.textContent = msg; el.classList.toggle("error", !!isError); }
  function ramp(t) {
    const x = Math.max(0, Math.min(1, t)) * (VIRIDIS.length - 1);
    const i = Math.floor(x), f = x - i;
    if (i >= VIRIDIS.length - 1) return VIRIDIS[VIRIDIS.length - 1];
    const a = hex(VIRIDIS[i]), b = hex(VIRIDIS[i + 1]);
    return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(",")})`;
  }
  function hex(h) { return [1, 3, 5].map((p) => parseInt(h.slice(p, p + 2), 16)); }
  function fmt(n) { return n == null ? "–" : Math.round(n).toLocaleString("en-US"); }
  function ym(s) { const [y, m] = s.split("-").map(Number); return { y, m }; }
  function parseBaseline(text) {
    const m = text.trim().match(/^(\d{4})\s*[-–to ]+\s*(\d{4})$/);
    return m ? [Number(m[1]), Number(m[2])] : null;
  }
  function quantile(arr, q) { const s = arr.filter((v) => v != null).sort((a, b) => a - b); if (!s.length) return 0; return s[Math.min(s.length - 1, Math.floor(q * s.length))]; }

  // ---------------------------------------------------------------- API
  async function analyze() {
    if (!geometry) applyBbox();
    if (!geometry) return;
    const body = { geometry, start: $("start").value, end: $("end").value };
    if ($("target").value) body.target = $("target").value;
    const baseline = parseBaseline($("baseline").value);
    if (baseline) body.baseline = baseline;
    setStatus("Computing…"); $("analyze").disabled = true;
    try {
      const res = await fetch(`${API}/api/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      lastRequest = body; lastResult = await res.json();
      render(lastResult);
      $("download").disabled = false;
      const live = lastResult.live || {};
      const liveMsg = live.status === "ok" ? ` Live FIRMS data merged from ${live.first_month} (${live.hotspot_rows} cell-months).`
        : live.status === "unavailable" ? ` Live FIRMS data unavailable: ${live.reason}.` : "";
      setStatus(`Done: ${lastResult.area.cells.toLocaleString()} grid cells, ${lastResult.series.length} months.${liveMsg}`);
    } catch (err) {
      setStatus(`Error: ${err.message}`, true);
    } finally { $("analyze").disabled = false; }
  }

  async function download() {
    if (!lastRequest) return;
    const res = await fetch(`${API}/api/export.csv`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lastRequest) });
    const blob = await res.blob();
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ember_series.csv"; a.click();
  }

  // ---------------------------------------------------------------- rendering
  function render(r) {
    $("results").hidden = false;
    renderKpis(r); renderCalendar(r); renderSeries(r); renderClimatology(r); renderCells(r);
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderKpis(r) {
    const a = r.anomaly, k = $("kpiAnomaly");
    k.className = "kpi " + (a.percentile == null ? "" : a.percentile >= 75 ? "high" : a.percentile <= 25 ? "low" : "normal");
    k.querySelector(".kpi-value").textContent = `${MONTHS[a.month - 1]} ${a.year}: ${fmt(a.value)}`;
    k.querySelector(".kpi-sub").textContent = a.median == null ? "no baseline years" :
      `${a.label} · ${a.ratio != null ? a.ratio + "× the median (" + fmt(a.median) + ")" : "median is 0"} · percentile ${a.percentile} over ${a.n_years} years`;

    const s = r.season, ks = $("kpiSeason");
    ks.querySelector(".kpi-value").textContent = s.peak ? `${MONTHS[s.onset - 1]} → ${MONTHS[s.end - 1]}` : "–";
    ks.querySelector(".kpi-sub").textContent = s.peak ? `peak in ${MONTHS[s.peak - 1]} (${Math.round(s.peak_share * 100)}% of the year), ${s.length_months} months` : "no activity";

    const kt = $("kpiTop");
    kt.querySelector(".kpi-value").textContent = r.top_years.slice(0, 3).map((t) => t.year).join(" · ") || "–";
    kt.querySelector(".kpi-sub").textContent = r.top_years.slice(0, 3).map((t) => fmt(t.n_harm)).join(" · ") + " hotspots";

    const ka = $("kpiArea"), b = r.area.bbox;
    ka.querySelector(".kpi-value").textContent = `${r.area.cells.toLocaleString()} cells`;
    ka.querySelector(".kpi-sub").textContent = `0.1° grid · ${b[0].toFixed(2)}–${b[2].toFixed(2)}N, ${b[1].toFixed(2)}–${b[3].toFixed(2)}E · ${r.period.start} → ${r.period.end}`;
  }

  function renderCalendar(r) {
    const cal = r.calendar, table = $("calendar");
    const flat = cal.values.flat().filter((v) => v != null && v > 0);
    const vmax = quantile(flat, 0.98) || 1;
    const bySource = {}, byProv = {};
    r.series.forEach((s) => { bySource[`${s.year}-${s.month}`] = s.source; byProv[`${s.year}-${s.month}`] = s.provisional; });
    const target = $("target").value ? ym($("target").value) : null;
    let html = "<thead><tr><th></th>" + MONTHS.map((m) => `<th>${m}</th>`).join("") + "<th>Year</th></tr></thead><tbody>";
    cal.years.forEach((year, i) => {
      let total = 0;
      html += `<tr><th class="year">${year}</th>`;
      cal.months.forEach((month, j) => {
        const v = cal.values[i][j];
        if (v == null) { html += `<td class="empty"></td>`; return; }
        total += v;
        const src = bySource[`${year}-${month}`] || "";
        const prov = !!byProv[`${year}-${month}`];
        const cls = [src.startsWith("MODIS") ? "recon" : "", prov ? "prov" : "", target && target.y === year && target.m === month ? "selected" : ""].join(" ");
        const bg = v > 0 ? ramp(Math.sqrt(v / vmax)) : "#1a1e27";
        const note = prov ? ", provisional near-real-time" : "";
        html += `<td class="${cls}" style="background:${bg}" data-y="${year}" data-m="${month}" title="${MONTHS[month - 1]} ${year}: ${fmt(v)} hotspots (${src.replace("_", " ")}${note})">${v >= 1 ? fmt(v) : ""}</td>`;
      });
      html += `<th class="year">${fmt(total)}</th></tr>`;
    });
    table.innerHTML = html + "</tbody>";
    table.querySelectorAll("td[data-y]").forEach((td) => td.addEventListener("click", () => {
      $("target").value = `${td.dataset.y}-${String(td.dataset.m).padStart(2, "0")}`;
      analyze();
    }));
  }

  function renderSeries(r) {
    const labels = r.series.map((s) => `${s.year}-${String(s.month).padStart(2, "0")}`);
    const data = {
      labels,
      datasets: [
        { label: "upper band", data: r.series.map((s) => s.n_high), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: "rgba(249,199,79,.25)" },
        { label: "lower band", data: r.series.map((s) => s.n_low), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "harmonized hotspots", data: r.series.map((s) => s.n_harm), borderColor: "#ff7a1a", borderWidth: 1.5, pointRadius: 0, tension: 0.2 },
        { label: "raw MODIS", data: r.series.map((s) => s.n_modis || null), borderColor: "rgba(154,163,178,.7)", borderDash: [4, 3], borderWidth: 1, pointRadius: 0 },
      ],
    };
    const opts = { responsive: true, animation: false, interaction: { mode: "index", intersect: false },
      scales: { x: { ticks: { color: "#9aa3b2", maxTicksLimit: 14 }, grid: { color: "#262b36" } }, y: { ticks: { color: "#9aa3b2" }, grid: { color: "#262b36" }, beginAtZero: true } },
      plugins: { legend: { labels: { color: "#9aa3b2", filter: (i) => !i.text.includes("band") } } } };
    if (seriesChart) seriesChart.destroy();
    seriesChart = new Chart($("seriesChart"), { type: "line", data, options: opts });
  }

  function renderClimatology(r) {
    const c = r.climatology, year = r.anomaly.year;
    const thisYear = MONTHS.map((_, i) => { const s = r.series.find((x) => x.year === year && x.month === i + 1); return s ? s.n_harm : null; });
    const data = { labels: MONTHS, datasets: [
      { type: "bar", label: "median (baseline)", data: c.median, backgroundColor: "rgba(76,201,240,.45)" },
      { type: "line", label: "25th–75th percentile", data: c.p75, borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: "rgba(76,201,240,.18)" },
      { type: "line", label: "p25", data: c.p25, borderWidth: 0, pointRadius: 0, fill: false },
      { type: "line", label: `${year}`, data: thisYear, borderColor: "#ff7a1a", backgroundColor: "#ff7a1a", borderWidth: 2, pointRadius: 3, tension: 0.2 },
    ] };
    const opts = { responsive: true, animation: false,
      scales: { x: { ticks: { color: "#9aa3b2" }, grid: { display: false } }, y: { ticks: { color: "#9aa3b2" }, grid: { color: "#262b36" }, beginAtZero: true } },
      plugins: { legend: { labels: { color: "#9aa3b2", filter: (i) => i.text !== "p25" } } } };
    if (climChart) climChart.destroy();
    climChart = new Chart($("climChart"), { data, options: opts });
  }

  function renderCells(r) {
    if (cellLayer) map.removeLayer(cellLayer);
    cellLayer = L.layerGroup();
    const vals = r.cells.map((c) => c.n_per_year);
    const vmax = quantile(vals, 0.98) || 1;
    const res = 0.1;
    r.cells.forEach((c) => {
      L.rectangle([[c.lat, c.lon], [c.lat + res, c.lon + res]], {
        stroke: false, fillColor: ramp(Math.sqrt(c.n_per_year / vmax)), fillOpacity: 0.65, interactive: false,
      }).addTo(cellLayer);
    });
    cellLayer.addTo(map);
    $("mapLegend").hidden = r.cells.length === 0;
  }

  // ---------------------------------------------------------------- wiring
  $("applyBbox").addEventListener("click", applyBbox);
  $("analyze").addEventListener("click", analyze);
  $("download").addEventListener("click", download);
  fetch(`${API}/api/coverage`).then((r) => r.json()).then((c) => {
    $("start").min = c.first; $("end").max = c.last;
    if (c.bounds) {
      const b = c.bounds;
      $("south").value = b.south.toFixed(2); $("west").value = b.west.toFixed(2);
      $("north").value = b.north.toFixed(2); $("east").value = b.east.toFixed(2);
      map.fitBounds([[b.south, b.west], [b.north, b.east]]);
    }
    setStatus(`Data available ${c.first} → ${c.last} over ${c.cells.toLocaleString()} cells.`);
  }).catch(() => setStatus("Backend unreachable: start the API (see README).", true));
})();
