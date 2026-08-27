const state = {
  summary: null,
  tracks: null,
  view: "tracks",
  split: 50,
  maps: {},
  basemaps: {},
  trackLayers: {left: null, right: null},
  pointLayers: {left: null, right: null},
  rasterLayers: {left: null, right: null},
  rasters: {},
  trackOpacity: 0.70,
  densityOpacity: 0.88,
  showPoints: false,
};

const REGIONS = {
  "Global":[[-58,-180],[84,180]],
  "North America":[[5,-170],[82,-50]],
  "South America":[[-58,-92],[15,-30]],
  "Europe":[[34,-25],[72,45]],
  "Africa":[[-38,-20],[38,55]],
  "Asia":[[-10,25],[82,180]],
  "Oceania":[[-50,105],[5,180]],
};

const YEAR_BOUNDS = [1980,1985,1990,1995,2000,2005,2010,2015,2020];
const YEAR_LABELS = [
  "1980–1985","1985–1990","1990–1995","1995–2000",
  "2000–2005","2005–2010","2010–2015","2015–2020"
];
const YEAR_COLORS = [
  "#efe7d8","#d9c39e","#a99273","#e5d476",
  "#a9e66e","#29c86f","#11a5e8","#313695"
];

const DENSITY_COLORS = [
  "#fffdf0","#fff0b2","#fed976","#feb24c",
  "#fd8d3c","#e6550d","#a63603","#6b2500"
];

const CHANGE_NEG = ["#f2edf7","#dadaeb","#bcbddc","#9e9ac8","#756bb1","#54278f"];
const CHANGE_POS = ["#fff7ec","#fee8c8","#fdbb84","#fc8d59","#e34a33","#b30000"];

document.addEventListener("DOMContentLoaded", init);

async function init() {
  setupMaps();
  bindControls();
  setupDivider();
  buildYearLegend();

  try {
    setStatus("Loading…");
    state.summary = await fetchJSON("data/summary.json");
    state.tracks = await fetchJSON("data/tracks.geojson");
    await loadRasters();
    updateSummary();
    drawCharts();
    renderView();
    setStatus("Ready");
  } catch (err) {
    console.error(err);
    setStatus("Data missing", true);
    document.getElementById("mapSubtitle").textContent =
      "Processed dashboard data are missing. Check the GitHub Actions build.";
  }
}

function setupMaps() {
  const opts = {
    center:[22,0],
    zoom:2,
    minZoom:1,
    maxZoom:8,
    maxBounds:[[-85,-180],[85,180]],
    maxBoundsViscosity:1.0,
    worldCopyJump:false,
    preferCanvas:true,
  };

  state.maps.left = L.map("mapLeft", opts);
  state.maps.right = L.map("mapRight", {
    ...opts,
    zoomControl:false,
    attributionControl:false,
    dragging:false,
    scrollWheelZoom:false,
    doubleClickZoom:false,
    boxZoom:false,
    keyboard:false,
    touchZoom:false,
  });

  const tileUrl = "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png";
  const tileOpts = {
    subdomains:"abcd",
    maxZoom:20,
    noWrap:true,
    attribution:"&copy; OpenStreetMap contributors &copy; CARTO"
  };

  state.basemaps.left = L.tileLayer(tileUrl,tileOpts).addTo(state.maps.left);
  state.basemaps.right = L.tileLayer(tileUrl,tileOpts).addTo(state.maps.right);

  state.maps.left.fitBounds(REGIONS.Global,{padding:[6,6]});
  syncRight();

  state.maps.left.on("move zoom", syncRight);
  state.maps.left.on("mousemove", e => {
    document.getElementById("readout").textContent =
      `${e.latlng.lat.toFixed(2)}°, ${e.latlng.lng.toFixed(2)}°`;
  });
}

function syncRight() {
  state.maps.right.setView(
    state.maps.left.getCenter(),
    state.maps.left.getZoom(),
    {animate:false, reset:true}
  );
}

function bindControls() {
  document.getElementById("regionSelect").addEventListener("change", e => {
    state.maps.left.fitBounds(REGIONS[e.target.value] || REGIONS.Global,{padding:[8,8]});
  });

  document.getElementById("resetView").addEventListener("click", () => {
    document.getElementById("regionSelect").value = "Global";
    state.maps.left.fitBounds(REGIONS.Global,{padding:[8,8]});
    setSplit(50);
  });

  document.querySelectorAll(".view-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.view = btn.dataset.view;
      renderView();
    });
  });

  document.getElementById("trackOpacity").addEventListener("input", e => {
    state.trackOpacity = Number(e.target.value) / 100;
    document.getElementById("trackOpacityValue").textContent = `${e.target.value}%`;
    refreshTrackStyles();
  });

  document.getElementById("densityOpacity").addEventListener("input", e => {
    state.densityOpacity = Number(e.target.value) / 100;
    document.getElementById("densityOpacityValue").textContent = `${e.target.value}%`;
    ["left","right"].forEach(side => {
      const layer = state.rasterLayers[side];
      if (layer && layer.setOpacity) layer.setOpacity(state.densityOpacity);
    });
  });

  document.getElementById("showTrackPoints").addEventListener("change", e => {
    state.showPoints = e.target.checked;
    if (state.view === "tracks") renderTracks();
  });
}

function setupDivider() {
  const shell = document.getElementById("mapShell");
  const divider = document.getElementById("divider");
  let dragging = false;

  divider.addEventListener("pointerdown", e => {
    dragging = true;
    divider.setPointerCapture(e.pointerId);
  });

  divider.addEventListener("pointermove", e => {
    if (!dragging || state.view === "change") return;
    const r = shell.getBoundingClientRect();
    const pct = (e.clientX - r.left) / r.width * 100;
    setSplit(Math.max(5, Math.min(95, pct)));
  });

  divider.addEventListener("pointerup", e => {
    dragging = false;
    try { divider.releasePointerCapture(e.pointerId); } catch (_) {}
  });

  window.addEventListener("resize", () => {
    state.maps.left.invalidateSize();
    state.maps.right.invalidateSize();
    setSplit(state.split);
  });
}

function setSplit(pct) {
  state.split = pct;
  document.getElementById("mapRight").style.clipPath = `inset(0 0 0 ${pct}%)`;
  document.getElementById("divider").style.left = `${pct}%`;
}

function buildYearLegend() {
  const box = document.getElementById("yearLegendItems");
  box.innerHTML = "";

  YEAR_LABELS.forEach((label, i) => {
    const div = document.createElement("div");
    div.className = "year-item";
    div.innerHTML = `
      <span class="year-swatch" style="background:${YEAR_COLORS[i]}"></span>
      <span>${label}</span>
    `;
    box.appendChild(div);
  });
}

async function loadRasters() {
  const f = state.summary.files;
  const [early,recent,change] = await Promise.all([
    loadGeoRaster(f.early_density),
    loadGeoRaster(f.recent_density),
    loadGeoRaster(f.change_density)
  ]);

  state.rasters.early = early;
  state.rasters.recent = recent;
  state.rasters.change = change;
}

async function loadGeoRaster(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Cannot load ${url}`);
  return parseGeoraster(await res.arrayBuffer());
}

function clearLayers() {
  ["left","right"].forEach(side => {
    for (const group of ["trackLayers","pointLayers","rasterLayers"]) {
      const layer = state[group][side];
      if (layer && state.maps[side].hasLayer(layer)) {
        state.maps[side].removeLayer(layer);
      }
      state[group][side] = null;
    }
  });
}

function renderView() {
  clearLayers();

  const right = document.getElementById("mapRight");
  const divider = document.getElementById("divider");
  const labelRight = document.getElementById("labelRight");
  const labelLeft = document.getElementById("labelLeft");
  const yearLegend = document.getElementById("yearLegend");
  const densityLegend = document.getElementById("densityLegend");
  const trackControls = document.getElementById("trackControls");
  const densityControls = document.getElementById("densityControls");

  if (state.view === "tracks") {
    right.classList.remove("hidden");
    divider.classList.remove("hidden");
    labelRight.classList.remove("hidden");
    labelLeft.textContent = "1982–2000";
    labelRight.textContent = "2001–2019";
    yearLegend.classList.remove("hidden");
    densityLegend.classList.add("hidden");
    trackControls.classList.remove("hidden");
    densityControls.classList.add("hidden");

    document.getElementById("mapTitle").textContent = "Migration trajectories";
    document.getElementById("mapSubtitle").textContent =
      "Drag the divider to compare event trajectories from 1982–2000 and 2001–2019.";
    document.getElementById("mapNoteText").textContent =
      "Tracks come directly from Daily_Summary_CDHW_Events.xlsx. Colors represent event start year. Dateline crossings are split to avoid false trans-global lines.";

    renderTracks();
  }

  if (state.view === "density") {
    right.classList.remove("hidden");
    divider.classList.remove("hidden");
    labelRight.classList.remove("hidden");
    labelLeft.textContent = "1982–2000";
    labelRight.textContent = "2001–2019";
    yearLegend.classList.add("hidden");
    densityLegend.classList.remove("hidden");
    trackControls.classList.add("hidden");
    densityControls.classList.remove("hidden");

    document.getElementById("mapTitle").textContent = "Migration-track density";
    document.getElementById("mapSubtitle").textContent =
      "The same color scale is used for both periods.";
    document.getElementById("mapNoteText").textContent =
      "The native migration grid is bilinearly resampled only for display. Period statistics still use the original grid.";

    renderDensity();
  }

  if (state.view === "change") {
    right.classList.add("hidden");
    divider.classList.add("hidden");
    labelRight.classList.add("hidden");
    labelLeft.textContent = "2001–2019 minus 1982–2000";
    yearLegend.classList.add("hidden");
    densityLegend.classList.remove("hidden");
    trackControls.classList.add("hidden");
    densityControls.classList.remove("hidden");

    document.getElementById("mapTitle").textContent = "Change in migration-track count";
    document.getElementById("mapSubtitle").textContent =
      "Positive values indicate more track counts in 2001–2019; negative values indicate fewer.";
    document.getElementById("mapNoteText").textContent =
      "Change is calculated on the original aligned grid and then resampled only for visualization.";

    renderChange();
  }
}

function renderTracks() {
  ["left","right"].forEach(side => {
    if (state.trackLayers[side] && state.maps[side].hasLayer(state.trackLayers[side])) {
      state.maps[side].removeLayer(state.trackLayers[side]);
    }
    if (state.pointLayers[side] && state.maps[side].hasLayer(state.pointLayers[side])) {
      state.maps[side].removeLayer(state.pointLayers[side]);
    }
  });

  const earlyFeatures = state.tracks.features.filter(f => f.properties.start_year <= 2000);
  const recentFeatures = state.tracks.features.filter(f => f.properties.start_year >= 2001);

  state.trackLayers.left = L.geoJSON(
    {type:"FeatureCollection",features:earlyFeatures},
    {
      style: f => trackStyle(f),
      pointToLayer: (f,latlng) => L.circleMarker(latlng,{
        radius:2,
        color:yearColor(f.properties.start_year),
        weight:1,
        fillOpacity:.7
      })
    }
  ).addTo(state.maps.left);

  state.trackLayers.right = L.geoJSON(
    {type:"FeatureCollection",features:recentFeatures},
    {
      style: f => trackStyle(f),
      pointToLayer: (f,latlng) => L.circleMarker(latlng,{
        radius:2,
        color:yearColor(f.properties.start_year),
        weight:1,
        fillOpacity:.7
      })
    }
  ).addTo(state.maps.right);

  if (state.showPoints) {
    state.pointLayers.left = makeDailyPointLayer(earlyFeatures).addTo(state.maps.left);
    state.pointLayers.right = makeDailyPointLayer(recentFeatures).addTo(state.maps.right);
  }
}

function trackStyle(feature) {
  return {
    color: yearColor(feature.properties.start_year),
    weight: 1.1,
    opacity: state.trackOpacity,
    lineCap: "round",
    lineJoin: "round"
  };
}

function refreshTrackStyles() {
  ["left","right"].forEach(side => {
    if (state.trackLayers[side]) {
      state.trackLayers[side].setStyle(f => trackStyle(f));
    }
  });
}

function makeDailyPointLayer(features) {
  const group = L.layerGroup();

  features.forEach(f => {
    if (f.geometry.type !== "LineString") return;
    const color = yearColor(f.properties.start_year);

    f.geometry.coordinates.forEach(([lon,lat]) => {
      L.circleMarker([lat,lon],{
        radius:1.25,
        color,
        weight:0,
        fillColor:color,
        fillOpacity:Math.min(1,state.trackOpacity+.1)
      }).addTo(group);
    });
  });

  return group;
}

function yearColor(year) {
  for (let i=0; i<YEAR_BOUNDS.length-1; i++) {
    if (year >= YEAR_BOUNDS[i] && year < YEAR_BOUNDS[i+1]) return YEAR_COLORS[i];
  }
  return YEAR_COLORS[YEAR_COLORS.length-1];
}

function renderDensity() {
  const max = state.summary.display.density_color_max;

  setupDensityLegend(
    "Cumulative migration-track count",
    "linear-gradient(90deg,#fffdf0,#fff0b2,#fed976,#feb24c,#fd8d3c,#e6550d,#a63603,#6b2500)",
    "0",
    fmt(max)
  );

  state.rasterLayers.left = makeRasterLayer(
    state.rasters.early,
    v => densityColor(v,max),
    state.densityOpacity
  ).addTo(state.maps.left);

  state.rasterLayers.right = makeRasterLayer(
    state.rasters.recent,
    v => densityColor(v,max),
    state.densityOpacity
  ).addTo(state.maps.right);
}

function renderChange() {
  const maxAbs = state.summary.display.change_color_abs_max;

  setupDensityLegend(
    "Change in migration-track count",
    "linear-gradient(90deg,#54278f,#9e9ac8,#eeeeF2,#fff7ec,#fc8d59,#b30000)",
    `−${fmt(maxAbs)}`,
    `+${fmt(maxAbs)}`
  );

  state.rasterLayers.left = makeRasterLayer(
    state.rasters.change,
    v => changeColor(v,maxAbs),
    state.densityOpacity
  ).addTo(state.maps.left);
}

function setupDensityLegend(title,gradient,min,max) {
  document.getElementById("densityLegendTitle").textContent = title;
  document.getElementById("densityRamp").style.background = gradient;
  document.getElementById("densityMin").textContent = min;
  document.getElementById("densityMax").textContent = max;
}

function makeRasterLayer(raster,colorFn,opacity) {
  return new GeoRasterLayer({
    georaster:raster,
    opacity,
    resolution:256,
    zIndex:300,
    pixelValuesToColorFn: vals => {
      const v = vals?.[0];
      return colorFn(v);
    }
  });
}

function densityColor(v,max) {
  if (!Number.isFinite(v) || v <= 0 || max <= 0) return null;
  return palette(DENSITY_COLORS, clamp(v/max,0,1));
}

function changeColor(v,maxAbs) {
  if (!Number.isFinite(v) || maxAbs <= 0) return null;
  if (Math.abs(v) < maxAbs*.005) return "rgba(255,255,255,0)";

  if (v < 0) {
    return palette(CHANGE_NEG, clamp(Math.abs(v)/maxAbs,0,1));
  }
  return palette(CHANGE_POS, clamp(v/maxAbs,0,1));
}

function palette(colors,t) {
  if (t <= 0) return colors[0];
  if (t >= 1) return colors[colors.length-1];

  const x = t*(colors.length-1);
  const i = Math.floor(x);
  const f = x-i;
  const a = rgb(colors[i]);
  const b = rgb(colors[i+1]);

  return `rgb(${Math.round(a.r+(b.r-a.r)*f)},${Math.round(a.g+(b.g-a.g)*f)},${Math.round(a.b+(b.b-a.b)*f)})`;
}

function rgb(hex) {
  const h = hex.replace("#","");
  return {
    r:parseInt(h.slice(0,2),16),
    g:parseInt(h.slice(2,4),16),
    b:parseInt(h.slice(4,6),16)
  };
}

function updateSummary() {
  const s = state.summary;
  const early = s.events.early_count;
  const recent = s.events.recent_count;

  document.getElementById("earlyEvents").textContent = fmt(early);
  document.getElementById("recentEvents").textContent = fmt(recent);
  document.getElementById("eventChange").textContent = pctChange(early,recent);
  document.getElementById("cellChange").textContent =
    pctChange(s.native_stats.early.sum,s.native_stats.recent.sum);

  document.getElementById("cropOverlap").textContent =
    `${s.landuse.cropland.recent_overlap_pct.toFixed(1)}%`;
  document.getElementById("pastureOverlap").textContent =
    `${s.landuse.pasture.recent_overlap_pct.toFixed(1)}%`;
}

function drawCharts() {
  const annual = state.summary.events.annual;
  const years = annual.map(d => d.year);
  const counts = annual.map(d => d.events);

  new Chart(document.getElementById("annualChart"),{
    type:"line",
    data:{
      labels:years,
      datasets:[{
        data:counts,
        label:"Events",
        borderColor:"#0f766e",
        backgroundColor:"rgba(15,118,110,.10)",
        fill:true,
        borderWidth:2,
        pointRadius:0,
        tension:.18
      }]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      animation:false,
      plugins:{legend:{display:false}},
      scales:{
        x:{
          grid:{display:false},
          ticks:{maxTicksLimit:6,font:{size:9},color:"#6f7d89"}
        },
        y:{
          beginAtZero:true,
          ticks:{precision:0,font:{size:9},color:"#6f7d89"},
          grid:{color:"rgba(100,115,130,.12)"}
        }
      }
    }
  });

  const lu = state.summary.landuse;

  new Chart(document.getElementById("landuseChart"),{
    type:"bar",
    data:{
      labels:["Cropland","Pasture"],
      datasets:[
        {
          label:"1982–2000",
          data:[
            lu.cropland.early_weighted_mean,
            lu.pasture.early_weighted_mean
          ],
          backgroundColor:"#9bc6bf"
        },
        {
          label:"2001–2019",
          data:[
            lu.cropland.recent_weighted_mean,
            lu.pasture.recent_weighted_mean
          ],
          backgroundColor:"#0f766e"
        }
      ]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      animation:false,
      plugins:{
        legend:{labels:{boxWidth:9,font:{size:9}}}
      },
      scales:{
        x:{
          grid:{display:false},
          ticks:{font:{size:9}}
        },
        y:{
          beginAtZero:true,
          title:{
            display:true,
            text:"Land-use-weighted mean track count",
            font:{size:9}
          },
          ticks:{font:{size:9}}
        }
      }
    }
  });
}

function pctChange(a,b) {
  if (!Number.isFinite(a) || a === 0 || !Number.isFinite(b)) return "—";
  const p = (b-a)/a*100;
  return `${p>=0?"+":""}${p.toFixed(1)}%`;
}

function fmt(n) {
  n = Number(n);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e6) return `${(n/1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `${(n/1e3).toFixed(1)}k`;
  if (Math.abs(n) >= 100) return n.toFixed(0);
  if (Math.abs(n) >= 10) return n.toFixed(1);
  return n.toFixed(2).replace(/\.00$/,"");
}

function clamp(v,a,b) {
  return Math.max(a,Math.min(b,v));
}

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function setStatus(text,error=false) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.classList.toggle("error",error);
}
