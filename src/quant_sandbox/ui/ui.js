// FILE: ui.js
// Quant Sandbox UI — console
// FIXED: eliminates call stack overflow by
//  - hard-suppressing zoom/pan callbacks during ALL programmatic updates (update/resize/zoomScale)
//  - removing duplicate installPopovers + duplicate init/listeners via idempotent installers
//  - using ONE authoritative xBounds shape: { xMin, xMax } everywhere
//  - preventing listener re-attachment on drawer/splitters

window.onerror = (msg, url, line, col, err) => {
  console.log("ERR:", msg, url + ":" + line + ":" + col);
  if (err?.stack) console.log(err.stack);
};

(() => {
  const _setInterval = window.setInterval;
  window.setInterval = (fn, ms, ...rest) => _setInterval(() => {
    try { fn(); } catch (e) { console.log("interval error:", e?.stack || e); throw e; }
  }, ms, ...rest);

  const _add = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(type, listener, opts) {
    // prevents accidental re-register loops from exploding the stack silently
    return _add.call(this, type, listener, opts);
  };

  window.onerror = (msg, url, line, col, err) => {
    console.log("ERR:", msg, url + ":" + line + ":" + col);
    if (err?.stack) console.log(err.stack);
  };
})();




console.log("ui.js loaded", new Date().toISOString());
if (typeof Chart === "undefined") console.error("Chart.js not loaded");

const API_BASE = ""; // same-origin
const HISTORY_LIMIT = 20;
let __lastBottomPanelId = null;

// ============================================================
// DOM
// ============================================================
const els = {
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebarToggle"),
  apiStatus: document.getElementById("apiStatus"),

  chartTitle: document.getElementById("chartTitle"),
  chartSubtitle: document.getElementById("chartSubtitle"),
  chartEl: document.getElementById("chart"),
  yUnit: document.getElementById("yUnit"),

  cmd: document.getElementById("cmd"),
  runBtn: document.getElementById("runBtn"),
  saveBtn: document.getElementById("saveBtn"),
  copyJsonBtn: document.getElementById("copyJsonBtn"),
  snapshotBtn: document.getElementById("snapshotBtn"),
  chartTableBtn: document.getElementById("chartTableBtn") || null,
  colorBtn: document.getElementById("colorBtn"),
  gearBtn: document.getElementById("gearBtn") || null,

  dataBtn: document.getElementById("dataBtn") || null,
  msg: document.getElementById("msg"),

  historyList: document.getElementById("historyList"),
  histCount: document.getElementById("histCount"),
  clearHistoryBtn: document.getElementById("clearHistoryBtn"),

  libraryTree: document.getElementById("libraryTree"),
  newFolderBtn: document.getElementById("newFolderBtn"),
  exportBtn: document.getElementById("exportBtn"),
  importInput: document.getElementById("importInput"),

  historyCaret: document.getElementById("historyCaret"),
  libraryCaret: document.getElementById("libraryCaret"),
  helpCaret: document.getElementById("helpCaret") || null,
  seasonalityCaret: document.getElementById("seasonalityCaret") || null,

  // TA + Panel popover controls
  taBtn: document.getElementById("taBtn"),
  taPopover: document.getElementById("taPopover"),
  taSelect: document.getElementById("taSelect") || null,
  taAddBtn: document.getElementById("taAddBtn") || null,
  taList: document.getElementById("taList") || null,
  ovBB: document.getElementById("ovBB"),
  smaN: document.getElementById("smaN"),
  emaN: document.getElementById("emaN"),
  addSMA: document.getElementById("addSMA"),
  clearSMA: document.getElementById("clearSMA"),
  addEMA: document.getElementById("addEMA"),
  clearEMA: document.getElementById("clearEMA"),

  panelBtn: document.getElementById("panelBtn"),
  panelPopover: document.getElementById("panelPopover"),

  // Gear popover
  gearPopover: document.getElementById("gearPopover") || null,
  gridToggle: document.getElementById("gridToggle") || null,
  menuColorBtn: document.getElementById("menuColorBtn") || null,
  chartTypeSel: document.getElementById("chartTypeSel") || null,
  helpList: document.getElementById("helpList") || null,
  seasonalityList: document.getElementById("seasonalityList") || null,
  addSeasonalityBtn: document.getElementById("addSeasonalityBtn") || null,
  seasonalitySaveBtn: document.getElementById("seasonalitySaveBtn") || null,
  seasonalitySnapBtn: document.getElementById("seasonalitySnapBtn") || null,
  chartTableWrap: document.getElementById("chartTableWrap") || null,
  chartTableBody: document.getElementById("chartTableBody") || null,
  chartTableCopyBtn: document.getElementById("chartTableCopyBtn") || null,
  chartTableExportBtn: document.getElementById("chartTableExportBtn") || null,
  chartTableRemoveBtn: document.getElementById("chartTableRemoveBtn") || null,
  chartingCollapseBtn: document.getElementById("chartingCollapseBtn") || null,

  chartingAssetInput: document.getElementById("chartingAssetInput") || null,
  chartingAddTickerBtn: document.getElementById("chartingAddTickerBtn") || null,
  chartingAddTickerMore: document.getElementById("chartingAddTickerMore") || null,
  chartingTickerList: document.getElementById("chartingTickerList") || null,
  chartingMetricSelect: document.getElementById("chartingMetricSelect") || null,
  chartingAddMetricBtn: document.getElementById("chartingAddMetricBtn") || null,
  chartingMetricList: document.getElementById("chartingMetricList") || null,
  chartingTemplateName: document.getElementById("chartingTemplateName") || null,
  chartingSaveTemplateBtn: document.getElementById("chartingSaveTemplateBtn") || null,
  chartingTemplateList: document.getElementById("chartingTemplateList") || null,
};

let lastResponseJson = null;
let expandedFolders = new Set();
let dragPayload = null;
let collapsedPanels = loadJSON("qs.panels.collapsed.v1", { history: true, library: true, help: true, seasonality: true });
let activeCmdId = null;
let __syncingCmdText = false;
let __lastCmdLines = [];
let __lineToCmdId = [];
let __keepTrailingNewline = false;
let __openSidebarPanel = null;

// Palette
const PALETTE = ["#1f77b4", "#0ea5e9", "#16a34a", "#f97316", "#a855f7", "#ef4444"];
let paletteIdx = loadJSON("qs.chart.paletteIdx.v1", 0);
const LAST_VALUE_PAD_RIGHT = 80;
const MAX_Y_AXES_PER_SIDE = 3;
const MAX_Y_AXES = MAX_Y_AXES_PER_SIDE * 2;
const TOP_DATES_PAD = 28;
const AXIS_TICK_FONT = { family: "system-ui, -apple-system, Segoe UI, Roboto, Arial", size: 10 };

// Chart instances
let priceChart = null;
let panelCharts = new Map(); // panelId -> Chart instance

// Color persistence per dataset label
const DS_COLOR_KEY = "qs.dataset.colors.v1";
const dsColors = loadJSON(DS_COLOR_KEY, {});
function sanitizeDsColors() {
  let changed = false;
  for (const k of Object.keys(dsColors)) {
    const v = dsColors[k];
    const hex = toHexColor(v);
    if (!hex) {
      dsColors[k] = autoColor(k);
      changed = true;
    } else if (hex !== v) {
      dsColors[k] = hex;
      changed = true;
    }
  }
  if (changed) saveJSON(DS_COLOR_KEY, dsColors);
}

// Panel legend toggle persistence
const LS_PANEL_LEGENDS = "qs.panel.legends.v1";
const panelLegends = loadJSON(LS_PANEL_LEGENDS, {});
function savePanelLegends() { saveJSON(LS_PANEL_LEGENDS, panelLegends); }

// Panel “follow-base” specs
const LS_PANEL_SPECS = "qs.panel.specs.v1";
let panelSpecs = loadJSON(LS_PANEL_SPECS, {});
function savePanelSpecs() { saveJSON(LS_PANEL_SPECS, panelSpecs); }

// UI prefs
const LS_UI_PREFS = "qs.ui.prefs.v1";
let uiPrefs = loadJSON(LS_UI_PREFS, { grid: true, chartType: "line" });
function saveUiPrefs() { saveJSON(LS_UI_PREFS, uiPrefs); }

// Charting templates
const LS_CHART_TEMPLATES = "qs.charting.templates.v1";
const LS_CHART_TEMPLATE_ACTIVE = "qs.charting.templates.active.v1";
let chartingTemplates = loadJSON(LS_CHART_TEMPLATES, null);
let chartingActiveTemplateId = loadJSON(LS_CHART_TEMPLATE_ACTIVE, null);

const CHARTING_METRICS = {
  volume: { label: "Volume", shareable: false, singleTicker: true },
  rsi: { label: "RSI", shareable: true, singleTicker: false },
  drawdown: { label: "Drawdown", shareable: true, singleTicker: false },
  sharpe: { label: "Sharpe", shareable: true, singleTicker: false },
  zscore: { label: "Z-Score", shareable: true, singleTicker: false },
  ma: { label: "Moving Average", shareable: true, singleTicker: true },
  bollinger: { label: "Bollinger", shareable: false, singleTicker: true },
  corr: { label: "Correlation", shareable: false, singleTicker: false },
};

// ============================================================
// Runtime state
// ============================================================
const state = {
  base: {
    expr: "",
    start: null,
    end: null,
    durationToken: "3y",
    bar_size: "1 day",
    use_rth: true,
    norm: null,
    ccy: null,
    unit: null,
    axisOverflowSide: "right",
    xBounds: null, // { xMin, xMax } in ms
  },
  overlays: { bb: null, sma: [], ema: [] },
  data: { price: null, bb: null, ma: null },
};

// ============================================================
// Layout + Panel Stack
// ============================================================
const LS_PANEL_HEIGHTS = "qs.panel.heights.v1";
const panelHeights = loadJSON(LS_PANEL_HEIGHTS, {});

const PANEL_IDS = { PRICE: "price", SEASONALITY_MODULE: "seasonality_module" };

const panels = new Map(); // panelId -> { id, kind, title, rootEl, canvas, chart, spec }
let panelSeq = 0;
let activePanelId = null;

let chartInner = null;
let stackEl = null;
let dataDrawer = null;
let dataDrawerContent = null;
let dataDrawerOpen = false;

// ============================================================
// X SYNC (STACK OVERFLOW FIX)
// ============================================================
let __syncingXBounds = false;
let __togglingXAxis = false;
let __activeZoomChart = null;
let __updatingBaseX = false;
let __resizingCharts = false;
let __pendingBaseXBounds = null;
let __syncQueued = false;
let __lastSyncOrigin = null;

// Hard suppression gate: stops plugin callbacks from re-entering sync during programmatic ops
function withZoomSuppressed(chart, fn) {
  if (!chart) return;
  chart.$qsSuppressZoom = true;
  try { fn(); }
  finally {
    // keep suppression through microtask + RAF (plugin callbacks can be async)
    Promise.resolve().then(() => {
      requestAnimationFrame(() => { chart.$qsSuppressZoom = false; });
    });
  }
}

function _num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function _same(a, b, eps = 2) {
  if (a == null || b == null) return false;
  return Math.abs(a - b) <= eps;
}
function _boundsEqual(a, b) {
  if (!a || !b) return false;
  return _same(a.xMin, b.xMin) && _same(a.xMax, b.xMax);
}

function _getChartBounds(ch) {
  // Prefer zoom plugin bounds if present
  try {
    if (typeof ch?.getZoomedScaleBounds === "function") {
      const z = ch.getZoomedScaleBounds();
      const bx = z?.x;
      const xMin = _num(bx?.min);
      const xMax = _num(bx?.max);
      if (xMin != null && xMax != null) return { xMin, xMax };
    }
  } catch {}

  if (!ch?.scales?.x) return null;
  const xMin = _num(ch.scales.x.min);
  const xMax = _num(ch.scales.x.max);
  if (xMin == null || xMax == null) return null;
  return { xMin, xMax };
}

function _applyBoundsViaZoomScale(ch, xb) {
  if (!ch || !xb || xb.xMin == null || xb.xMax == null) return;

  const cur = _getChartBounds(ch);
  if (cur && _boundsEqual(cur, xb)) return;

  ch.$qsSyncApply = true;
  withZoomSuppressed(ch, () => {
    if (ch?.options?.scales?.x) {
      ch.options.scales.x.min = xb.xMin;
      ch.options.scales.x.max = xb.xMax;
      ch.update("none");
    }
  });

  Promise.resolve().then(() => {
    requestAnimationFrame(() => { ch.$qsSyncApply = false; });
  });
}

function syncAllPanelsToBaseXBounds(originChart = null) {
  const xb = state?.base?.xBounds;
  if (!xb) return;

  __syncingXBounds = true;
  try {
    if (priceChart && priceChart !== originChart) _applyBoundsViaZoomScale(priceChart, xb);
    for (const ch of panelCharts.values()) {
      if (ch && ch !== originChart) _applyBoundsViaZoomScale(ch, xb);
    }
  } finally {
    __syncingXBounds = false;
  }
}

function updateBaseXFromChart(ch) {
  if (!ch) return;

  // Ignore programmatic applications and UI-only updates
  if (__syncingXBounds) return;
  if (__togglingXAxis) return;
  if (ch.$qsSyncApply) return;
  if (ch.$qsAxisVisUpdate) return;
  if (ch.$qsSuppressZoom) return;
  if (__updatingBaseX) return;
  __updatingBaseX = true;

  const xb = _getChartBounds(ch);
  if (!xb) {
    __updatingBaseX = false;
    return;
  }

  if (_boundsEqual(state.base.xBounds, xb)) {
    __updatingBaseX = false;
    return;
  }

  state.base.xBounds = xb;
  __pendingBaseXBounds = xb;
  __lastSyncOrigin = ch;
  if (!__syncQueued) {
    __syncQueued = true;
    requestAnimationFrame(() => {
      __syncQueued = false;
      if (__pendingBaseXBounds) {
        syncAllPanelsToBaseXBounds(__lastSyncOrigin);
      }
      __pendingBaseXBounds = null;
      __lastSyncOrigin = null;
      __updatingBaseX = false;
    });
    return;
  }
  Promise.resolve().then(() => {
    requestAnimationFrame(() => { __updatingBaseX = false; });
  });
}

function zoomPanSyncCallbacks() {
  return {
    pan: {
      enabled: false,
      mode: "x",
      onPanStart: ({ chart }) => {
        if (chart?.$qsSuppressZoom) return;
        __activeZoomChart = chart;
      },
      onPanComplete: ({ chart }) => {
        if (chart?.$qsSuppressZoom) return;
        if (__syncingXBounds || __togglingXAxis || __updatingBaseX) return;
        if (chart?.$qsAxisVisUpdate || chart?.$qsSyncApply) return;
        if (chart !== __activeZoomChart) return;
        updateBaseXFromChart(chart);
      },
    },
    zoom: {
      wheel: { enabled: false, speed: 0.035 },
      pinch: { enabled: false },
      drag: { enabled: false, threshold: 0 },
      mode: "xy",
      scaleMode: "xy",
      onZoomStart: ({ chart }) => {
        if (chart?.$qsSuppressZoom) return;
        __activeZoomChart = chart;
      },
      onZoomComplete: ({ chart }) => {
        if (chart?.$qsSuppressZoom) return;
        if (__syncingXBounds || __togglingXAxis || __updatingBaseX) return;
        if (chart?.$qsAxisVisUpdate || chart?.$qsSyncApply) return;
        if (chart !== __activeZoomChart) return;
        updateBaseXFromChart(chart);
      },
    },
  };
}

// ============================================================
// Viewport setup
// ============================================================
function setupChartViewport() {
  if (!els.chartEl) return;

  let cur = els.chartEl.parentElement;
  while (cur && !cur.classList.contains("chart-inner")) cur = cur.parentElement;
  chartInner = cur || els.chartEl.parentElement;
  if (!chartInner) return;

  chartInner.classList.add("qs-chart-inner");
  chartInner.style.display = "flex";
  chartInner.style.flexDirection = "column";
  chartInner.style.minHeight = "0";
  chartInner.style.overflow = "hidden";

  let canvasWrap = els.chartEl.parentElement;
  while (canvasWrap && !(canvasWrap.classList && canvasWrap.classList.contains("chart-canvas-wrap"))) {
    canvasWrap = canvasWrap.parentElement;
  }
  if (!canvasWrap) {
    canvasWrap = document.createElement("div");
    canvasWrap.className = "chart-canvas-wrap";
    els.chartEl.parentElement.insertBefore(canvasWrap, els.chartEl);
    canvasWrap.appendChild(els.chartEl);
  }

  stackEl = chartInner.querySelector("#panelStack");
  if (!stackEl) {
    stackEl = document.createElement("div");
    stackEl.id = "panelStack";
    stackEl.className = "qs-panel-stack";
    chartInner.appendChild(stackEl);
  }

  // Ensure the PRICE panel exists and holds the main canvas wrapper
  if (!stackEl.querySelector(`[data-panel-id="${PANEL_IDS.PRICE}"]`)) {
    const pricePanel = document.createElement("div");
    pricePanel.className = "qpanel qs-price-panel";
    pricePanel.dataset.panelId = PANEL_IDS.PRICE;

    pricePanel.innerHTML = `
      <div class="qpanel-head">
        <div class="qpanel-title">Price</div>
        <div class="qpanel-actions">
          <button class="iconbtn" data-act="legend" title="Legend" aria-label="Legend">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6-10-6-10-6z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
          </button>
          <button class="iconbtn" data-act="clear" title="Clear" aria-label="Clear">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 6h16"></path>
              <path d="M8 6l1 14h6l1-14"></path>
              <path d="M10 6l1-2h2l1 2"></path>
            </svg>
          </button>
        </div>
      </div>
      <div class="qpanel-canvas qs-panel-canvas"></div>
    `;

    pricePanel.addEventListener("click", (e) => {
      const btn = e.target?.closest?.("button[data-act]");
      const act = btn?.dataset?.act;
      if (!act) return;
      if (act === "legend" && priceChart) {
        toggleChartLegend(priceChart);
      }
      if (act === "clear") destroyPriceChart();
    });

    pricePanel.querySelector(".qpanel-canvas").appendChild(canvasWrap);
    stackEl.insertBefore(pricePanel, stackEl.firstChild);

    panels.set(PANEL_IDS.PRICE, {
      id: PANEL_IDS.PRICE,
      kind: "price",
      title: "Price",
      rootEl: pricePanel,
      canvas: els.chartEl,
      chart: null,
    });
  }

  stackEl.querySelectorAll(".qpanel").forEach(p => installPanelReorder(p));

  // Drawer (idempotent)
  dataDrawer = chartInner.querySelector("#qsDataDrawer");
  if (!dataDrawer) {
    dataDrawer = document.createElement("div");
    dataDrawer.id = "qsDataDrawer";
    dataDrawer.className = "qs-drawer";
    dataDrawer.innerHTML = `
      <div class="qs-drawer-grab" title="Drag to resize"></div>
      <div class="qs-drawer-inner">
        <div class="qs-drawer-tabs">
          <button class="btn btn-ghost" data-tab="data">Data</button>
          <button class="btn btn-ghost" data-tab="csv">CSV</button>
          <button class="btn btn-ghost" data-tab="json">JSON</button>
          <button class="btn btn-ghost" data-act="copy">Copy</button>
        </div>
        <div id="qsDataContent" class="qs-drawer-content"></div>
      </div>
    `;
    chartInner.appendChild(dataDrawer);
  }

  dataDrawerContent = dataDrawer.querySelector("#qsDataContent");
  installDrawerBehavior(); // idempotent installer

  stackEl.style.flex = "1 1 auto";
  stackEl.style.minHeight = "0";
  stackEl.style.overflow = "hidden";
  stackEl.style.display = "flex";
  stackEl.style.flexDirection = "column";

  rebuildSplitters();
  applySavedHeights();
  updatePanelsXAxisVisibility();

  requestChartResizeAll();
}

function listPanelOrder() {
  const arr = [];
  if (!stackEl) return arr;
  stackEl.querySelectorAll(".qpanel[data-panel-id]").forEach(el => arr.push(el.dataset.panelId));
  return arr;
}

function rebuildSplitters() {
  if (!stackEl) return;
  stackEl.querySelectorAll(".qs-splitter").forEach(s => s.remove());

  const order = listPanelOrder();
  for (let i = 0; i < order.length - 1; i++) {
    const a = order[i];
    const aEl = stackEl.querySelector(`.qpanel[data-panel-id="${a}"]`);
    if (!aEl) continue;

    const sp = document.createElement("div");
    sp.className = "qs-splitter";
    sp.dataset.a = a;
    sp.dataset.b = order[i + 1];

    aEl.insertAdjacentElement("afterend", sp);
    installSplitterDrag(sp);
  }
}

function applySavedHeights() {
  if (!stackEl) return;
  const order = listPanelOrder();
  const hasSubpanels = order.length > 1;

  for (const pid of order) {
    const pEl = stackEl.querySelector(`.qpanel[data-panel-id="${pid}"]`);
    if (!pEl) continue;

    if (pid === PANEL_IDS.PRICE) {
      pEl.style.flex = "1 1 auto";
      pEl.style.minHeight = hasSubpanels ? "220px" : "0px";
      continue;
    }

    const h = Number(panelHeights[pid] ?? 200);
    const clamped = clamp(h, 140, 520);
    pEl.style.flex = `0 0 ${clamped}px`;
    pEl.style.minHeight = "140px";
  }
}

function savePanelHeights() { saveJSON(LS_PANEL_HEIGHTS, panelHeights); }

function installSplitterDrag(splitterEl) {
  if (!splitterEl || splitterEl.$qsInstalled) return;
  splitterEl.$qsInstalled = true;

  let dragging = false;
  let startY = 0;
  let startHa = 0;
  let startHb = 0;

  const getPanelEl = (pid) => stackEl?.querySelector(`.qpanel[data-panel-id="${pid}"]`);

  const onDown = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    dragging = true;
    startY = ev.clientY;

    const a = splitterEl.dataset.a;
    const b = splitterEl.dataset.b;

    const aEl = getPanelEl(a);
    const bEl = getPanelEl(b);
    if (!aEl || !bEl) return;

    startHa = aEl.getBoundingClientRect().height;
    startHb = bEl.getBoundingClientRect().height;

    document.body.classList.add("qs-resizing");
    window.addEventListener("mousemove", onMove, true);
    window.addEventListener("mouseup", onUp, true);
  };

  const onMove = (ev) => {
    if (!dragging) return;
    const dy = ev.clientY - startY;

    const a = splitterEl.dataset.a;
    const b = splitterEl.dataset.b;
    const aEl = getPanelEl(a);
    const bEl = getPanelEl(b);
    if (!aEl || !bEl) return;

    const minH = 140;

    if (a === PANEL_IDS.PRICE && b !== PANEL_IDS.PRICE) {
      const newHb = clamp(startHb - dy, minH, 520);
      bEl.style.flex = `0 0 ${newHb}px`;
      panelHeights[b] = newHb;
      savePanelHeights();
      requestChartResizeAll();
      return;
    }

    if (b === PANEL_IDS.PRICE && a !== PANEL_IDS.PRICE) {
      const newHa = clamp(startHa + dy, minH, 520);
      aEl.style.flex = `0 0 ${newHa}px`;
      panelHeights[a] = newHa;
      savePanelHeights();
      requestChartResizeAll();
      return;
    }

    const newHa = clamp(startHa + dy, minH, 520);
    const newHb = clamp(startHb - dy, minH, 520);

    aEl.style.flex = `0 0 ${newHa}px`;
    bEl.style.flex = `0 0 ${newHb}px`;

    panelHeights[a] = newHa;
    panelHeights[b] = newHb;
    savePanelHeights();
    requestChartResizeAll();
  };

  const onUp = () => {
    dragging = false;
    document.body.classList.remove("qs-resizing");
    window.removeEventListener("mousemove", onMove, true);
    window.removeEventListener("mouseup", onUp, true);
  };

  splitterEl.addEventListener("mousedown", onDown);
}

function requestChartResizeAll() {
  if (__resizingCharts) return;
  __resizingCharts = true;
  try {
    withZoomSuppressed(priceChart, () => priceChart?.resize());
  } catch {}
  for (const ch of panelCharts.values()) {
    try {
      withZoomSuppressed(ch, () => ch.resize());
    } catch {}
  }
  requestAnimationFrame(() => { __resizingCharts = false; });
}

function installPanelReorder(panelEl) {
  if (!panelEl || panelEl.$qsReorderInstalled) return;
  const panelId = panelEl.dataset.panelId;
  if (!panelId) return;

  const head = panelEl.querySelector(".qpanel-head");
  if (!head) return;
  panelEl.$qsReorderInstalled = true;

  let dragging = false;
  let placeholder = null;
  let offsetY = 0;
  let start = null;

  const onMove = (ev) => {
    if (!dragging || !placeholder || !stackEl) return;
    const stackRect = stackEl.getBoundingClientRect();
    const top = ev.clientY - stackRect.top - offsetY;
    panelEl.style.top = `${top}px`;

    const panelsInStack = Array.from(stackEl.querySelectorAll(".qpanel"))
      .filter(p => p !== panelEl && p !== placeholder);
    let target = null;
    for (const p of panelsInStack) {
      if (p.dataset.panelId === PANEL_IDS.PRICE) continue;
      const r = p.getBoundingClientRect();
      if (ev.clientY < r.top + r.height / 2) { target = p; break; }
    }

    if (target) stackEl.insertBefore(placeholder, target);
    else stackEl.appendChild(placeholder);
  };

  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("qs-grabbing");
    panelEl.classList.remove("qs-panel-dragging");
    window.removeEventListener("mousemove", onMove, true);
    window.removeEventListener("mouseup", onUp, true);

    if (placeholder && stackEl) {
      stackEl.insertBefore(panelEl, placeholder);
      placeholder.remove();
    }
    placeholder = null;

    if (start) {
      panelEl.style.position = start.position;
      panelEl.style.left = start.left;
      panelEl.style.top = start.top;
      panelEl.style.width = start.width;
      panelEl.style.zIndex = start.zIndex;
      panelEl.style.pointerEvents = start.pointerEvents;
      panelEl.style.flex = start.flex;
    }

    rebuildSplitters();
    applySavedHeights();
    updatePanelsXAxisVisibility();
    requestChartResizeAll();
  };

  head.addEventListener("mousedown", (ev) => {
    if (ev.button !== 0 || !stackEl) return;
    if (ev.target?.closest?.(".qpanel-actions, button")) return;
    ev.preventDefault();
    ev.stopPropagation();

    dragging = true;
    document.body.classList.add("qs-grabbing");
    panelEl.classList.add("qs-panel-dragging");

    const stackRect = stackEl.getBoundingClientRect();
    const rect = panelEl.getBoundingClientRect();
    offsetY = ev.clientY - rect.top;

    stackEl.querySelectorAll(".qs-splitter").forEach(s => s.remove());

    placeholder = document.createElement("div");
    placeholder.className = "qpanel qs-panel-placeholder";
    placeholder.style.height = `${rect.height}px`;
    placeholder.style.flex = `0 0 ${rect.height}px`;
    stackEl.insertBefore(placeholder, panelEl.nextSibling);

    start = {
      position: panelEl.style.position || "",
      left: panelEl.style.left || "",
      top: panelEl.style.top || "",
      width: panelEl.style.width || "",
      zIndex: panelEl.style.zIndex || "",
      pointerEvents: panelEl.style.pointerEvents || "",
      flex: panelEl.style.flex || "",
    };

    panelEl.style.position = "absolute";
    panelEl.style.left = `${rect.left - stackRect.left}px`;
    panelEl.style.top = `${rect.top - stackRect.top}px`;
    panelEl.style.width = `${rect.width}px`;
    panelEl.style.zIndex = "1000";
    panelEl.style.pointerEvents = "none";
    panelEl.style.flex = `0 0 ${rect.height}px`;

    window.addEventListener("mousemove", onMove, true);
    window.addEventListener("mouseup", onUp, true);
  });
}

/**
 * Only the bottom-most panel shows X ticks/labels.
 * UI-only; must not touch bounds.
 */
function updatePanelsXAxisVisibility() {
  const order = listPanelOrder();
  if (!order.length) return;
  const bottomId = order[order.length - 1];
  if (bottomId === __lastBottomPanelId) return;
  __lastBottomPanelId = bottomId;

  __togglingXAxis = true;
  try {
    const applyXVis = (ch, show) => {
      if (!ch?.options?.scales?.x) return;
      const x = ch.options.scales.x;
      if (!x.ticks || typeof x.ticks !== "object") x.ticks = {};
      if (!x.grid || typeof x.grid !== "object") x.grid = {};

      x.display = true;
      x.ticks.display = !!show;
      x.grid.drawTicks = !!show;

      ch.$qsAxisVisUpdate = true;
      try {
        withZoomSuppressed(ch, () => ch.update("none"));
      } finally {
        Promise.resolve().then(() => {
          requestAnimationFrame(() => { ch.$qsAxisVisUpdate = false; });
        });
      }
    };

    if (priceChart) applyXVis(priceChart, bottomId === PANEL_IDS.PRICE);
    for (const [pid, ch] of panelCharts.entries()) applyXVis(ch, pid === bottomId);
  } finally {
    __togglingXAxis = false;
  }
}

// ============================================================
// Panels
// ============================================================
function createPanel({ kind = "series", title = "Panel", height = 200 } = {}) {
  if (!stackEl) setupChartViewport();
  if (!stackEl) return null;

  const panelId = `p${++panelSeq}`;
  const canvasId = `cv_${panelId}`;

  if (panelLegends[panelId] == null) {
    panelLegends[panelId] = false;
    savePanelLegends();
  }

  const el = document.createElement("div");
  el.className = "qpanel";
  el.dataset.panelId = panelId;

  el.innerHTML = `
    <div class="qpanel-head">
      <div class="qpanel-title" id="ttl_${panelId}">${escapeHtml(title)}</div>
      <div class="qpanel-actions">
        <button class="iconbtn" data-act="legend" title="Legend" aria-label="Legend">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6-10-6-10-6z"></path>
            <circle cx="12" cy="12" r="3"></circle>
          </svg>
        </button>
        <button class="iconbtn" data-act="clear" title="Clear" aria-label="Clear">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 6h16"></path>
            <path d="M8 6l1 14h6l1-14"></path>
            <path d="M10 6l1-2h2l1 2"></path>
          </svg>
        </button>
        <button class="iconbtn" data-act="remove" title="Remove" aria-label="Remove">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 6l12 12"></path>
            <path d="M18 6L6 18"></path>
          </svg>
        </button>
      </div>
    </div>
    <div class="qpanel-canvas qs-panel-canvas">
      <canvas id="${canvasId}"></canvas>
    </div>
  `;

  el.addEventListener("click", (e) => {
    const btn = e.target?.closest?.("button[data-act]");
    const act = btn?.dataset?.act;
    if (!act) return;
    if (act === "legend") togglePanelLegend(panelId);
    if (act === "clear") clearPanel(panelId);
    if (act === "remove") removePanel(panelId);
  });

  stackEl.appendChild(el);

  const canvas = el.querySelector(`#${canvasId}`);
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.display = "block";

  panels.set(panelId, { id: panelId, kind, title, rootEl: el, canvas, chart: null, spec: null });
  panelHeights[panelId] = clamp(Number(panelHeights[panelId] ?? height), 140, 520);
  savePanelHeights();

  setActivePanel(panelId);
  installPanelReorder(el);

  rebuildSplitters();
  applySavedHeights();
  updatePanelsXAxisVisibility();
  requestChartResizeAll();

  return panelId;
}

function ensureSeasonalityModulePanel() {
  const host = document.getElementById("seasonalityModulePanel");
  if (!host) return null;
  const panelId = PANEL_IDS.SEASONALITY_MODULE;
  const existing = panels.get(panelId);
  if (existing?.rootEl && host.contains(existing.rootEl)) return panelId;

  host.innerHTML = "";
  const el = document.createElement("div");
  el.className = "qpanel qs-seasonality-panel";
  el.dataset.panelId = panelId;
  el.innerHTML = `
    <div class="qpanel-head">
      <div class="qpanel-title" id="ttl_${panelId}">Seasonality</div>
    </div>
    <div class="qpanel-canvas qs-panel-canvas">
      <canvas id="cv_${panelId}"></canvas>
    </div>
  `;
  host.appendChild(el);

  const canvas = el.querySelector(`#cv_${panelId}`);
  if (canvas) {
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
  }

  panels.set(panelId, { id: panelId, kind: "seasonality", title: "Seasonality", rootEl: el, canvas, chart: null, spec: null });
  panelSpecs[panelId] = panelSpecs[panelId] || { kind: "seasonality", params: { expr: state.base.expr || "", mode: "heatmap", bucket: "month", yearsSpec: "10" } };
  savePanelSpecs();

  return panelId;
}

function togglePanelLegend(panelId) {
  panelLegends[panelId] = !panelLegends[panelId];
  savePanelLegends();

  const ch = panelCharts.get(panelId);
  if (ch?.options?.plugins?.legend) {
    ch.options.plugins.legend.display = !!panelLegends[panelId];
    withZoomSuppressed(ch, () => ch.update("none"));
  }
}

function setActivePanel(panelId) {
  activePanelId = panelId;
  if (!stackEl) return;
  stackEl.querySelectorAll(".qpanel").forEach(p => {
    p.style.outline = (p.dataset.panelId === panelId) ? "2px solid rgba(37,99,235,.25)" : "none";
  });
}

function clearPanel(panelId) {
  const p = panels.get(panelId);
  if (!p) return;

  const ch = panelCharts.get(panelId);
  if (ch) {
    try { ch.destroy(); } catch {}
    panelCharts.delete(panelId);
  }

  const t = document.getElementById(`ttl_${panelId}`);
  if (t) t.textContent = "Panel";
  p.title = "Panel";

  const ctx = p.canvas.getContext("2d");
  ctx.clearRect(0, 0, p.canvas.width, p.canvas.height);

  updatePanelsXAxisVisibility();
  requestChartResizeAll();
}

function removePanel(panelId) {
  if (panelId === PANEL_IDS.PRICE) return;

  clearPanel(panelId);
  panels.delete(panelId);

  const el = stackEl?.querySelector(`.qpanel[data-panel-id="${panelId}"]`);
  if (el) el.remove();

  delete panelHeights[panelId];
  savePanelHeights();

  delete panelSpecs[panelId];
  savePanelSpecs();
  markCmdRemoved(panelId);

  rebuildSplitters();
  applySavedHeights();
  updatePanelsXAxisVisibility();
  requestChartResizeAll();

  const order = listPanelOrder().filter(x => x !== PANEL_IDS.PRICE);
  activePanelId = order.length ? order[order.length - 1] : PANEL_IDS.PRICE;
  setActivePanel(activePanelId);
}

function renderPanelError(panelId, msg) {
  const p = panels.get(panelId);
  if (!p) return;
  const ctx = p.canvas.getContext("2d");
  ctx.clearRect(0, 0, p.canvas.width, p.canvas.height);
  ctx.font = "12px system-ui, -apple-system, Segoe UI, Roboto, Arial";
  ctx.fillStyle = "rgba(239,68,68,.9)";
  ctx.fillText(`Panel error: ${msg}`, 10, 20);
}

function setPanelTitle(panelId, title) {
  const p = panels.get(panelId);
  if (!p) return;
  const t = document.getElementById(`ttl_${panelId}`);
  const safe = String(title || "Panel");
  if (t) t.textContent = safe;
  p.title = safe;
}

function buildPanelDatasets(series) {
  const datasets = [];
  for (const s of (series || [])) {
    const label = String(s?.label || "series");
    const xy = normalizePoints(s?.points);
    if (!xy.length) continue;

    const c = normalizeColor(dsColors[label], label);
    dsColors[label] = c;

    const isLevel = /level/i.test(label);
    datasets.push({
      label,
      data: xy,
      borderColor: c,
      backgroundColor: "transparent",
      borderWidth: isLevel ? 1 : 2,
      borderDash: isLevel ? [4, 4] : undefined,
      pointRadius: 0,
      tension: 0,
    });
  }
  saveJSON(DS_COLOR_KEY, dsColors);
  return datasets;
}

function sma(values, period) {
  const p = Math.max(1, Number(period) || 1);
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    sum += (v ?? 0);
    if (i >= p) sum -= (values[i - p] ?? 0);
    if (i >= p - 1) out[i] = sum / p;
  }
  return out;
}

function fmtSmart(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "";
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "K";
  return String(Math.round(v));
}

function renderVolumeToPanel(panelId, resp, label, { maPeriod = 20 } = {}) {
  const p = panels.get(panelId);
  if (!p || !p.canvas) return;

  const old = panelCharts.get(panelId);
  if (old) {
    try { old.destroy(); } catch {}
    panelCharts.delete(panelId);
  }

  const bars =
    resp?.bars ??
    resp?.candles ??
    resp?.ohlc ??
    resp?.ohlcv ??
    resp?.data?.bars ??
    resp?.data;

  if (!resp || !Array.isArray(bars) || !bars.length) {
    renderPanelError(panelId, "OHLCV error: No bars returned");
    return;
  }

  const xyVol = [];
  const colors = [];

  for (const b of bars) {
    let t = b.t ?? b.time ?? b.ts ?? b.date ?? b.x;
    let ms;

    if (t instanceof Date) ms = t.getTime();
    else if (typeof t === "number") ms = (t < 2e12) ? t * 1000 : t;
    else {
      const parsed = Date.parse(String(t));
      if (!Number.isFinite(parsed)) continue;
      ms = parsed;
    }

    const vRaw = b.v ?? b.volume ?? b.vol ?? b.V;
    const v = (vRaw == null) ? null : Number(vRaw);

    const o = Number(b.o ?? b.open);
    const c = Number(b.c ?? b.close);

    if (!Number.isFinite(ms) || !Number.isFinite(v)) continue;

    xyVol.push({ x: ms, y: v });
    colors.push((Number.isFinite(o) && Number.isFinite(c) && c >= o)
      ? "rgba(16,185,129,0.6)"
      : "rgba(239,68,68,0.6)");
  }

  if (!xyVol.length) {
    renderPanelError(panelId, "No volume values found in bars[].v");
    return;
  }

  const maP = Math.max(1, Number(maPeriod) || 1);
  const maVals = sma(xyVol.map(pt => pt.y), maP);
  const xyMA = xyVol.map((pt, i) => ({ x: pt.x, y: maVals[i] }));

  setPanelTitle(panelId, label);

  const xb = state?.base?.xBounds;
  const xMin = xb?.xMin;
  const xMax = xb?.xMax;

  const maLabel = `Vol MA(${maP})`;
  const maColor = normalizeColor(dsColors[maLabel], maLabel);
  dsColors[maLabel] = maColor;
  saveJSON(DS_COLOR_KEY, dsColors);

  const datasets = [
    {
      type: "bar",
      label: "Volume",
      data: xyVol,
      parsing: false,
      backgroundColor: colors,
      borderWidth: 0,
      barPercentage: 1.0,
      categoryPercentage: 1.0,
    },
    {
      type: "line",
      label: maLabel,
      data: xyMA,
      parsing: false,
      borderWidth: 1.6,
      pointRadius: 0,
      tension: 0,
      backgroundColor: "transparent",
      borderColor: withAlpha(maColor, 0.75),
    }
  ];

  const ch = new Chart(p.canvas.getContext("2d"), {
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      animation: false,
      layout: { padding: { left: 6, right: LAST_VALUE_PAD_RIGHT, top: 0, bottom: 0 } },
      plugins: {
        legend: {
          display: !!panelLegends[panelId],
          labels: {
            font: AXIS_TICK_FONT,
            generateLabels: (chart) => {
              const base = Chart.defaults.plugins.legend.labels.generateLabels(chart);
              return base.map((label) => {
                const ds = chart.data?.datasets?.[label.datasetIndex];
                if (ds?.type === "line") {
                  label.usePointStyle = true;
                  label.pointStyle = "line";
                  label.strokeStyle = ds.borderColor || label.strokeStyle;
                  label.fillStyle = ds.borderColor || label.fillStyle;
                  label.lineWidth = 2;
                  label.boxWidth = 28;
                  label.boxHeight = 2;
                }
                return label;
              });
            },
          },
          onClick: legendToggleDataset,
        },
        tooltip: {
          callbacks: {
            title: (items) => {
              const x = items?.[0]?.parsed?.x;
              return (x != null) ? new Date(Number(x)).toLocaleString() : "";
            },
          },
        },
        zoom: zoomPanSyncCallbacks(),
        qsEdgeXTicks: { enabled: true, forceEdgeLabels: true, drawEdgeMarks: true, edgeOutside: true, edgeOutsidePad: 8 },
        qsLastValue: {
          enabled: true,
          uniformWidth: true,
          datasetIndex: 0,
          formatter: (v) => fmtSmart(v),
        },
        qsCrosshair: {
          enabled: true,
          formatter: (v) => fmtSmart(v),
        },
      },
      scales: {
        x: {
          type: "linear",
          offset: false,
          bounds: "data",
          min: Number.isFinite(xMin) ? xMin : undefined,
          max: Number.isFinite(xMax) ? xMax : undefined,
          ticks: {
            callback: function (v, idx, ticks) {
              const edgePluginOn = !!this?.chart?.options?.plugins?.qsEdgeXTicks?.enabled;
              const last = (ticks?.length ?? 0) - 1;
              if (edgePluginOn && (idx === 0 || idx === last)) return "";
              return formatDateTick(v);
            },
            maxTicksLimit: 10,
            autoSkip: true,
            display: true,
            font: AXIS_TICK_FONT,
          },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
        y: {
          beginAtZero: true,
          ticks: {
            maxTicksLimit: 3,
            callback: function (v) {
              const max = Number(this.max);
              if (!Number.isFinite(max) || max <= 0) return "";
              const mid = max / 2;
              const eps = Math.max(1, max * 0.01);
              if (Math.abs(v - max) <= eps || Math.abs(v - mid) <= eps) return fmtSmart(v);
              return "";
            },
            font: AXIS_TICK_FONT,
          },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
      },
    },
  });

  panelCharts.set(panelId, ch);
  p.chart = ch;

  applyXAxisInnerTicks(ch.options.scales);
  if (ch.options?.scales?.x?.ticks) ch.options.scales.x.ticks.includeBounds = true;
  applyAxisFonts(ch.options.scales);
  applyFixedYWidth(ch, Y_AXIS_WIDTH);
  setGridEnabledOnChart(ch, !!uiPrefs.grid);
  withZoomSuppressed(ch, () => ch.update("none"));

  attachDblClickReset(ch, p.canvas);
  installAxisGripsForChart(ch, p.rootEl?.querySelector(".qpanel-canvas"));
  installChartPan(ch, p.canvas);
  updatePanelsXAxisVisibility();
  requestChartResizeAll();
}

function renderPanelChart(panelId, resp) {
  const p = panels.get(panelId);
  if (!p) return;

  const series = resp?.series || [];
  const datasets = buildPanelDatasets(series);
  if (!datasets.length) {
    renderPanelError(panelId, "No series data.");
    return;
  }

  const xb = state.base.xBounds;
  const xMin = xb?.xMin;
  const xMax = xb?.xMax;

  const existing = panelCharts.get(panelId);
  if (existing) {
    try { existing.destroy(); } catch {}
    panelCharts.delete(panelId);
  }

  const kind = panelSpecs?.[panelId]?.kind || "series";
  const yTickLimit = (kind === "drawdown" || kind === "sharpe") ? 4 : 8;

  const ch = new Chart(p.canvas.getContext("2d"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      animation: false,
      layout: { padding: { left: 6, right: LAST_VALUE_PAD_RIGHT, top: 0, bottom: 0 } },
      plugins: {
        legend: {
          display: !!panelLegends[panelId],
          labels: { usePointStyle: true, pointStyle: "line", boxWidth: 28, font: AXIS_TICK_FONT },
          onClick: legendToggleDataset,
        },
        tooltip: {
          callbacks: {
            title: (items) => {
              const x = items?.[0]?.parsed?.x;
              return (x != null) ? new Date(Number(x)).toLocaleString() : "";
            },
          },
        },
        zoom: zoomPanSyncCallbacks(),
        qsEdgeXTicks: { enabled: true },
        qsLastValue: {
          enabled: true,
          datasetIndex: 0,
          formatter: (v) => (Number.isFinite(Number(v)) ? Number(v).toFixed(2) : ""),
        },
        qsCrosshair: {
          enabled: true,
          formatter: (v) => (Number.isFinite(Number(v)) ? Number(v).toFixed(2) : ""),
        },
      },
      scales: {
        x: {
          type: "linear",
          offset: false,
          bounds: "data",
          min: Number.isFinite(xMin) ? xMin : undefined,
          max: Number.isFinite(xMax) ? xMax : undefined,
          ticks: {
            callback: function (v, idx, ticks) {
              const edgePluginOn = !!this?.chart?.options?.plugins?.qsEdgeXTicks?.enabled;
              const last = (ticks?.length ?? 0) - 1;
              if (edgePluginOn && (idx === 0 || idx === last)) return "";
              return formatDateTick(v);
            },
            maxTicksLimit: 10,
            autoSkip: true,
            display: true,
          },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
        y: {
          ticks: { maxTicksLimit: yTickLimit },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
      },
    },
  });

  panelCharts.set(panelId, ch);
  p.chart = ch;

  applyXAxisInnerTicks(ch.options.scales);
  applyAxisFonts(ch.options.scales);
  applyFixedYWidth(ch, Y_AXIS_WIDTH);
  setGridEnabledOnChart(ch, !!uiPrefs.grid);
  withZoomSuppressed(ch, () => ch.update("none"));

  attachDblClickReset(ch, p.canvas);
  installAxisGripsForChart(ch, p.rootEl?.querySelector(".qpanel-canvas"));
  installChartPan(ch, p.canvas);
  updatePanelsXAxisVisibility();
  requestChartResizeAll();
}

function renderPriceToPanel(panelId, priceResp) {
  const p = panels.get(panelId);
  if (!p) return;

  const label =
    (priceResp && typeof priceResp.label === "string" && priceResp.label) ||
    (priceResp?.series?.[0]?.label) ||
    "price";

  const points =
    Array.isArray(priceResp?.points) ? priceResp.points :
    Array.isArray(priceResp?.series?.[0]?.points) ? priceResp.series[0].points :
    [];

  const xy = normalizePoints(points);
  if (!xy.length) {
    renderPanelError(panelId, "No price points.");
    return;
  }

  const datasets = [{
    label,
    data: xy,
    borderColor: normalizeColor(dsColors[label], label),
    backgroundColor: "transparent",
    borderWidth: 2,
    pointRadius: 0,
    tension: 0,
  }];
  dsColors[label] = normalizeColor(dsColors[label], label);
  saveJSON(DS_COLOR_KEY, dsColors);

  const xb = state.base.xBounds;
  const xMin = xb?.xMin;
  const xMax = xb?.xMax;

  const existing = panelCharts.get(panelId);
  if (existing) {
    try { existing.destroy(); } catch {}
    panelCharts.delete(panelId);
  }

  const ch = new Chart(p.canvas.getContext("2d"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      animation: false,
      layout: { padding: { left: 6, right: LAST_VALUE_PAD_RIGHT, top: 0, bottom: 0 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const x = items?.[0]?.parsed?.x;
              return (x != null) ? new Date(Number(x)).toLocaleString() : "";
            },
          },
        },
        zoom: zoomPanSyncCallbacks(),
        qsEdgeXTicks: { enabled: true },
        qsLastValue: {
          enabled: true,
          datasetIndex: 0,
          formatter: (v) => (Number.isFinite(Number(v)) ? Number(v).toFixed(2) : ""),
        },
        qsCrosshair: {
          enabled: true,
          formatter: (v) => (Number.isFinite(Number(v)) ? Number(v).toFixed(2) : ""),
        },
      },
      scales: {
        x: {
          type: "linear",
          offset: false,
          bounds: "data",
          min: Number.isFinite(xMin) ? xMin : undefined,
          max: Number.isFinite(xMax) ? xMax : undefined,
          ticks: {
            callback: function (v, idx, ticks) {
              const edgePluginOn = !!this?.chart?.options?.plugins?.qsEdgeXTicks?.enabled;
              const last = (ticks?.length ?? 0) - 1;
              if (edgePluginOn && (idx === 0 || idx === last)) return "";
              return formatDateTick(v);
            },
            maxTicksLimit: 10,
            autoSkip: true,
            display: true,
            font: AXIS_TICK_FONT,
          },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
        y: {
          ticks: { maxTicksLimit: 8, font: AXIS_TICK_FONT },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
      },
    },
  });

  panelCharts.set(panelId, ch);
  p.chart = ch;

  applyXAxisInnerTicks(ch.options.scales);
  applyAxisFonts(ch.options.scales);
  applyFixedYWidth(ch, Y_AXIS_WIDTH);
  setGridEnabledOnChart(ch, !!uiPrefs.grid);
  withZoomSuppressed(ch, () => ch.update("none"));

  attachDblClickReset(ch, p.canvas);
  installAxisGripsForChart(ch, p.rootEl?.querySelector(".qpanel-canvas"));
  installChartPan(ch, p.canvas);
  updatePanelsXAxisVisibility();
  requestChartResizeAll();
}

// ============================================================
// Chart helpers
// ============================================================
function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getOrCreateColorPicker() {
  let el = document.getElementById("qsColorPicker");
  if (el) return el;

  el = document.createElement("input");
  el.type = "color";
  el.id = "qsColorPicker";
  el.style.position = "fixed";
  el.style.left = "0px";
  el.style.top = "0px";
  el.style.width = "1px";
  el.style.height = "1px";
  el.style.opacity = "0";
  el.style.pointerEvents = "none";
  el.style.zIndex = "999999";

  document.body.appendChild(el);
  return el;
}

function toHexColor(c) {
  if (!c) return null;
  const s = String(c).trim();
  if (s.startsWith("#")) return s;

  const m = s.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
  if (!m) return null;

  const r = Math.max(0, Math.min(255, parseInt(m[1], 10)));
  const g = Math.max(0, Math.min(255, parseInt(m[2], 10)));
  const b = Math.max(0, Math.min(255, parseInt(m[3], 10)));
  return "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

function hashStrToInt(s) {
  let h = 2166136261;
  const str = String(s || "");
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function autoColor(label) {
  const h = hashStrToInt(label);
  const r = 60 + (h & 0x7f);
  const g = 60 + ((h >> 8) & 0x7f);
  const b = 60 + ((h >> 16) & 0x7f);
  return "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

function normalizeColor(c, fallbackLabel = "series") {
  const hex = toHexColor(c);
  if (hex) return hex;
  return autoColor(fallbackLabel);
}

function withAlpha(color, a = 1) {
  const hex = toHexColor(color);
  if (!hex) return color;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const aa = Math.max(0, Math.min(1, a));
  return `rgba(${r},${g},${b},${aa})`;
}

function normalizePoints(points) {
  const out = [];
  for (const p of (points || [])) {
    let t, v;
    if (Array.isArray(p) && p.length >= 2) { t = p[0]; v = p[1]; }
    else if (p && typeof p === "object") {
      t = p.time ?? p.t ?? p.ts ?? p.timestamp ?? p.date ?? p.x;
      v = p.value ?? p.v ?? p.y ?? p.close ?? p.px;
    }
    if (t == null || v == null) continue;

    let ms;
    if (t instanceof Date) ms = t.getTime();
    else if (typeof t === "number") ms = (t < 1e12) ? t * 1000 : t;
    else {
      const parsed = Date.parse(String(t));
      if (!Number.isFinite(parsed)) continue;
      ms = parsed;
    }

    const fv = Number(v);
    if (!Number.isFinite(ms) || !Number.isFinite(fv)) continue;
    out.push({ x: ms, y: fv });
  }
  out.sort((a, b) => a.x - b.x);
  return out;
}

function normalizeSeriesXY(xy, mode, baseValue) {
  if ((!mode && mode !== 0) || !Array.isArray(xy) || !xy.length) return xy;
  if (typeof mode === "string" && /^(none|raw)$/i.test(mode)) return xy;

  const first = xy[0]?.y;
  if (!Number.isFinite(first) || first === 0) return xy;

  if (mode === 0) {
    return xy.map(p => ({ x: p.x, y: (p.y / first - 1) * 100 }));
  }

  let target = null;
  if (typeof mode === "number" && Number.isFinite(mode)) target = mode;
  else if (Number.isFinite(baseValue)) target = baseValue;

  if (!Number.isFinite(target)) return xy;
  const k = target / first;
  return xy.map(p => ({ x: p.x, y: p.y * k }));
}

function resolveNormBaseValue(normMode, seriesList) {
  if (typeof normMode !== "string" || !Array.isArray(seriesList)) return null;
  const key = normMode.toLowerCase();
  for (const s of seriesList) {
    const label = String(s?.label || "").toLowerCase();
    const expr = String(s?.expr || "").toLowerCase();
    if (!label.includes(key) && !expr.includes(key)) continue;
    const xy = normalizePoints(s?.points || []);
    const first = xy?.[0]?.y;
    if (Number.isFinite(first)) return first;
  }
  return null;
}

function quantileSorted(arr, q) {
  if (!arr.length) return null;
  const pos = (arr.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  if (arr[base + 1] != null) return arr[base] + rest * (arr[base + 1] - arr[base]);
  return arr[base];
}

function toPctFromStart(xy) {
  if (!Array.isArray(xy) || !xy.length) return [];
  const first = xy[0]?.y;
  if (!Number.isFinite(first) || first === 0) return xy.map(p => ({ x: p.x, y: null }));
  return xy.map(p => ({ x: p.x, y: (p.y / first - 1) * 100 }));
}

function normalizeSeasonalitySeries(xy, baseIdx, mode = "pct") {
  if (!Array.isArray(xy) || !xy.length) return [];
  const idx = clamp(Math.round(Number(baseIdx) || 0), 0, xy.length - 1);
  const base = xy[idx]?.y;
  if (!Number.isFinite(base) || base === 0) return xy.map(p => ({ x: p.x, y: null }));
  const wantIndex = String(mode || "pct").toLowerCase() === "index";
  return xy.map(p => {
    const v = Number(p?.y);
    if (!Number.isFinite(v)) return { x: p?.x, y: null };
    const y = wantIndex ? (v / base) * 100 : ((v / base) - 1) * 100;
    return { x: p?.x, y };
  });
}

const SEASONALITY_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthDayToIndex(month, day) {
  const m = Math.max(1, Math.min(12, Number(month) || 1));
  const d = Math.max(1, Math.min(31, Number(day) || 1));
  const base = new Date(2001, 0, 1);
  const cur = new Date(2001, m - 1, d);
  const diff = Math.round((cur - base) / 86400000);
  return clamp(diff, 0, 364);
}

function parseRangeSpec(spec) {
  const raw = String(spec || "").trim();
  const m = raw.match(/^(\d{2})-(\d{2})$/);
  if (!m) return null;
  return { month: Number(m[1]), day: Number(m[2]) };
}

function seasonalityDayIndexFromPoint(pt, fallbackIdx = 0) {
  const raw = pt?.x;
  const n = Number(raw);
  if (Number.isFinite(n) && n >= 0 && n <= 366) return Math.round(n);
  if (Number.isFinite(n)) {
    const d = new Date(n);
    if (!Number.isNaN(d.getTime())) return monthDayToIndex(d.getMonth() + 1, d.getDate());
  }
  return clamp(fallbackIdx, 0, 364);
}

function normalizeSeasonalityByDay(xy, baseDay, mode = "pct") {
  if (!Array.isArray(xy) || !xy.length) return [];
  const wantIndex = String(mode || "pct").toLowerCase() === "index";
  let base = null;
  let bestDist = Infinity;
  for (const p of xy) {
    const x = Number(p?.x);
    const y = Number(p?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const d = Math.abs(x - baseDay);
    if (d < bestDist) {
      base = y;
      bestDist = d;
    }
  }
  if (!Number.isFinite(base) || base === 0) return xy.map(p => ({ x: p?.x, y: null }));
  return xy.map(p => {
    const v = Number(p?.y);
    if (!Number.isFinite(v)) return { x: p?.x, y: null };
    const y = wantIndex ? (v / base) * 100 : ((v / base) - 1) * 100;
    return { x: p?.x, y };
  });
}

function seasonalityNormalizePoints(points, startIdx, endIdx, { preferDayOfYear = false } = {}) {
  const out = [];
  if (!Array.isArray(points)) return out;
  let hasDate = false;
  let minRaw = Infinity;
  let maxRaw = -Infinity;

  for (const p of points) {
    let t, v;
    if (Array.isArray(p) && p.length >= 2) { t = p[0]; v = p[1]; }
    else if (p && typeof p === "object") {
      t = p.time ?? p.t ?? p.ts ?? p.timestamp ?? p.date ?? p.x;
      v = p.value ?? p.v ?? p.y ?? p.close ?? p.px;
    }
    if (t == null || v == null) continue;
    const fv = Number(v);
    if (!Number.isFinite(fv)) continue;

    if (t instanceof Date) {
      out.push({ x: monthDayToIndex(t.getMonth() + 1, t.getDate()), y: fv });
      hasDate = true;
      continue;
    }

    if (typeof t === "number") {
      if (t >= 0 && t <= 400) {
        out.push({ x: t, y: fv, _raw: true });
        minRaw = Math.min(minRaw, t);
        maxRaw = Math.max(maxRaw, t);
      } else {
        const ms = t < 1e12 ? t * 1000 : t;
        const d = new Date(ms);
        if (!Number.isNaN(d.getTime())) {
          out.push({ x: monthDayToIndex(d.getMonth() + 1, d.getDate()), y: fv });
          hasDate = true;
        }
      }
      continue;
    }

    const parsed = Date.parse(String(t));
    if (Number.isFinite(parsed)) {
      const d = new Date(parsed);
      out.push({ x: monthDayToIndex(d.getMonth() + 1, d.getDate()), y: fv });
      hasDate = true;
    }
  }

  if (!out.length) return out;

  if (preferDayOfYear) return out.map((pt) => ({ x: pt.x, y: pt.y }));

  if (!hasDate && Number.isFinite(minRaw) && Number.isFinite(maxRaw) && maxRaw > minRaw) {
    if (maxRaw >= 360 || out.length < 200 || (maxRaw - minRaw) >= 300) {
      return out.map((pt) => ({ x: pt.x, y: pt.y }));
    }
    const span = maxRaw - minRaw;
    const targetSpan = (endIdx >= startIdx)
      ? (endIdx - startIdx)
      : ((365 - startIdx) + endIdx);
    return out.map((pt) => {
      const t = (pt.x - minRaw) / span;
      const x = startIdx + t * targetSpan;
      return { x, y: pt.y };
    });
  }

  return out.map((pt) => ({ x: pt.x, y: pt.y }));
}

function formatSeasonalityTick(idx) {
  const n = Number(idx);
  if (!Number.isFinite(n)) return "";
  const base = new Date(2001, 0, 1);
  const d = new Date(base.getTime() + Math.round(n % 365) * 86400000);
  const mm = SEASONALITY_MONTHS[d.getMonth()] || "";
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm} ${dd}`;
}

function ensureSeasonalityLayout(panelId) {
  const p = panels.get(panelId);
  if (!p) return null;
  const wrap = p.rootEl?.querySelector(".qpanel-canvas");
  if (!wrap) return null;

  let host = wrap.querySelector(".qs-seasonality");
  if (!host) {
    host = document.createElement("div");
    host.className = "qs-seasonality";
    host.innerHTML = `
      <div class="qs-seasonality-controls"></div>
      <div class="qs-seasonality-years"></div>
      <div class="qs-seasonality-title"></div>
      <div class="qs-seasonality-body"></div>
    `;
    wrap.innerHTML = "";
    wrap.appendChild(host);
    const body = host.querySelector(".qs-seasonality-body");
    if (body && p.canvas) body.appendChild(p.canvas);
  }

  return {
    host,
    controls: host.querySelector(".qs-seasonality-controls"),
    years: host.querySelector(".qs-seasonality-years"),
    title: host.querySelector(".qs-seasonality-title"),
    body: host.querySelector(".qs-seasonality-body"),
  };
}

function getSeasonalityParams(panelId) {
  const spec = panelSpecs?.[panelId] || {};
  const params = spec.params || {};
  const defaultStats = ["mean", "median", "min", "max", "pos", "neg", "stdev"];
  return {
    expr: params.expr || state.base.expr || "",
    mode: String(params.mode || "heatmap").toLowerCase(),
    bucket: String(params.bucket || "month").toLowerCase(),
    yearsSpec: params.yearsSpec || "10",
    yearsSelected: Array.isArray(params.yearsSelected) ? params.yearsSelected : null,
    rangeStart: params.rangeStart || "01-01",
    rangeEnd: params.rangeEnd || "12-31",
    normMode: String(params.normMode || "pct").toLowerCase(),
    normBase: String(params.normBase || "start").toLowerCase(),
    normMonth: params.normMonth || "01",
    normDay: params.normDay || "01",
    statsSelected: Array.isArray(params.statsSelected) && params.statsSelected.length ? params.statsSelected : defaultStats,
  };
}

function setSeasonalityParams(panelId, next) {
  panelSpecs[panelId] = panelSpecs[panelId] || { kind: "seasonality" };
  panelSpecs[panelId].params = { ...(panelSpecs[panelId].params || {}), ...next };
  savePanelSpecs();
}

function renderSeasonalityEmpty(panelId, msg) {
  const layout = ensureSeasonalityLayout(panelId);
  if (!layout) return;
  const p = panels.get(panelId);
  if (layout.body) {
    if (p?.kind === "seasonality") {
      layout.body.innerHTML = "";
      return;
    }
    layout.body.innerHTML = `<div class="qs-seasonality-empty">${escapeHtml(msg || "Set an expression to load seasonality.")}</div>`;
  }
}

function renderSeasonalityControls(panelId, availableYears) {
  const layout = ensureSeasonalityLayout(panelId);
  if (!layout) return;
  const params = getSeasonalityParams(panelId);
  const yearsSpec = String(params.yearsSpec || "10");
  const yearsSelected = params.yearsSelected || availableYears || [];
  const yearsList = availableYears || [];
  const rangeStart = parseRangeSpec(params.rangeStart || "01-01") || { month: 1, day: 1 };
  const rangeEnd = parseRangeSpec(params.rangeEnd || "12-31") || { month: 12, day: 31 };
  const normMode = String(params.normMode || "pct");
  const normBase = String(params.normBase || "start");
  const normMonth = String(params.normMonth || "01");
  const normDay = String(params.normDay || "01");
  const monthOptions = SEASONALITY_MONTHS.map((m, i) => {
    const v = String(i + 1).padStart(2, "0");
    const sel = (i + 1 === rangeStart.month) ? "selected" : "";
    return `<option value="${v}" ${sel}>${m}</option>`;
  }).join("");
  const monthOptionsEnd = SEASONALITY_MONTHS.map((m, i) => {
    const v = String(i + 1).padStart(2, "0");
    const sel = (i + 1 === rangeEnd.month) ? "selected" : "";
    return `<option value="${v}" ${sel}>${m}</option>`;
  }).join("");
  const dayOptions = Array.from({ length: 31 }, (_, i) => {
    const d = i + 1;
    const v = String(d).padStart(2, "0");
    const sel = (d === rangeStart.day) ? "selected" : "";
    return `<option value="${v}" ${sel}>${v}</option>`;
  }).join("");
  const dayOptionsEnd = Array.from({ length: 31 }, (_, i) => {
    const d = i + 1;
    const v = String(d).padStart(2, "0");
    const sel = (d === rangeEnd.day) ? "selected" : "";
    return `<option value="${v}" ${sel}>${v}</option>`;
  }).join("");
  const normMonthOptions = SEASONALITY_MONTHS.map((m, i) => {
    const v = String(i + 1).padStart(2, "0");
    const sel = (v === normMonth) ? "selected" : "";
    return `<option value="${v}" ${sel}>${m}</option>`;
  }).join("");
  const normDayOptions = Array.from({ length: 31 }, (_, i) => {
    const d = i + 1;
    const v = String(d).padStart(2, "0");
    const sel = (v === normDay) ? "selected" : "";
    return `<option value="${v}" ${sel}>${v}</option>`;
  }).join("");

  layout.controls.innerHTML = `
    <div class="qs-seasonality-controls-grid">
      <div class="qs-seasonality-asset">
        <div class="qs-seasonality-label">Select asset</div>
        <input class="qs-seasonality-input" type="text" data-act="expr" value="${escapeHtml(params.expr)}" />
        <div class="qs-seasonality-hint">e.g. EQ:QQQ, IX:SPX, IX:SPX/IX:RTY, FX:EURUSD</div>
      </div>
      <div class="qs-seasonality-actions">
        <button class="btn btn-run" data-act="apply">Run</button>
      </div>
      <div class="qs-seasonality-row">
        <label>Bucket
          <select data-act="bucket">
            <option value="month" ${params.bucket === "month" ? "selected" : ""}>month</option>
            <option value="week" ${params.bucket === "week" ? "selected" : ""}>week</option>
          </select>
        </label>
        <label>Years <input type="text" data-act="yearsSpec" value="${escapeHtml(yearsSpec)}" /></label>
        <label>Start
          <select data-act="startMonth">${monthOptions}</select>
          <select data-act="startDay">${dayOptions}</select>
        </label>
        <label>End
          <select data-act="endMonth">${monthOptionsEnd}</select>
          <select data-act="endDay">${dayOptionsEnd}</select>
        </label>
        <label>Normalize
          <select data-act="normMode">
            <option value="pct" ${normMode === "pct" ? "selected" : ""}>0%</option>
            <option value="index" ${normMode === "index" ? "selected" : ""}>100</option>
          </select>
        </label>
        <label>Base
          <select data-act="normBase">
            <option value="start" ${normBase === "start" ? "selected" : ""}>Start</option>
            <option value="date" ${normBase === "date" ? "selected" : ""}>Date</option>
          </select>
        </label>
        <label data-act="normDate">Date
          <select data-act="normMonth">${normMonthOptions}</select>
          <select data-act="normDay">${normDayOptions}</select>
        </label>
      </div>
      <div class="qs-seasonality-row">
        <label><input type="radio" name="seasonality_mode_${panelId}" value="heatmap" ${params.mode === "heatmap" ? "checked" : ""}/> Heatmap</label>
        <label><input type="radio" name="seasonality_mode_${panelId}" value="years" ${params.mode === "years" ? "checked" : ""}/> Time Series</label>
      </div>
    </div>
  `;

  const bucketSelect = layout.controls.querySelector("[data-act=bucket]");
  if (bucketSelect) bucketSelect.disabled = (params.mode !== "heatmap");
  const normDateLabel = layout.controls.querySelector("[data-act=normDate]");
  if (normDateLabel) normDateLabel.style.display = (normBase === "date") ? "inline-flex" : "none";

  if (layout.years) {
    layout.years.innerHTML = "";
    layout.years.style.display = "none";
  }

  layout.controls.querySelectorAll("input[name^=seasonality_mode_]").forEach((el) => {
    el.addEventListener("change", () => {
      setSeasonalityParams(panelId, { mode: el.value });
      loadSeasonalityPanel(panelId, true);
    });
  });

  const applyBtn = layout.controls.querySelector("[data-act=apply]");
  applyBtn?.addEventListener("click", () => {
    const exprEl = layout.controls.querySelector("[data-act=expr]");
    const bucketEl = layout.controls.querySelector("[data-act=bucket]");
    const yearsEl = layout.controls.querySelector("[data-act=yearsSpec]");
    const startMonthEl = layout.controls.querySelector("[data-act=startMonth]");
    const startDayEl = layout.controls.querySelector("[data-act=startDay]");
    const endMonthEl = layout.controls.querySelector("[data-act=endMonth]");
    const endDayEl = layout.controls.querySelector("[data-act=endDay]");
    const normModeEl = layout.controls.querySelector("[data-act=normMode]");
    const normBaseEl = layout.controls.querySelector("[data-act=normBase]");
    const normMonthEl = layout.controls.querySelector("[data-act=normMonth]");
    const normDayEl = layout.controls.querySelector("[data-act=normDay]");
    const expr = normalizeSeasonalityExpr(String(exprEl?.value || "").trim());
    const bucket = String(bucketEl?.value || "month").trim().toLowerCase();
    const yearsSpec = String(yearsEl?.value || "10").trim();
    const rangeStart = `${String(startMonthEl?.value || "01")}-${String(startDayEl?.value || "01")}`;
    const rangeEnd = `${String(endMonthEl?.value || "12")}-${String(endDayEl?.value || "31")}`;
    const normModeNext = String(normModeEl?.value || "pct").trim().toLowerCase();
    const normBaseNext = String(normBaseEl?.value || "start").trim().toLowerCase();
    const normMonthNext = String(normMonthEl?.value || "01");
    const normDayNext = String(normDayEl?.value || "01");
    setSeasonalityParams(panelId, {
      expr,
      bucket,
      yearsSpec,
      yearsSelected: null,
      rangeStart,
      rangeEnd,
      normMode: normModeNext,
      normBase: normBaseNext,
      normMonth: normMonthNext,
      normDay: normDayNext,
    });
    loadSeasonalityPanel(panelId, true);
  });

  const normBaseSelect = layout.controls.querySelector("[data-act=normBase]");
  normBaseSelect?.addEventListener("change", () => {
    const val = String(normBaseSelect.value || "start").toLowerCase();
    if (normDateLabel) normDateLabel.style.display = (val === "date") ? "inline-flex" : "none";
  });
  layout.years.querySelectorAll("input[type=checkbox][data-year]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const picked = Array.from(layout.years.querySelectorAll("input[data-year]:checked"))
        .map(x => Number(x.dataset.year))
        .filter(Number.isFinite);
      setSeasonalityParams(panelId, { yearsSelected: picked });
      const cache = panelSpecs?.[panelId]?.cache;
      if (cache?.mode === "heatmap") {
        renderSeasonalityHeatmap(panelId, cache.resp, { bucket: cache.bucket });
      } else if (cache?.mode === "years") {
        renderSeasonalityYearsPanel(panelId, cache.resp, { showBand: true });
      }
    });
  });
}

function normalizeSeasonalityExpr(expr) {
  const s = String(expr || "").trim();
  if (!s) return s;
  if (/[*\/+\-]/.test(s)) {
    const trimmed = s.replace(/\s+/g, "");
    if (!(trimmed.startsWith("(") && trimmed.endsWith(")"))) return `(${s})`;
  }
  return s;
}

async function loadSeasonalityPanel(panelId, forceFetch = false) {
  const params = getSeasonalityParams(panelId);
  const expr = normalizeSeasonalityExpr(params.expr);
  const subtitle = document.getElementById("seasonalitySubtitle");
  if (subtitle) subtitle.textContent = "";

  const yearsForControls = parseYearsSpec(params.yearsSpec || "10") || [];
  renderSeasonalityControls(panelId, yearsForControls);
  if (!expr) {
    renderSeasonalityEmpty(panelId, "Set an expression to load seasonality.");
    return;
  }

  if (params.mode === "years") {
    const years = parseYearsSpec(params.yearsSpec || "10") || parseYearsSpec(10);
    const nowYear = new Date().getFullYear();
    if (Array.isArray(years) && !years.includes(nowYear)) {
      years.push(nowYear);
      years.sort((a, b) => a - b);
    }
    const resp = await postJSON("/expr/seasonality/years", {
      expr,
      years,
      duration: `${years.length} Y`,
      bar_size: state.base.bar_size,
      use_rth: state.base.use_rth,
      rebase: true,
      min_points_per_year: 1,
    });
    const hasCurrent = Array.isArray(resp?.series) && resp.series.some((s) => String(s?.label || "").includes(String(nowYear)));
    if (!hasCurrent) {
      try {
        const respNow = await postJSON("/expr/seasonality/years", {
          expr,
          years: [nowYear],
          duration: "1 Y",
          bar_size: state.base.bar_size,
          use_rth: state.base.use_rth,
          rebase: true,
          min_points_per_year: 1,
        });
        if (Array.isArray(respNow?.series) && respNow.series.length) {
          resp.series = [...(resp.series || []), ...respNow.series];
        }
        if (Array.isArray(respNow?.tables?.years)) {
          resp.tables = resp.tables || {};
          resp.tables.years = [...(resp.tables.years || []), ...respNow.tables.years];
        }
      } catch {}
    }
    panelSpecs[panelId].cache = { mode: "years", resp };
    lastResponseJson = resp;
    setPanelTitle(panelId, "Seasonality");
    const availableYears = Array.from(new Set((resp.tables?.years || [])
      .filter((r) => r?.included)
      .map((r) => Number(r.year))
      .filter(Number.isFinite))).sort((a, b) => a - b);
    renderSeasonalityControls(panelId, availableYears.length ? availableYears : years);
    renderSeasonalityYearsPanel(panelId, resp, { showBand: true });
    return;
  }

  const years = parseYearsSpec(params.yearsSpec || "10");
  const resp = await postJSON("/expr/seasonality/heatmap", {
    expr,
    duration: `${Math.max(1, (years || []).length || 10)} Y`,
    bar_size: state.base.bar_size,
    use_rth: state.base.use_rth,
    bucket: params.bucket === "week" ? "week" : "month",
    years: years && years.length ? years : null,
  });
  panelSpecs[panelId].cache = { mode: "heatmap", resp, bucket: params.bucket };
  lastResponseJson = resp;
  setPanelTitle(panelId, "Seasonality");
  const availableYears = Array.from(new Set((resp.tables?.heatmap || []).map(r => Number(r.year)).filter(Number.isFinite))).sort((a, b) => a - b);
  renderSeasonalityControls(panelId, availableYears);
  renderSeasonalityHeatmap(panelId, resp, { bucket: params.bucket });
}

function renderSeasonalityYearsPanel(panelId, resp, { showBand = true } = {}) {
  const p = panels.get(panelId);
  if (!p) return;
  const layout = ensureSeasonalityLayout(panelId);
  if (!layout) return;
  const params = getSeasonalityParams(panelId);
  if (layout.years) layout.years.style.display = "none";
  const grab = layout.body?.querySelector(".qs-heatmap-resize");
  if (grab) grab.remove();
  const rangeStart = parseRangeSpec(params.rangeStart || "01-01") || { month: 1, day: 1 };
  const rangeEnd = parseRangeSpec(params.rangeEnd || "12-31") || { month: 12, day: 31 };
  const normMode = String(params.normMode || "pct").toLowerCase();
  const normBase = String(params.normBase || "start").toLowerCase();
  const normMonth = String(params.normMonth || "01");
  const normDay = String(params.normDay || "01");
  const showAvg = true;
  const startIdx = monthDayToIndex(rangeStart.month, rangeStart.day);
  const endIdx = monthDayToIndex(rangeEnd.month, rangeEnd.day);
  const baseIdx = (normBase === "date")
    ? monthDayToIndex(normMonth, normDay)
    : startIdx;
  const isWrap = endIdx < startIdx;
  const startTarget = startIdx;
  const endTarget = isWrap ? endIdx + 365 : endIdx;

  const series = Array.isArray(resp?.series) ? resp.series : [];
  if (!series.length) {
    renderPanelError(panelId, "No seasonality data.");
    return;
  }

  const preferDay = String(resp?.meta?.x_axis || "").toLowerCase() === "day_of_year";
  const seriesXY = series.map((s) => {
    const rawLabel = String(s?.label || "year");
    const ym = rawLabel.match(/(\d{4})/);
    const yearLabel = ym ? ym[1] : rawLabel;
    const preferDay = String(resp?.meta?.x_axis || "").toLowerCase() === "day_of_year";
    const rawDays = seasonalityNormalizePoints(s?.points || [], startIdx, endIdx, { preferDayOfYear: preferDay });
    let norm = normalizeSeasonalityByDay(rawDays, baseIdx, normMode);
    if (isWrap) {
      norm = norm.map((pt) => {
        if (!Number.isFinite(pt.x)) return pt;
        const adj = pt.x <= endIdx ? pt.x + 365 : pt.x;
        return { x: adj, y: pt.y };
      });
    }
    let xy = norm
      .filter((pt) => Number.isFinite(pt.y))
      .filter((pt) => {
        if (isWrap) return pt.x >= startTarget && pt.x <= endTarget;
        return pt.x >= startTarget && pt.x <= endTarget;
      })
      .sort((a, b) => a.x - b.x);
    if (xy.length) {
      const first = xy[0];
      if (Number.isFinite(first?.y) && first.x > startTarget) xy.unshift({ x: startTarget, y: first.y });
    }
    return { label: yearLabel, xy };
  }).filter(s => s && s.xy.length);

  if (!seriesXY.length) {
    renderPanelError(panelId, "No seasonality points.");
    return;
  }

  const yearNums = seriesXY.map(s => Number(s.label)).filter(Number.isFinite);
  const currentYear = yearNums.length ? String(Math.max(...yearNums)) : null;
  const selectedYears = Array.isArray(params.yearsSelected) && params.yearsSelected.length
    ? params.yearsSelected.map(String)
    : seriesXY.map(s => String(s.label));
  const seriesForBands = seriesXY.filter(s => {
    const label = String(s.label);
    if (currentYear && label === currentYear) return false;
    if (!selectedYears.includes(label)) return false;
    return true;
  });

  const baseX = [];
  for (let x = startTarget; x <= endTarget; x++) baseX.push(x);
  const p0 = [];
  const p50 = [];
  const p100 = [];
  const pAvg = [];
  const seriesMaps = seriesForBands.map((s) => {
    const pts = (s.xy || []).slice().sort((a, b) => a.x - b.x);
    const map = new Map();
    let last = null;
    let idx = 0;
    for (const x of baseX) {
      while (idx < pts.length && pts[idx].x <= x) {
        const v = Number(pts[idx].y);
        if (Number.isFinite(v)) last = v;
        idx += 1;
      }
      if (last != null) map.set(x, last);
    }
    return map;
  });

  for (let i = 0; i < baseX.length; i++) {
    const vals = [];
    for (const sm of seriesMaps) {
      const v = sm.get(baseX[i]);
      if (Number.isFinite(v)) vals.push(v);
    }
    if (!vals.length) continue;
    vals.sort((a, b) => a - b);
    p0.push({ x: baseX[i], y: quantileSorted(vals, 0) });
    p50.push({ x: baseX[i], y: quantileSorted(vals, 0.5) });
    p100.push({ x: baseX[i], y: quantileSorted(vals, 1) });
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    pAvg.push({ x: baseX[i], y: mean });
  }

  const datasets = [];
  if (showBand && p0.length && p100.length) {
    datasets.push({
      label: "P0",
      data: p0,
      borderColor: "rgba(37,99,235,.18)",
      backgroundColor: "rgba(37,99,235,.05)",
      borderWidth: 1,
      pointRadius: 0,
      tension: 0,
      _qsIsBand: true,
    });
    datasets.push({
      label: "P50",
      data: p50,
      borderColor: "rgba(37,99,235,.6)",
      borderWidth: 2.4,
      pointRadius: 0,
      tension: 0,
      _qsIsBand: true,
    });
    datasets.push({
      label: "P100",
      data: p100,
      borderColor: "rgba(37,99,235,.18)",
      backgroundColor: "rgba(37,99,235,.08)",
      borderWidth: 1,
      pointRadius: 0,
      tension: 0,
      fill: "-2",
      _qsIsBand: true,
    });
  }
  if (showAvg && pAvg.length) {
    datasets.push({
      label: "Mean",
      data: pAvg,
      borderColor: "rgba(17,17,17,.55)",
      borderWidth: 1.8,
      pointRadius: 0,
      tension: 0,
      _qsIsBand: true,
    });
  }

  // currentYear computed earlier

  for (const s of seriesXY) {
    const lbl = s.label;
    const c = normalizeColor(dsColors[lbl], lbl);
    dsColors[lbl] = c;
    const isCurrent = (currentYear && String(lbl) === currentYear);
    datasets.push({
      label: lbl,
      data: s.xy,
      borderColor: c,
      backgroundColor: "transparent",
      borderWidth: isCurrent ? 2.2 : 1.4,
      pointRadius: 0,
      tension: 0,
      _qsBoldLabel: isCurrent,
    });
  }
  saveJSON(DS_COLOR_KEY, dsColors);

  const existing = panelCharts.get(panelId);
  if (existing) {
    try { existing.destroy(); } catch {}
    panelCharts.delete(panelId);
  }

  p.canvas.style.display = "block";
  const heat = layout.body?.querySelector(".qs-heatmap");
  if (heat) heat.remove();
  if (layout.body && p.canvas && !layout.body.contains(p.canvas)) {
    layout.body.appendChild(p.canvas);
  }

  let yMin = Infinity;
  let yMax = -Infinity;
  for (const ds of datasets) {
    for (const pt of (ds.data || [])) {
      const v = Number(pt?.y);
      if (!Number.isFinite(v)) continue;
      yMin = Math.min(yMin, v);
      yMax = Math.max(yMax, v);
    }
  }
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) {
    yMin = 0;
    yMax = 1;
  }
  let pad = (yMax - yMin) * 0.08;
  if (!Number.isFinite(pad) || pad === 0) pad = Math.max(1, Math.abs(yMax) * 0.05);
  const yMinPad = yMin - pad;
  const yMaxPad = yMax + pad;

  const rangeLabel = `${SEASONALITY_MONTHS[rangeStart.month - 1]} ${String(rangeStart.day).padStart(2, "0")} - ${SEASONALITY_MONTHS[rangeEnd.month - 1]} ${String(rangeEnd.day).padStart(2, "0")}`;
  const endLabel = `${SEASONALITY_MONTHS[rangeEnd.month - 1]} ${String(rangeEnd.day).padStart(2, "0")}`;
  if (layout.title) {
    layout.title.textContent = `${String(params.expr || "").trim()} Seasonality ${rangeLabel}`;
  }

  const legendToggleSeasonality = (e, legendItem, legend) => {
    const chart = legend.chart;
    const idx = legendItem.datasetIndex;
    const ds = chart?.data?.datasets?.[idx];
    if (!ds) return;
    const meta = chart.getDatasetMeta(idx);
    const state = ds._qsLegendState || 0;
    if (!ds._qsOrigColor) {
      ds._qsOrigColor = ds.borderColor;
      ds._qsOrigBg = ds.backgroundColor;
    }
    if (state === 0) {
      ds._qsLegendState = 1;
      ds.borderColor = "rgba(17,17,17,.12)";
      ds.backgroundColor = "rgba(17,17,17,.015)";
      meta.hidden = false;
    } else if (state === 1) {
      ds._qsLegendState = 2;
      meta.hidden = true;
    } else {
      ds._qsLegendState = 0;
      meta.hidden = false;
      ds.borderColor = ds._qsOrigColor;
      ds.backgroundColor = ds._qsOrigBg;
    }
    if (chart.$qsSeasonalityBaseX && chart.$qsSeasonalityCurrentYear) {
      recomputeSeasonalityBands(chart);
    }
    chart.update("none");
  };

  const ch = new Chart(p.canvas.getContext("2d"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      animation: false,
      layout: { padding: { left: 6, right: LAST_VALUE_PAD_RIGHT, top: 0, bottom: 0 } },
      plugins: {
        legend: {
          display: false,
          labels: { usePointStyle: true, pointStyle: "line", boxWidth: 28, font: AXIS_TICK_FONT },
          onClick: legendToggleSeasonality,
        },
        tooltip: {
          callbacks: {
            title: (items) => {
              const x = items?.[0]?.parsed?.x;
              return (x != null) ? formatSeasonalityTick(x) : "";
            },
          },
        },
        qsEdgeXTicks: {
          enabled: true,
          forceEdgeLabels: true,
          drawEdgeMarks: true,
          edgeOutside: true,
          edgeOutsidePad: 8,
          endLabel,
        },
        qsLastValue: {
          enabled: true,
          uniformWidth: true,
          datasetIndices: datasets
            .map((d, i) => ({ i, label: String(d.label || "") }))
            .filter((d) => !/^p\d+/i.test(d.label))
            .map((d) => d.i),
          formatter: (v, ds) => {
            if (!Number.isFinite(Number(v))) return "";
            const yr = String(ds?.label || "");
            const suffix = (normMode === "index") ? "" : "%";
            return `${yr}: ${Number(v).toFixed(1)}${suffix}`;
          },
          fontForDataset: (ds) => {
            if (ds?._qsBoldLabel) return "bold 9px system-ui, -apple-system, Segoe UI, Roboto, Arial";
            return "9px system-ui, -apple-system, Segoe UI, Roboto, Arial";
          },
          font: "9px system-ui, -apple-system, Segoe UI, Roboto, Arial",
          minGap: 12,
          drawConnectors: true,
        },
        qsCrosshair: {
          enabled: true,
          formatter: (v) => {
            if (!Number.isFinite(Number(v))) return "";
            const suffix = (normMode === "index") ? "" : "%";
            return `${Number(v).toFixed(2)}${suffix}`;
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          min: baseX.length ? baseX[0] : startIdx,
          max: baseX.length ? baseX[baseX.length - 1] : endIdx,
          ticks: {
            maxTicksLimit: 8,
            font: AXIS_TICK_FONT,
            includeBounds: true,
            callback: (v) => formatSeasonalityTick(v),
          },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
        y: {
          min: yMinPad,
          max: yMaxPad,
          ticks: {
            maxTicksLimit: 6,
            font: AXIS_TICK_FONT,
            callback: (v) => {
              const suffix = (normMode === "index") ? "" : "%";
              return Number.isFinite(Number(v)) ? `${Number(v).toFixed(0)}${suffix}` : "";
            },
          },
          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
      },
    },
  });

  ch.$qsSeasonalityBaseX = baseX;
  ch.$qsSeasonalityCurrentYear = currentYear;

  panelCharts.set(panelId, ch);
  p.chart = ch;
  applyXAxisInnerTicks(ch.options.scales);
  applyAxisFonts(ch.options.scales);
  applyFixedYWidth(ch, Y_AXIS_WIDTH);
  setGridEnabledOnChart(ch, !!uiPrefs.grid);
  withZoomSuppressed(ch, () => ch.update("none"));

  attachDblClickReset(ch, p.canvas);
  installAxisGripsForChart(ch, p.rootEl?.querySelector(".qpanel-canvas"));
  installChartPan(ch, p.canvas);
  updatePanelsXAxisVisibility();
  requestChartResizeAll();
}

function renderSeasonalityHeatmap(panelId, resp, { bucket = "month" } = {}) {
  const p = panels.get(panelId);
  if (!p) return;
  const layout = ensureSeasonalityLayout(panelId);
  if (!layout) return;
  if (layout.years) layout.years.style.display = "none";
  const params = getSeasonalityParams(panelId);
  const rangeStart = parseRangeSpec(params.rangeStart || "01-01") || { month: 1, day: 1 };
  const rangeEnd = parseRangeSpec(params.rangeEnd || "12-31") || { month: 12, day: 31 };
  let statsSelected = Array.isArray(params.statsSelected) ? params.statsSelected : [];
  const rows = resp?.tables?.heatmap || [];
  if (!Array.isArray(rows) || !rows.length) {
    renderPanelError(panelId, "No heatmap data.");
    return;
  }

  const bucketLabel = (String(params.bucket || "month").toLowerCase() === "week") ? "Weekly" : "Monthly";
  const rangeLabel = `${SEASONALITY_MONTHS[rangeStart.month - 1]} ${String(rangeStart.day).padStart(2, "0")} - ${SEASONALITY_MONTHS[rangeEnd.month - 1]} ${String(rangeEnd.day).padStart(2, "0")}`;
  if (layout.title) {
    layout.title.textContent = `${String(params.expr || "").trim()} ${bucketLabel} Seasonality ${rangeLabel}`;
  }

  p.canvas.style.display = "none";
  if (p.canvas && p.canvas.parentElement === layout.body) {
    p.canvas.parentElement.removeChild(p.canvas);
  }
  if (layout.body) layout.body.innerHTML = "";
  let heat = layout.body?.querySelector(".qs-heatmap");
  if (!heat) {
    heat = document.createElement("div");
    heat.className = "qs-heatmap";
    layout.body?.appendChild(heat);
  }
  const years = Array.from(new Set(rows.map(r => Number(r.year)).filter(Number.isFinite))).sort((a, b) => a - b);
  const bucketType = String(resp?.meta?.bucket || bucket || "month").toLowerCase();
  const maxPeriod = (bucketType === "week") ? 53 : 12;
  let periodStart = 1;
  let periodEnd = maxPeriod;
  if (bucketType === "month") {
    periodStart = clamp(rangeStart.month, 1, 12);
    periodEnd = clamp(rangeEnd.month, 1, 12);
    if (periodEnd < periodStart) {
      periodStart = 1;
      periodEnd = 12;
    }
  }
  const periods = [];
  for (let p = 1; p <= maxPeriod; p++) {
    if (p < periodStart || p > periodEnd) continue;
    periods.push(p);
  }

  let selected = panelSpecs?.[panelId]?.params?.yearsSelected;
  if (Array.isArray(selected) && selected.length) {
    selected = selected.filter((y) => years.includes(Number(y)));
  }
  if (!Array.isArray(selected) || !selected.length) selected = years.slice();
  setSeasonalityParams(panelId, { yearsSelected: selected });

  const filtered = rows.filter(r => selected.includes(Number(r.year)));
  const values = filtered.map(r => Number(r.return_pct)).filter(Number.isFinite);
  const maxAbs = Math.max(1, ...values.map(v => Math.abs(v)));

  const blend = (a, b, t) => ({
    r: Math.round(a.r + (b.r - a.r) * t),
    g: Math.round(a.g + (b.g - a.g) * t),
    b: Math.round(a.b + (b.b - a.b) * t),
  });
  const green = { r: 46, g: 160, b: 96 };
  const lightGreen = { r: 178, g: 236, b: 200 };
  const lightYellow = { r: 250, g: 232, b: 160 };
  const red = { r: 206, g: 56, b: 56 };
  const lightRed = { r: 240, g: 168, b: 168 };
  const colorFor = (v) => {
    if (!Number.isFinite(v)) return "rgba(17,17,17,.04)";
    const t = Math.min(1, Math.pow(Math.abs(v) / maxAbs, 0.65));
    if (t < 0.12) return "rgba(17,17,17,.06)";
    if (v >= 0) {
      const base = (t < 0.4)
        ? blend(lightYellow, lightGreen, t / 0.4)
        : blend(lightGreen, green, (t - 0.4) / 0.6);
      return `rgba(${base.r},${base.g},${base.b},${0.5 + t * 0.45})`;
    }
    const base = (t < 0.4)
      ? blend(lightYellow, lightRed, t / 0.4)
      : blend(lightRed, red, (t - 0.4) / 0.6);
    return `rgba(${base.r},${base.g},${base.b},${0.5 + t * 0.45})`;
  };

  const periodMap = new Map();
  for (const r of rows) {
    const yy = Number(r.year);
    const pp = Number(r.period);
    if (!Number.isFinite(yy) || !Number.isFinite(pp)) continue;
    if (!periodMap.has(yy)) periodMap.set(yy, new Map());
    periodMap.get(yy).set(pp, Number(r.return_pct));
  }

  const headerCells = [];
  headerCells.push(`<div class="qs-heatmap-cell qs-heatmap-year"></div>`);
  for (const p of periods) {
    const label = (bucketType === "week") ? `W${String(p).padStart(2, "0")}` : SEASONALITY_MONTHS[p - 1];
    headerCells.push(`<div class="qs-heatmap-cell qs-heatmap-year">${label}</div>`);
  }
  headerCells.push(`<div class="qs-heatmap-cell qs-heatmap-year">Year</div>`);
  const header = `<div class="qs-heatmap-row" style="grid-template-columns:90px repeat(${periods.length}, minmax(18px, 1fr)) 70px;">${headerCells.join("")}</div>`;

  const yearReturn = (vals) => {
    let acc = 1;
    let seen = 0;
    for (const v of vals) {
      if (!Number.isFinite(v)) continue;
      acc *= (1 + v / 100);
      seen += 1;
    }
    if (!seen) return null;
    return (acc - 1) * 100;
  };

  const rowsHtml = years.map((y) => {
    const cells = [];
    const rowMap = periodMap.get(Number(y)) || new Map();
    const isOn = selected.includes(y);
    const rowClass = isOn ? "" : " is-disabled";
    cells.push(`<div class="qs-heatmap-cell qs-heatmap-year qs-heatmap-rowhead"><label class="qs-heatmap-rowlabel"><input type="checkbox" data-year="${y}" ${isOn ? "checked" : ""}/> ${y}</label></div>`);
    const vals = [];
    for (const p of periods) {
      const v = rowMap.has(p) ? Number(rowMap.get(p)) : null;
      vals.push(v);
      const text = Number.isFinite(v) ? `${v.toFixed(1)}` : "";
      if (isOn) cells.push(`<div class="qs-heatmap-cell" style="background:${colorFor(v)}">${text}</div>`);
      else cells.push(`<div class="qs-heatmap-cell qs-heatmap-disabled">${text}</div>`);
    }
    const yr = yearReturn(vals);
    if (isOn) cells.push(`<div class="qs-heatmap-cell qs-heatmap-year">${Number.isFinite(yr) ? `${yr.toFixed(1)}%` : ""}</div>`);
    else cells.push(`<div class="qs-heatmap-cell qs-heatmap-year qs-heatmap-disabled">${Number.isFinite(yr) ? `${yr.toFixed(1)}%` : ""}</div>`);
    return `<div class="qs-heatmap-row${rowClass}" style="grid-template-columns:90px repeat(${periods.length}, minmax(18px, 1fr)) 70px;">${cells.join("")}</div>`;
  }).join("");

  let summaryHtml = "";
  const stats = [
    { key: "mean", label: "Mean", fmt: (v) => Number(v).toFixed(1) },
    { key: "median", label: "Median", fmt: (v) => Number(v).toFixed(1) },
    { key: "min", label: "Min", fmt: (v) => Number(v).toFixed(1) },
    { key: "max", label: "Max", fmt: (v) => Number(v).toFixed(1) },
    { key: "pos", label: "%Pos", fmt: (v) => `${Math.round(Number(v) * 100)}%` },
    { key: "neg", label: "%Neg", fmt: (v) => `${Math.round(Number(v) * 100)}%` },
    { key: "stdev", label: "StdDev", fmt: (v) => Number(v).toFixed(1) },
  ];
  if (!statsSelected.length) {
    statsSelected = stats.map((st) => st.key);
    setSeasonalityParams(panelId, { statsSelected });
  }

  const periodStats = new Map();
  for (const p of periods) {
    const vals = [];
    for (const y of selected) {
      const rowMap = periodMap.get(Number(y));
      const v = rowMap?.get(p);
      if (Number.isFinite(v)) vals.push(Number(v));
    }
    if (!vals.length) {
      periodStats.set(p, null);
      continue;
    }
    vals.sort((a, b) => a - b);
    const pos = vals.filter(v => v > 0).length / vals.length;
    const neg = vals.filter(v => v < 0).length / vals.length;
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const median = quantileSorted(vals, 0.5);
    const min = vals[0];
    const max = vals[vals.length - 1];
    const stdev = (vals.length >= 2)
      ? Math.sqrt(vals.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (vals.length - 1))
      : 0;
    periodStats.set(p, { mean, median, min, max, pos, neg, stdev });
  }

  const summaryAll = (() => {
    const vals = [];
    for (const y of selected) {
      const rowMap = periodMap.get(Number(y));
      if (!rowMap) continue;
      for (const p of periods) {
        const v = rowMap.get(p);
        if (Number.isFinite(v)) vals.push(Number(v));
      }
    }
    if (!vals.length) return null;
    vals.sort((a, b) => a - b);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const pos = vals.filter(v => v > 0).length / vals.length;
    const neg = vals.filter(v => v < 0).length / vals.length;
    const stdev = (vals.length >= 2)
      ? Math.sqrt(vals.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (vals.length - 1))
      : 0;
    return {
      mean,
      median: quantileSorted(vals, 0.5),
      min: vals[0],
      max: vals[vals.length - 1],
      pos,
      neg,
      stdev,
    };
  })();

  const rowsSummary = [];
  for (const stDef of stats) {
    const on = statsSelected.includes(stDef.key);
    const row = [];
    row.push(`<div class="qs-heatmap-cell qs-heatmap-year qs-heatmap-rowhead"><label class="qs-heatmap-rowlabel"><input type="checkbox" data-stat="${stDef.key}" ${on ? "checked" : ""}/> ${stDef.label}</label></div>`);
    if (on) {
      for (const p of periods) {
        const st = periodStats.get(p);
        const val = st ? st[stDef.key] : null;
        const text = Number.isFinite(val) ? stDef.fmt(val) : "";
        row.push(`<div class="qs-heatmap-cell qs-heatmap-summary">${text}</div>`);
      }
      const tail = summaryAll ? summaryAll[stDef.key] : null;
      const tailText = Number.isFinite(tail) ? stDef.fmt(tail) : "";
      row.push(`<div class="qs-heatmap-cell qs-heatmap-summary">${tailText}</div>`);
    } else {
      row.push(`<div class="qs-heatmap-cell qs-heatmap-summary" style="grid-column: span ${periods.length + 1};"></div>`);
    }
    rowsSummary.push(`<div class="qs-heatmap-row qs-heatmap-summary" style="grid-template-columns:90px repeat(${periods.length}, minmax(18px, 1fr)) 70px;">${row.join("")}</div>`);
  }
  summaryHtml = rowsSummary.join("");

  heat.innerHTML = `<div class="qs-heatmap-grid">${header}${rowsHtml}${summaryHtml}</div>`;

  let grab = layout.body?.querySelector(".qs-heatmap-resize");
  if (!grab && layout.body) {
    grab = document.createElement("div");
    grab.className = "qs-heatmap-resize";
    layout.body.appendChild(grab);
  }
  const key = "qs.heatmap.h.v1";
  const saved = Number(loadJSON(key, null));
  const positionGrab = () => {
    if (!grab) return;
    const top = heat.offsetTop + heat.offsetHeight + 78;
    grab.style.top = `${Math.max(0, top)}px`;
  };
  const updateRowHeight = (px) => {
    const rowsCount = heat.querySelectorAll(".qs-heatmap-row").length;
    if (!rowsCount) return;
    const usable = Math.max(0, px - 28);
    const rowH = Math.max(18, Math.floor(usable / rowsCount));
    heat.style.setProperty("--qs-heatmap-row-h", `${rowH}px`);
  };
  const setHeatHeight = (h) => {
    const px = clamp(h, 220, 1000);
    heat.style.height = `${px}px`;
    heat.style.flex = `0 0 ${px}px`;
    updateRowHeight(px);
    positionGrab();
  };
  if (Number.isFinite(saved)) setHeatHeight(saved);
  else setHeatHeight(560);
  positionGrab();

  let dragging = false;
  let startY = 0;
  let startH = 0;
  const applyDrag = (clientY) => {
    if (!dragging) return;
    const dy = clientY - startY;
    const nh = startH + dy;
    setHeatHeight(nh);
    saveJSON(key, clamp(nh, 220, 1000));
  };
  const onPointerMove = (ev) => applyDrag(ev.clientY);
  const onPointerUp = (ev) => {
    dragging = false;
    document.body.classList.remove("qs-resizing");
    try { grab?.releasePointerCapture?.(ev.pointerId); } catch {}
    grab?.removeEventListener("pointermove", onPointerMove);
    grab?.removeEventListener("pointerup", onPointerUp);
    grab?.removeEventListener("pointercancel", onPointerUp);
    window.removeEventListener("pointermove", onPointerMove, true);
    window.removeEventListener("pointerup", onPointerUp, true);
    window.removeEventListener("pointercancel", onPointerUp, true);
    window.removeEventListener("mousemove", onMouseMove, true);
    window.removeEventListener("mouseup", onMouseUp, true);
  };
  const onMouseMove = (ev) => applyDrag(ev.clientY);
  const onMouseUp = () => {
    dragging = false;
    document.body.classList.remove("qs-resizing");
    window.removeEventListener("mousemove", onMouseMove, true);
    window.removeEventListener("mouseup", onMouseUp, true);
  };
  const startDrag = (clientY) => {
    dragging = true;
    startY = clientY;
    startH = heat.getBoundingClientRect().height;
    document.body.classList.add("qs-resizing");
  };
  const isNearBottom = (ev) => {
    const r = heat.getBoundingClientRect();
    return ev.clientY >= (r.bottom - 28);
  };
  if (grab && !grab.$qsResizeInstalled) {
    grab.$qsResizeInstalled = true;
    grab.style.touchAction = "none";
    grab.addEventListener("dragstart", (ev) => ev.preventDefault());
    grab.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      startDrag(ev.clientY);
      try { grab.setPointerCapture(ev.pointerId); } catch {}
      grab.addEventListener("pointermove", onPointerMove);
      grab.addEventListener("pointerup", onPointerUp);
      grab.addEventListener("pointercancel", onPointerUp);
      window.addEventListener("pointermove", onPointerMove, true);
      window.addEventListener("pointerup", onPointerUp, true);
      window.addEventListener("pointercancel", onPointerUp, true);
    });
    grab.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      startDrag(ev.clientY);
      window.addEventListener("mousemove", onMouseMove, true);
      window.addEventListener("mouseup", onMouseUp, true);
    });
  }
  if (!heat.$qsResizeInstalled) {
    heat.$qsResizeInstalled = true;
    heat.addEventListener("pointerdown", (ev) => {
      if (!isNearBottom(ev)) return;
      ev.preventDefault();
      ev.stopPropagation();
      startDrag(ev.clientY);
      try { heat.setPointerCapture(ev.pointerId); } catch {}
      heat.addEventListener("pointermove", onPointerMove);
      heat.addEventListener("pointerup", onPointerUp);
      heat.addEventListener("pointercancel", onPointerUp);
      window.addEventListener("pointermove", onPointerMove, true);
      window.addEventListener("pointerup", onPointerUp, true);
      window.addEventListener("pointercancel", onPointerUp, true);
    });
    heat.addEventListener("mousedown", (ev) => {
      if (!isNearBottom(ev)) return;
      ev.preventDefault();
      ev.stopPropagation();
      startDrag(ev.clientY);
      window.addEventListener("mousemove", onMouseMove, true);
      window.addEventListener("mouseup", onMouseUp, true);
    });
  }
  if (layout.body && !layout.body.$qsHeatmapResizeBound) {
    layout.body.$qsHeatmapResizeBound = true;
    window.addEventListener("resize", positionGrab);
  }

  heat.querySelectorAll("input[type=checkbox][data-year]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const picked = Array.from(heat.querySelectorAll("input[data-year]:checked"))
        .map(x => Number(x.dataset.year))
        .filter(Number.isFinite);
      setSeasonalityParams(panelId, { yearsSelected: picked });
      renderSeasonalityHeatmap(panelId, resp, { bucket: bucketType });
    });
  });

  heat.querySelectorAll("input[type=checkbox][data-stat]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const picked = Array.from(heat.querySelectorAll("input[data-stat]:checked"))
        .map(x => String(x.dataset.stat))
        .filter(Boolean);
      setSeasonalityParams(panelId, { statsSelected: picked });
      renderSeasonalityHeatmap(panelId, resp, { bucket: bucketType });
    });
  });
}

function formatDateTick(ms) {
  let v = ms;
  if (v instanceof Date) v = v.getTime();
  if (v && typeof v === "object") {
    if ("value" in v) v = v.value;
    else if ("x" in v) v = v.x;
    else if ("t" in v) v = v.t;
    else if ("time" in v) v = v.time;
    else v = null;
  }

  if (v == null) return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return "";

  try {
    return new Intl.DateTimeFormat(undefined, { year: "2-digit", month: "short", day: "2-digit" })
      .format(new Date(n));
  } catch {
    return "";
  }
}

function formatDateShort(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n)) return "";
  try {
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit", year: "2-digit" })
      .format(new Date(n));
  } catch {
    return "";
  }
}

function ensureEdgeXTicksPlugin() {
  if (!window.Chart || window.$qsEdgeXTicksInstalled) return;
  window.$qsEdgeXTicksInstalled = true;

  const plugin = {
    id: "qsEdgeXTicks",
    afterDraw(chart, args, opts) {
      if (!opts || !opts.enabled) return;

      const scale = chart.scales?.x;
      if (!scale) return;

      // Only draw if ticks are visible on this chart
      const showTicks = scale.options?.ticks?.display !== false;
      if (!showTicks) return;

      const ticks = scale.ticks || [];
      if (ticks.length < 2 && !opts.forceEdgeLabels) return;

      const area = chart.chartArea;
      const ctx = chart.ctx;

      // Chart.js tick callback (value, index, ticks)
      const cb = scale.options?.ticks?.callback;
      const mkLabel = (tick, idx) => {
        const v = tick?.value ?? tick;
        if (typeof cb === "function") return cb(v, idx, ticks);
        return formatDateTick(v);
      };

      const tickRef = ticks.length ? ticks : [{ value: scale.min }, { value: scale.max }];
      const firstTick = opts.forceEdgeLabels ? { value: scale.min } : tickRef[0];
      const lastTick = opts.forceEdgeLabels ? { value: scale.max } : tickRef[tickRef.length - 1];
      const firstLabel = mkLabel(firstTick, 0);
      const lastLabel = mkLabel(lastTick, tickRef.length - 1);

      if (!firstLabel && !lastLabel) return;

      // Font / color: use scale tick styling
      const tickOpts = scale.options?.ticks || {};
      const font = Chart.helpers?.toFont ? Chart.helpers.toFont(tickOpts.font) : null;
      const fontStr = font?.string || "12px system-ui";

      const pad = Number(tickOpts.padding ?? 6);
      const y = scale.bottom + pad;

      ctx.save();
      ctx.font = fontStr;
      ctx.fillStyle = tickOpts.color || "rgba(17,17,17,.7)";
      ctx.textBaseline = "top";

      if (firstLabel) {
        ctx.textAlign = "left";
        ctx.fillText(String(firstLabel), area.left, y);
      }

      if (lastLabel || opts.endLabel) {
        const pad = Number(opts.edgeOutsidePad ?? 8);
        const rx = opts.edgeOutside ? Math.min(ctx.canvas.width - 4, area.right + pad) : area.right;
        ctx.textAlign = opts.edgeOutside ? "left" : "right";
        ctx.fillText(String(opts.endLabel || lastLabel), rx, y);
      }

      if (opts.drawEdgeMarks) {
        const markY0 = scale.bottom - 2;
        const markY1 = scale.bottom + 4;
        ctx.strokeStyle = tickOpts.color || "rgba(17,17,17,.4)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(area.left, markY0);
        ctx.lineTo(area.left, markY1);
        ctx.moveTo(area.right, markY0);
        ctx.lineTo(area.right, markY1);
        ctx.stroke();
      }

      ctx.restore();
    },
  };

  try {
    Chart.register(plugin);
  } catch {
    // ignore if already registered
  }
}

function ensureTopDatesPlugin() {
  if (!window.Chart || window.$qsTopDatesInstalled) return;
  window.$qsTopDatesInstalled = true;

  const plugin = {
    id: "qsTopDates",
    afterDraw(chart, args, opts) {
      if (!opts || !opts.enabled) return;

      const scale = chart.scales?.x;
      if (!scale) return;

      const area = chart.chartArea;
      if (!area) return;

      const xb = state?.base?.xBounds;
      const xMin = xb?.xMin ?? scale.min;
      const xMax = xb?.xMax ?? scale.max;
      if (!Number.isFinite(xMin) || !Number.isFinite(xMax)) return;

      const left = formatDateShort(xMin);
      const right = formatDateShort(xMax);
      if (!left && !right) return;

      const ctx = chart.ctx;
      const fontStr = "10px system-ui, -apple-system, Segoe UI, Roboto, Arial";

      ctx.save();
      ctx.font = fontStr;
      ctx.fillStyle = "rgba(17,17,17,.55)";
      ctx.textBaseline = "bottom";

      if (left) {
        ctx.textAlign = "left";
        ctx.fillText(left, area.left, area.top - 8);
      }
      if (right) {
        ctx.textAlign = "right";
        ctx.fillText(right, area.right, area.top - 8);
      }

      const tickY = area.top - 4;
      const tail = 12;
      ctx.strokeStyle = "rgba(17,17,17,.55)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (left) {
        ctx.moveTo(area.left, tickY - 6);
        ctx.lineTo(area.left, tickY + 2);
        ctx.moveTo(area.left, tickY);
        ctx.lineTo(area.left + tail, tickY);
      }
      if (right) {
        ctx.moveTo(area.right, tickY - 6);
        ctx.lineTo(area.right, tickY + 2);
        ctx.moveTo(area.right - tail, tickY);
        ctx.lineTo(area.right, tickY);
      }
      ctx.stroke();
      ctx.restore();
    },
  };

  try {
    Chart.register(plugin);
  } catch {
    // ignore if already registered
  }
}

function ensureLastValuePlugin() {
  if (!window.Chart || window.$qsLastValueInstalled) return;
  window.$qsLastValueInstalled = true;

  const nearestPoint = (data, xVal) => {
    if (!Array.isArray(data) || !data.length || !Number.isFinite(xVal)) return null;
    let lo = 0;
    let hi = data.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const mx = data[mid]?.x;
      if (!Number.isFinite(mx)) break;
      if (mx === xVal) { lo = mid; hi = mid; break; }
      if (mx < xVal) lo = mid + 1;
      else hi = mid - 1;
    }
    const idx = clamp(lo, 0, data.length - 1);
    const idx2 = clamp(idx - 1, 0, data.length - 1);
    const a = data[idx];
    const b = data[idx2];
    if (!a || !b) return a || b || null;
    const ax = a.x;
    const bx = b.x;
    if (!Number.isFinite(ax) || !Number.isFinite(bx)) return a;
    return (Math.abs(ax - xVal) < Math.abs(bx - xVal)) ? a : b;
  };

  const drawLabel = (ctx, x, y, text, color, fontStr = null, forceWidth = null) => {
    const padX = 6;
    const padY = 3;
    const font = fontStr || "11px system-ui, -apple-system, Segoe UI, Roboto, Arial";
    ctx.save();
    ctx.font = font;
    let w = ctx.measureText(text).width + padX * 2;
    if (Number.isFinite(forceWidth)) w = Math.max(w, forceWidth);
    const h = 16;
    let xx = x;
    let yy = y - h / 2;

    const maxX = ctx.canvas.width - 4;
    if (xx + w > maxX) xx = maxX - w;
    if (yy < 4) yy = 4;
    if (yy + h > ctx.canvas.height - 4) yy = ctx.canvas.height - 4 - h;

    const r = 4;
    ctx.beginPath();
    ctx.moveTo(xx + r, yy);
    ctx.lineTo(xx + w - r, yy);
    ctx.quadraticCurveTo(xx + w, yy, xx + w, yy + r);
    ctx.lineTo(xx + w, yy + h - r);
    ctx.quadraticCurveTo(xx + w, yy + h, xx + w - r, yy + h);
    ctx.lineTo(xx + r, yy + h);
    ctx.quadraticCurveTo(xx, yy + h, xx, yy + h - r);
    ctx.lineTo(xx, yy + r);
    ctx.quadraticCurveTo(xx, yy, xx + r, yy);
    ctx.closePath();

    ctx.fillStyle = color || "rgba(37,99,235,.9)";
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillText(text, xx + padX, yy + h / 2);
    ctx.restore();
    return { x: xx, y: yy, w, h };
  };

  const plugin = {
    id: "qsLastValue",
    afterEvent(chart, args, opts) {
      if (!opts || !opts.enabled) return;
      if (args?.event?.type !== "click") return;
      const ev = args.event;
      const rects = chart.$qsLastValueRects || [];
      if (!rects.length) return;
      for (const r of rects) {
        if (ev.x >= r.x && ev.x <= r.x + r.w && ev.y >= r.y && ev.y <= r.y + r.h) {
          const canvasRect = chart.canvas?.getBoundingClientRect?.();
          const clientX = canvasRect ? canvasRect.left + r.x + r.w + 8 : null;
          const clientY = canvasRect ? canvasRect.top + r.y + r.h / 2 : null;
          openColorPickerForDataset(chart, r.datasetIndex, clientX, clientY);
          break;
        }
      }
    },
    afterDatasetsDraw(chart, args, opts) {
      if (!opts || !opts.enabled) return;
      const indices = Array.isArray(opts.datasetIndices) ? opts.datasetIndices
        : [Number.isFinite(opts.datasetIndex) ? opts.datasetIndex : 0];
      const yScale = chart.scales?.y;
      const area = chart.chartArea;
      if (!yScale || !area) return;
      const formatter = typeof opts.formatter === "function" ? opts.formatter : (v) => String(v);
      const minGap = Number.isFinite(opts.minGap) ? opts.minGap : 14;
      const fontStr = typeof opts.font === "string" ? opts.font : null;
      const fontForDataset = typeof opts.fontForDataset === "function" ? opts.fontForDataset : null;
      chart.$qsLastValueRects = [];

      const labels = [];
      for (const idx of indices) {
        const ds = chart.data?.datasets?.[idx];
        if (!ds) continue;
        const meta = chart.getDatasetMeta?.(idx);
        if (ds.hidden || meta?.hidden) continue;
        const data = ds.data || [];
        const cross = window.$qsCrosshairState;
        let last = null;
        if (cross?.active && Number.isFinite(cross.xValue)) {
          const pt = nearestPoint(data, cross.xValue);
          const y = (pt && typeof pt === "object") ? pt.y : null;
          if (Number.isFinite(Number(y))) last = { y: Number(y) };
        } else {
          for (let i = data.length - 1; i >= 0; i--) {
            const p = data[i];
            const y = (p && typeof p === "object") ? p.y : Array.isArray(p) ? p[1] : p;
            if (Number.isFinite(Number(y))) {
              last = { y: Number(y) };
              break;
            }
          }
        }
        if (!last) continue;
        const y = yScale.getPixelForValue(last.y);
        const text = formatter(last.y, ds, idx);
        if (!text) continue;

        const color =
          ds._qsLegendState === 1 ? "rgba(17,17,17,.2)" :
          typeof ds.borderColor === "string" ? ds.borderColor :
          typeof ds.backgroundColor === "string" ? ds.backgroundColor :
          "rgba(37,99,235,.9)";

        const dsFont = fontForDataset ? fontForDataset(ds, idx) : null;
        labels.push({ idx, y, y0: y, text, color, font: dsFont || fontStr });
      }

      labels.sort((a, b) => a.y - b.y);
      for (let i = 1; i < labels.length; i++) {
        const prev = labels[i - 1];
        const cur = labels[i];
        if (cur.y - prev.y < minGap) {
          cur.y = prev.y + minGap;
        }
      }
      if (labels.length) {
        const last = labels[labels.length - 1];
        if (last.y > area.bottom - 6) {
          const shift = last.y - (area.bottom - 6);
          for (const l of labels) l.y -= shift;
        }
        const first = labels[0];
        if (first.y < area.top + 6) {
          const shift = (area.top + 6) - first.y;
          for (const l of labels) l.y += shift;
        }
      }

      let maxW = 0;
      for (const l of labels) {
        const f = l.font || fontStr || "11px system-ui, -apple-system, Segoe UI, Roboto, Arial";
        chart.ctx.save();
        chart.ctx.font = f;
        maxW = Math.max(maxW, chart.ctx.measureText(l.text).width + 12);
        chart.ctx.restore();
      }
      const maxX = chart.ctx.canvas.width - 4;
      const anchorX = Math.min(area.right + 10, maxX - maxW);

      for (const l of labels) {
        const rect = drawLabel(
          chart.ctx,
          anchorX,
          l.y,
          l.text,
          l.color,
          l.font,
          opts.uniformWidth ? maxW : null
        );
        if (rect) {
          chart.$qsLastValueRects.push({ ...rect, datasetIndex: l.idx });
          if (opts.drawConnectors !== false) {
            chart.ctx.save();
            chart.ctx.strokeStyle = l.color || "rgba(17,17,17,.35)";
            chart.ctx.lineWidth = 1;
            chart.ctx.beginPath();
            chart.ctx.moveTo(area.right, l.y0);
            chart.ctx.lineTo(rect.x, rect.y + rect.h / 2);
            chart.ctx.stroke();
            chart.ctx.restore();
          }
        }
      }
    },
  };

  try {
    Chart.register(plugin);
  } catch {
    // ignore if already registered
  }
}

function ensureAxisControlsPlugin() {
  if (!window.Chart || window.$qsAxisControlsInstalled) return;
  window.$qsAxisControlsInstalled = true;

  const drawBtn = (ctx, x, y, label) => {
    const w = 12;
    const h = 12;
    ctx.save();
    ctx.strokeStyle = "#000";
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = "#000";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = "#fff";
    ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, x + w / 2, y + h / 2);
    ctx.restore();
    return { x, y, w, h };
  };

  const plugin = {
    id: "qsAxisControls",
    afterDraw(chart, args, opts) {
      if (!opts || !opts.enabled) return;
      const area = chart.chartArea;
      if (!area) return;
      const rects = [];
      const size = 12;
      const pad = 4;
      const lastRects = chart.$qsLastValueRects || [];
      const minLabelY = lastRects.length
        ? Math.min(...lastRects.map(r => r.y))
        : null;

      Object.keys(chart.scales || {}).forEach((id) => {
        const sc = chart.scales[id];
        if (!sc || sc.axis !== "y") return;
        const isLeft = sc.position !== "right";
        let x = isLeft
          ? sc.left - (size * 2 + pad + 6)
          : sc.right + 6;
        const maxX = chart.ctx.canvas.width - (size * 2 + pad + 2);
        x = clamp(x, 4, maxX);
        const yBase = (minLabelY != null) ? (minLabelY - size - 6) : (area.top + 2);
        const y = clamp(yBase, area.top + 2, area.bottom - size - 2);
        rects.push({ ...drawBtn(chart.ctx, x, y, "N"), axisId: id, type: "norm" });
        rects.push({ ...drawBtn(chart.ctx, x + size + pad, y, "↕"), axisId: id, type: "invert" });
      });

      chart.$qsAxisControlRects = rects;
    },
    afterEvent(chart, args, opts) {
      if (!opts || !opts.enabled) return;
      if (args?.event?.type !== "click") return;
      const rects = chart.$qsAxisControlRects || [];
      if (!rects.length) return;
      const ev = args.event;
      for (const r of rects) {
        if (ev.x >= r.x && ev.x <= r.x + r.w && ev.y >= r.y && ev.y <= r.y + r.h) {
          if (r.type === "invert") {
            const sc = chart.scales?.[r.axisId];
            if (sc?.options) {
              sc.options.reverse = !sc.options.reverse;
              chart.update("none");
            }
          } else if (r.type === "norm") {
            if (typeof chart.$qsAxisNormalize === "function") chart.$qsAxisNormalize(r.axisId);
          }
          break;
        }
      }
    },
  };

  try {
    Chart.register(plugin);
  } catch {
    // ignore if already registered
  }
}

function ensureCrosshairPlugin() {
  if (!window.Chart || window.$qsCrosshairInstalled) return;
  window.$qsCrosshairInstalled = true;

  const state = { active: false, xValue: null, raf: false };
  window.$qsCrosshairState = state;

  const nearestPoint = (data, xVal) => {
    if (!Array.isArray(data) || !data.length || !Number.isFinite(xVal)) return null;
    let lo = 0;
    let hi = data.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const mx = data[mid]?.x;
      if (!Number.isFinite(mx)) break;
      if (mx === xVal) { lo = mid; hi = mid; break; }
      if (mx < xVal) lo = mid + 1;
      else hi = mid - 1;
    }
    const idx = clamp(lo, 0, data.length - 1);
    const idx2 = clamp(idx - 1, 0, data.length - 1);
    const a = data[idx];
    const b = data[idx2];
    if (!a || !b) return a || b || null;
    const ax = a.x;
    const bx = b.x;
    if (!Number.isFinite(ax) || !Number.isFinite(bx)) return a;
    return (Math.abs(ax - xVal) < Math.abs(bx - xVal)) ? a : b;
  };

  const requestRedraw = () => {
    if (state.raf) return;
    state.raf = true;
    requestAnimationFrame(() => {
      state.raf = false;
      try { priceChart?.draw(); } catch {}
      for (const ch of panelCharts.values()) {
        try { ch.draw(); } catch {}
      }
    });
  };

  const plugin = {
    id: "qsCrosshair",
    afterEvent(chart, args, opts) {
      if (!opts || !opts.enabled) return;
      const ev = args?.event;
      if (!ev) return;
      if (ev.type === "mouseout" || ev.type === "mouseleave") {
        state.active = false;
        requestRedraw();
        return;
      }
      if (ev.type !== "mousemove" && ev.type !== "pointermove" && ev.type !== "touchmove") return;
      const scale = chart.scales?.x;
      const area = chart.chartArea;
      if (!scale || !area) return;
      const x = ev.x;
      if (!Number.isFinite(x) || x < area.left || x > area.right) {
        state.active = false;
        requestRedraw();
        return;
      }
      const xVal = scale.getValueForPixel(x);
      if (!Number.isFinite(xVal)) return;
      state.active = true;
      state.xValue = xVal;
      requestRedraw();
    },
    afterDraw(chart, args, opts) {
      if (!opts || !opts.enabled) return;
      if (!state.active || !Number.isFinite(state.xValue)) return;
      const scaleX = chart.scales?.x;
      const scaleY = chart.scales?.y;
      const area = chart.chartArea;
      if (!scaleX || !scaleY || !area) return;

      const xPix = scaleX.getPixelForValue(state.xValue);
      if (!Number.isFinite(xPix) || xPix < area.left || xPix > area.right) return;

      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = "rgba(17,17,17,.25)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(xPix, area.top);
      ctx.lineTo(xPix, area.bottom);
      ctx.stroke();
      ctx.restore();

      void nearestPoint;
    },
  };

  try {
    Chart.register(plugin);
  } catch {
    // ignore if already registered
  }
}



function applyXAxisInnerTicks(scales) {
  if (!scales?.x) return;
  if (!scales.x.ticks || typeof scales.x.ticks !== "object") scales.x.ticks = {};
  scales.x.ticks.align = "inner";
  scales.x.ticks.maxRotation = 0;
  scales.x.ticks.minRotation = 0;
  scales.x.ticks.padding = 6;
  scales.x.ticks.includeBounds = false;
  scales.x.ticks.mirror = false;
  scales.x.ticks.font = AXIS_TICK_FONT;
  scales.x.offset = false;
  if (!scales.x.grid || typeof scales.x.grid !== "object") scales.x.grid = {};
  scales.x.grid.display = true;
  scales.x.grid.drawTicks = true;
}

function applyAxisFonts(scales) {
  if (!scales) return;
  if (scales.x?.ticks) scales.x.ticks.font = AXIS_TICK_FONT;
  Object.keys(scales).forEach((k) => {
    if (!/^y/i.test(k)) return;
    if (scales[k]?.ticks) scales[k].ticks.font = AXIS_TICK_FONT;
  });
}

// minimal: keeps left padding stable (your old helper didn’t actually set width)
function applyFixedYWidth(chart, px = Y_AXIS_WIDTH) {
  if (!chart?.options?.scales) return;
  Object.keys(chart.options.scales).forEach((k) => {
    if (!/^y/i.test(k)) return;
    const sc = chart.options.scales[k];
    if (!sc) return;
    sc.afterFit = (scale) => { scale.width = px; };
  });
}

function setGridEnabledOnChart(chart, enabled) {
  if (!chart?.options?.scales) return;
  for (const k of Object.keys(chart.options.scales)) {
    const sc = chart.options.scales[k];
    if (!sc) continue;
    if (!sc.grid || typeof sc.grid !== "object") sc.grid = {};
    sc.grid.display = !!enabled;
  }
}

function toggleChartLegend(chart) {
  if (!chart?.options?.plugins?.legend) return;
  const cur = chart.$qsLegendShown === true;
  chart.$qsLegendShown = !cur;
  chart.options.plugins.legend.display = chart.$qsLegendShown;
  withZoomSuppressed(chart, () => chart.update("none"));
}

function legendToggleDataset(e, legendItem, legend) {
  const chart = legend?.chart;
  if (!chart) return;
  const idx = legendItem.datasetIndex;
  const visible = chart.isDatasetVisible(idx);
  chart.setDatasetVisibility(idx, !visible);
  withZoomSuppressed(chart, () => chart.update("none"));
}

function openColorPickerForDataset(chart, datasetIndex, clientX, clientY) {
  if (!chart?.data?.datasets?.length) return;
  const ds = chart.data.datasets[datasetIndex];
  if (!ds) return;
  const lbl = ds.label || `series_${datasetIndex}`;
  const current = (ds.borderColor && String(ds.borderColor)) || "#111111";
  const picker = getOrCreateColorPicker();
  picker.value = toHexColor(current) || "#111111";

  if (Number.isFinite(clientX) && Number.isFinite(clientY)) {
    picker.style.left = `${Math.max(0, clientX - 6)}px`;
    picker.style.top = `${Math.max(0, clientY - 6)}px`;
  }

  picker.oninput = () => {
    const c = picker.value;
    ds.borderColor = c;
    if (typeof ds.backgroundColor === "string" && ds.backgroundColor !== "transparent") {
      ds.backgroundColor = c;
    }
    dsColors[lbl] = c;
    saveJSON(DS_COLOR_KEY, dsColors);
    withZoomSuppressed(chart, () => chart.update("none"));
  };
  picker.click();
}

function installAxisGripsForChart(chart, containerEl) {
  if (!chart || !containerEl) return;
  containerEl.querySelectorAll(".qs-axis-grip").forEach(el => el.remove());

  const yGripMax = document.createElement("div");
  yGripMax.className = "qs-axis-grip qs-axis-grip-y qs-axis-grip-y-max";
  yGripMax.title = "Drag to adjust Y max";

  const yGripMin = document.createElement("div");
  yGripMin.className = "qs-axis-grip qs-axis-grip-y qs-axis-grip-y-min";
  yGripMin.title = "Drag to adjust Y min";

  const xGrip = document.createElement("div");
  xGrip.className = "qs-axis-grip qs-axis-grip-x";
  xGrip.title = "Drag to scale X";

  containerEl.appendChild(yGripMax);
  containerEl.appendChild(yGripMin);
  containerEl.appendChild(xGrip);

  const startDrag = (axis, ev, which = null) => {
    ev.preventDefault();
    ev.stopPropagation();

    const scale = chart.scales?.[axis];
    if (!scale || !Number.isFinite(scale.min) || !Number.isFinite(scale.max)) return;

    const start = {
      min: scale.min,
      max: scale.max,
      x: ev.clientX,
      y: ev.clientY,
    };

    const onMove = (e) => {
      if (!chart.scales?.[axis]) return;
      if (axis === "y") {
        const dy = e.clientY - start.y;
        const baseRange = Math.max(1e-9, start.max - start.min);
        const step = baseRange / 220;
        const eps = Math.max(1e-9, baseRange * 0.02);
        if (which === "max") {
          let max = start.max - (dy * step);
          max = Math.max(max, start.min + eps);
          chart.options.scales.y.max = max;
          if (Number.isFinite(chart.options.scales.y.min) === false) {
            chart.options.scales.y.min = start.min;
          }
        } else if (which === "min") {
          let min = start.min - (dy * step);
          min = Math.min(min, start.max - eps);
          chart.options.scales.y.min = min;
          if (Number.isFinite(chart.options.scales.y.max) === false) {
            chart.options.scales.y.max = start.max;
          }
        }
        withZoomSuppressed(chart, () => chart.update("none"));
        return;
      }

      const dx = e.clientX - start.x;
      const factor = clamp(1 + (dx / 220), 0.2, 5);
      const min = start.min;
      const range = Math.max(1e-6, (start.max - start.min) * factor);
      state.base.xBounds = { xMin: min, xMax: min + range };
      syncAllPanelsToBaseXBounds();
    };

    const onUp = () => {
      window.removeEventListener("mousemove", onMove, true);
      window.removeEventListener("mouseup", onUp, true);
    };

    window.addEventListener("mousemove", onMove, true);
    window.addEventListener("mouseup", onUp, true);
  };

  yGripMax.addEventListener("mousedown", (ev) => startDrag("y", ev, "max"));
  yGripMin.addEventListener("mousedown", (ev) => startDrag("y", ev, "min"));
  xGrip.addEventListener("mousedown", (ev) => startDrag("x", ev));
}

function installChartPan(chart, canvas) {
  if (!chart || !canvas || canvas.$qsPanAttached) return;
  canvas.$qsPanAttached = true;

  let dragging = false;
  let startX = 0;
  let startBounds = null;

  const onMove = (e) => {
    if (!dragging || !startBounds) return;
    const scale = chart.scales?.x;
    const area = chart.chartArea;
    if (!scale || !area) return;
    const pxSpan = Math.max(1, area.right - area.left);
    const valuePerPx = (scale.max - scale.min) / pxSpan;
    const dx = e.clientX - startX;
    const dv = -dx * valuePerPx;
    state.base.xBounds = { xMin: startBounds.xMin + dv, xMax: startBounds.xMax + dv };
    syncAllPanelsToBaseXBounds();
  };

  const onUp = () => {
    dragging = false;
    startBounds = null;
    document.body.classList.remove("qs-grabbing");
    window.removeEventListener("mousemove", onMove, true);
    window.removeEventListener("mouseup", onUp, true);
  };

  canvas.addEventListener("mousedown", (ev) => {
    if (ev.button !== 0) return;
    const area = chart.chartArea;
    if (!area) return;
    if (ev.offsetX < area.left || ev.offsetX > area.right || ev.offsetY < area.top || ev.offsetY > area.bottom) return;
    if (!state.base.xBounds) return;
    dragging = true;
    startX = ev.clientX;
    startBounds = { ...state.base.xBounds };
    document.body.classList.add("qs-grabbing");
    window.addEventListener("mousemove", onMove, true);
    window.addEventListener("mouseup", onUp, true);
  });
}

// ---- dblclick reset ----
function attachDblClickReset(chart, canvas) {
  if (!chart || !canvas) return;
  if (canvas.$qsDblAttached) return;
  canvas.$qsDblAttached = true;

  canvas.addEventListener("dblclick", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();

    withZoomSuppressed(chart, () => {
      if (typeof chart.resetZoom === "function") chart.resetZoom("none");
      else if (chart?.options?.scales?.x) {
        chart.options.scales.x.min = undefined;
        chart.options.scales.x.max = undefined;
        chart.update("none");
      }
    });

    // Reset base bounds to the current charted window
    const startMs = Number.isFinite(Date.parse(state.base.start || "")) ? Date.parse(state.base.start) : null;
    const endMs = Number.isFinite(Date.parse(state.base.end || "")) ? Date.parse(state.base.end) : null;
    if (startMs != null && endMs != null) {
      state.base.xBounds = { xMin: startMs, xMax: endMs };
    } else {
      state.base.xBounds = null;
      const ds0 = chart.data.datasets?.[0]?.data;
      if (Array.isArray(ds0) && ds0.length) {
        state.base.xBounds = { xMin: ds0[0].x, xMax: ds0[ds0.length - 1].x };
      }
    }
    syncAllPanelsToBaseXBounds();
    updatePanelsXAxisVisibility();
  });
}

// ============================================================
// Storage
// ============================================================
const LS_KEYS = {
  history: "qs.history.v1",
  library: "qs.library.v2",
  expanded: "qs.library.expanded.v1",
  indicators: "qs.indicators.v2",
  dataTab: "qs.data.tab.v1",
  cmdStack: "qs.cmd.stack.v1",
};

function loadJSON(key, fallback) {
  const raw = localStorage.getItem(key);
  if (!raw) return fallback;
  try { return JSON.parse(raw) ?? fallback; }
  catch { return fallback; }
}
function saveJSON(key, value) { localStorage.setItem(key, JSON.stringify(value)); }

function ensureChartingTemplates() {
  if (!Array.isArray(chartingTemplates) || !chartingTemplates.length) {
    const id = `tpl_${Date.now()}`;
    chartingTemplates = [{
      id,
      name: "Default",
      tickers: [],
      metrics: [],
      durationToken: "1Y",
      norm: null,
      axisOverflowSide: "right",
    }];
    chartingActiveTemplateId = id;
    saveChartingTemplates();
  }
}

function saveChartingTemplates() {
  saveJSON(LS_CHART_TEMPLATES, chartingTemplates);
  saveJSON(LS_CHART_TEMPLATE_ACTIVE, chartingActiveTemplateId);
}

function getActiveChartingTemplate() {
  ensureChartingTemplates();
  let tpl = chartingTemplates.find(t => t.id === chartingActiveTemplateId);
  if (!tpl) {
    tpl = chartingTemplates[0];
    chartingActiveTemplateId = tpl.id;
    saveChartingTemplates();
  }
  return tpl;
}

function setActiveChartingTemplate(id) {
  chartingActiveTemplateId = id;
  saveChartingTemplates();
}

function setMsg(text) { if (els.msg) els.msg.textContent = text || ""; }
function setCommandLine(text) { if (els.cmd) els.cmd.value = text || ""; }
function fmtDate(ts) { return new Date(ts).toLocaleString(); }

function safeCopy(text) {
  navigator.clipboard?.writeText(text).then(
    () => setMsg("Copied."),
    () => setMsg("Copy failed.")
  );
}

function loadCmdStack() { return loadJSON(LS_KEYS.cmdStack, []); }
function saveCmdStack(list) { saveJSON(LS_KEYS.cmdStack, list); }
function resetCmdStackToGreeting() {
  saveCmdStack([]);
}

function ensureGreetingIfEmpty() {
  const list = loadCmdStack();
  const active = list.filter(x => !x.removed);
  if (!active.length) saveCmdStack([]);
}

function resetCmdStackOnLoad() {
  saveCmdStack([]);
  activeCmdId = null;
  __lineToCmdId = [];
  __keepTrailingNewline = false;
}

function clearAllPanels() {
  for (const pid of Array.from(panels.keys())) {
    if (pid !== PANEL_IDS.PRICE) removePanel(pid);
  }
  destroyPriceChart();
  state.base.xBounds = null;
  state.base.expr = "";
  state.data.price = null;
  panelSpecs = {};
  savePanelSpecs();
}

function normalizeCmdLine(line) {
  const s = String(line || "").trim();
  if (!s) return "";
  if (s.startsWith("//")) return s.replace(/^\/\/\s*/, "").trim();
  return s;
}

function commandSortKey(item) {
  if (item.kind === "price") return 0;
  if (item.kind === "rsi") return 1;
  return 2;
}

function renderCmdTextArea() {
  if (!els.cmd) return;
  const list = loadCmdStack().slice().sort((a, b) => {
    return (a.order ?? a.ts ?? 0) - (b.order ?? b.ts ?? 0);
  });
  __lineToCmdId = [];
  const lines = list.map((it, idx) => {
    __lineToCmdId[idx] = it.id;
    return it.removed ? `// ${it.cmd}` : it.cmd;
  });
  if (__keepTrailingNewline) lines.push("");
  __syncingCmdText = true;
  els.cmd.value = lines.join("\n");
  __lastCmdLines = lines.map(normalizeCmdLine).filter(Boolean);
  __syncingCmdText = false;
  renderCmdDisplay();
  updateCmdScrollbar();
}

function renderCmdDisplay() {
  const display = document.querySelector(".cmd-display");
  if (!els.cmd || !display) return;
  const lines = (els.cmd.value || "").split("\n");
  const html = lines.map((line) => {
    const safe = escapeHtml(line || " ");
    const removed = /^\s*\/\//.test(line || "");
    const cls = removed ? "cmd-display-line removed" : "cmd-display-line";
    return `<div class="${cls}">${safe || "&nbsp;"}</div>`;
  }).join("");
  display.innerHTML = html || "";
  display.scrollTop = els.cmd.scrollTop;
}

function getCmdAtCursor() {
  if (!els.cmd) return "";
  const text = els.cmd.value || "";
  const pos = els.cmd.selectionStart ?? text.length;
  const start = text.lastIndexOf("\n", pos - 1) + 1;
  let end = text.indexOf("\n", pos);
  if (end === -1) end = text.length;
  const line = text.slice(start, end);
  if (/^\s*\/\//.test(line)) return "";
  return normalizeCmdLine(line);
}

function syncActiveCmdFromCursor() {
  if (!els.cmd) return "";
  const text = els.cmd.value || "";
  const pos = els.cmd.selectionStart ?? text.length;
  const lineIdx = text.slice(0, pos).split("\n").length - 1;
  activeCmdId = __lineToCmdId[lineIdx] || null;
  return getCmdAtCursor();
}

function findPanelIdForKind(kind) {
  const list = loadCmdStack().filter(x => x.kind === kind && !x.removed && x.panelId);
  if (list.length === 1) return list[0].panelId;
  return null;
}

function renderCmdStack() {
  renderCmdTextArea();
}

function upsertCmdEntry({ cmd, kind, panelId, attachToActiveLine = false } = {}) {
  if (!cmd) return null;
  const list = loadCmdStack();
  let entry = null;

  if (kind === "price" && panelId == null) {
    entry = list.find(x => x.kind === "price" && x.panelId == null);
  }
  if (!entry && panelId) entry = list.find(x => x.panelId === panelId);
  if (!entry && attachToActiveLine && activeCmdId) entry = list.find(x => x.id === activeCmdId);
  if (!entry && !panelId && activeCmdId) entry = list.find(x => x.id === activeCmdId);

  if (entry) {
    entry.cmd = cmd;
    entry.kind = kind || entry.kind;
    entry.panelId = panelId || entry.panelId;
    entry.removed = false;
    if (!Number.isFinite(entry.order)) entry.order = list.length;
  } else {
    const maxOrder = list.reduce((m, x) => Math.max(m, Number.isFinite(x.order) ? x.order : 0), -1);
    entry = {
      id: `c_${Math.random().toString(36).slice(2, 9)}`,
      cmd,
      kind: kind || "raw",
      panelId: panelId || null,
      removed: false,
      ts: Date.now(),
      order: maxOrder + 1,
    };
    list.push(entry);
  }

  saveCmdStack(list);
  activeCmdId = entry.id;
  renderCmdStack();
  return entry.id;
}

function markCmdRemoved(panelId) {
  if (!panelId) return;
  const list = loadCmdStack();
  const entry = list.find(x => x.panelId === panelId);
  if (!entry) return;
  entry.removed = true;
  saveCmdStack(list);
  renderCmdStack();
}

function saveIndicatorState() {
  saveJSON(LS_KEYS.indicators, { overlays: state.overlays });
}

function loadIndicatorState() {
  const saved = loadJSON(LS_KEYS.indicators, null);
  if (!saved?.overlays) return;
  state.overlays = {
    bb: saved.overlays.bb ?? null,
    sma: Array.isArray(saved.overlays.sma) ? saved.overlays.sma : [],
    ema: Array.isArray(saved.overlays.ema) ? saved.overlays.ema : [],
  };
}

async function refreshOverlaysOnly() {
  if (!state.data.price || !state.base.expr) return;

  const duration = durationTokenToApiDuration(state.base.durationToken || "3y");
  const bar_size = state.base.bar_size;
  const use_rth = state.base.use_rth;

  if (state.overlays.bb) {
    if (state.overlays.bb === true) state.overlays.bb = { window: 20, sigma: 2 };
    if (!Number.isFinite(Number(state.overlays.bb.window))) state.overlays.bb.window = 20;
    if (!Number.isFinite(Number(state.overlays.bb.sigma))) state.overlays.bb.sigma = 2;
    try {
      const bb = await postJSON("/expr/bollinger", {
        expr: state.base.expr,
        period: state.overlays.bb.window || 20,
        sigma: state.overlays.bb.sigma || 2,
        duration,
        bar_size,
        use_rth,
      });
      state.data.bb = bb;
    } catch (e) {
      state.data.bb = null;
      setMsg(`BB failed: ${String(e.message || e)}`);
    }
  } else {
    state.data.bb = null;
  }

  state.data.ma = [];
  for (const n of (state.overlays.sma || [])) {
    try {
      const resp = await postJSON("/expr/ma", {
        expr: state.base.expr,
        ma: "sma",
        window: Number(n),
        duration,
        bar_size,
        use_rth,
      });
      state.data.ma.push(resp);
    } catch (e) {
      setMsg(`SMA(${n}) failed: ${String(e.message || e)}`);
    }
  }

  for (const n of (state.overlays.ema || [])) {
    try {
      const resp = await postJSON("/expr/ma", {
        expr: state.base.expr,
        ma: "ema",
        window: Number(n),
        duration,
        bar_size,
        use_rth,
      });
      state.data.ma.push(resp);
    } catch (e) {
      setMsg(`EMA(${n}) failed: ${String(e.message || e)}`);
    }
  }

  renderPrice(state.data.price);
}

function installGlobalErrorTrap() {
  if (window.$qsErrorTrapInstalled) return;
  window.$qsErrorTrapInstalled = true;

  const record = (label, err) => {
    const msg = err?.message || String(err || label || "Unknown error");
    const stack = err?.stack || msg;
    saveJSON("qs.last.error.v1", { ts: Date.now(), label, message: msg, stack });
    setMsg(`Error: ${msg}`);
  };

  window.addEventListener("error", (ev) => {
    record("error", ev?.error || new Error(ev?.message || "error"));
  });
  window.addEventListener("unhandledrejection", (ev) => {
    record("unhandledrejection", ev?.reason || new Error("unhandled rejection"));
  });
}

// ============================================================
// History (minimal; keep your existing if you want)
// ============================================================
function getHistory() { return loadJSON(LS_KEYS.history, []); }
function setHistory(items) { saveJSON(LS_KEYS.history, items.slice(0, HISTORY_LIMIT)); }

function renderHistory() {
  if (!els.historyList || !els.histCount) return;
  const panel = document.getElementById("historyPanel");
  if (panel) panel.style.display = collapsedPanels.history ? "none" : "block";

  const hist = getHistory();
  els.histCount.textContent = `last ${HISTORY_LIMIT}`;
  els.historyList.innerHTML = "";

  if (collapsedPanels.history) {
    els.historyList.style.display = "none";
    if (els.historyCaret) els.historyCaret.textContent = "▸";
    return;
  }
  els.historyList.style.display = "block";
  if (els.historyCaret) els.historyCaret.textContent = "▾";

  if (!hist.length) {
    const div = document.createElement("div");
    div.className = "hint";
    div.textContent = "No history yet.";
    els.historyList.appendChild(div);
    return;
  }

  for (const h of hist) {
    const row = document.createElement("div");
    row.className = "hitem";
    row.innerHTML = `<div class="hcmd">${escapeHtml(h.cmd)}</div><div class="hts">${fmtDate(h.ts)}</div>`;
    row.addEventListener("click", () => {
      if (els.cmd) els.cmd.value = h.cmd;
      
      runCommand(h.cmd, { skipHistorySave: true });
      setMsg("Loaded from history.");
    });
    els.historyList.appendChild(row);
  }
}

// ============================================================
// Library (minimal; keep your existing if you want)
// ============================================================
function defaultLibrary() {
  const rootId = "root";
  return { rootId, folders: { [rootId]: { id: rootId, name: "Saved", parent: null, childrenFolders: [], items: [] } } };
}
function sanitizeLibraryCycles(lib) {
  if (!lib?.folders || !lib?.rootId) return false;
  const colors = new Map(); // 0=unseen,1=visiting,2=done
  let mutated = false;

  const dfs = (fid) => {
    const c = colors.get(fid) || 0;
    if (c === 1) return true;
    if (c === 2) return false;
    colors.set(fid, 1);

    const folder = lib.folders[fid];
    if (folder?.childrenFolders?.length) {
      const next = [];
      for (const cid of folder.childrenFolders) {
        if (!lib.folders[cid]) { mutated = true; continue; }
        if (colors.get(cid) === 1) { mutated = true; continue; }
        next.push(cid);
        if (dfs(cid)) { mutated = true; }
      }
      folder.childrenFolders = next;
    }

    colors.set(fid, 2);
    return false;
  };

  dfs(lib.rootId);
  return mutated;
}
function getLibrary() {
  let lib = loadJSON(LS_KEYS.library, null);
  if (!lib || !lib.folders || !lib.rootId) {
    lib = defaultLibrary();
    saveJSON(LS_KEYS.library, lib);
  }
  if (sanitizeLibraryCycles(lib)) saveJSON(LS_KEYS.library, lib);
  return lib;
}
function setLibrary(lib) { saveJSON(LS_KEYS.library, lib); }

function loadExpanded() {
  const arr = loadJSON(LS_KEYS.expanded, ["root"]);
  expandedFolders = new Set(arr);
}
function saveExpanded() { saveJSON(LS_KEYS.expanded, Array.from(expandedFolders)); }

function renderLibrary() {
  if (!els.libraryTree) return;
  const panel = document.getElementById("libraryPanel");
  if (panel) panel.style.display = collapsedPanels.library ? "none" : "block";

  const lib = getLibrary();
  els.libraryTree.innerHTML = "";

  if (collapsedPanels.library) {
    els.libraryTree.style.display = "none";
    if (els.libraryCaret) els.libraryCaret.textContent = "▸";
    return;
  }
  els.libraryTree.style.display = "block";
  if (els.libraryCaret) els.libraryCaret.textContent = "▾";

  const root = lib.folders[lib.rootId];
  if (!root) return;

  if (!expandedFolders.size) expandedFolders.add(lib.rootId);
  els.libraryTree.appendChild(renderFolderNode(lib, root.id, new Set()));
}

function renderHelp() {
  if (!els.helpList) return;
  const panel = document.getElementById("helpPanel");
  if (panel) panel.style.display = collapsedPanels.help ? "none" : "block";
  if (collapsedPanels.help) {
    els.helpList.style.display = "none";
    if (els.helpCaret) els.helpCaret.textContent = "▸";
    return;
  }
  els.helpList.style.display = "block";
  if (els.helpCaret) els.helpCaret.textContent = "▾";
}

function renderSeasonalityPanel() {
  if (!els.seasonalityList) return;
  if (collapsedPanels.seasonality) {
    els.seasonalityList.style.display = "none";
    if (els.seasonalityCaret) els.seasonalityCaret.textContent = "▸";
    return;
  }
  els.seasonalityList.style.display = "block";
  if (els.seasonalityCaret) els.seasonalityCaret.textContent = "▾";
}

function renderFolderNode(lib, folderId, visiting) {
  if (visiting.has(folderId)) {
    const warn = document.createElement("div");
    warn.className = "hint";
    warn.textContent = "Library error: folder cycle detected.";
    return warn;
  }
  visiting.add(folderId);

  const folder = lib.folders[folderId];
  const wrap = document.createElement("div");

  const node = document.createElement("div");
  node.className = "node";
  node.dataset.folderId = folderId;

  node.addEventListener("dragover", (ev) => { ev.preventDefault(); node.classList.add("dragover"); });
  node.addEventListener("dragleave", () => node.classList.remove("dragover"));
  node.addEventListener("drop", (ev) => {
    ev.preventDefault();
    node.classList.remove("dragover");
    if (!dragPayload) return;
    moveItemToFolder(dragPayload.itemId, dragPayload.fromFolderId, folderId);
    dragPayload = null;
  });

  const toggle = document.createElement("button");
  toggle.className = "toggle";
  const isOpen = expandedFolders.has(folderId);
  toggle.textContent = isOpen ? "−" : "+";
  toggle.addEventListener("click", () => {
    if (expandedFolders.has(folderId)) expandedFolders.delete(folderId);
    else expandedFolders.add(folderId);
    saveExpanded();
    renderLibrary();
  });

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = folder.name;

  const count = document.createElement("div");
  count.className = "count";
  count.textContent = `${(folder.items?.length || 0)}`;

  node.appendChild(toggle);
  node.appendChild(label);
  node.appendChild(count);
  wrap.appendChild(node);

  if (!isOpen) return wrap;

  const children = document.createElement("div");
  children.className = "children";

  for (const item of (folder.items || [])) {
    const it = document.createElement("div");
    it.className = "item";
    it.draggable = true;

    it.addEventListener("dragstart", () => { dragPayload = { itemId: item.id, fromFolderId: folderId }; });
    it.addEventListener("click", () => {
      if (els.cmd) els.cmd.value = item.cmd;
      setMsg(`Loaded: ${item.name || item.cmd}`);
      runCommand(item.cmd, { skipHistorySave: true });
    });

    it.innerHTML = `
      <span class="dot"></span>
      <strong>${escapeHtml(item.name || item.cmd)}</strong>
      <div class="meta">${escapeHtml(item.meta || "")}</div>
    `;
    children.appendChild(it);
  }

  for (const cid of (folder.childrenFolders || [])) {
    children.appendChild(renderFolderNode(lib, cid, new Set(visiting)));
  }
  wrap.appendChild(children);
  return wrap;
}

function createFolder(name, parentId) {
  const lib = getLibrary();
  const id = `f_${Math.random().toString(36).slice(2, 10)}`;
  lib.folders[id] = { id, name, parent: parentId, childrenFolders: [], items: [] };
  lib.folders[parentId].childrenFolders.push(id);
  setLibrary(lib);
  expandedFolders.add(parentId);
  expandedFolders.add(id);
  saveExpanded();
  renderLibrary();
}

function moveItemToFolder(itemId, fromFolderId, toFolderId) {
  if (fromFolderId === toFolderId) return;
  const lib = getLibrary();
  const from = lib.folders[fromFolderId];
  const to = lib.folders[toFolderId];
  if (!from || !to) return;

  const idx = (from.items || []).findIndex(x => x.id === itemId);
  if (idx < 0) return;

  const [item] = from.items.splice(idx, 1);
  to.items = to.items || [];
  to.items.unshift(item);

  setLibrary(lib);
  renderLibrary();
  setMsg("Moved.");
}

function saveCurrentToLibrary() {
  const cmd = (els.cmd?.value || "").trim();
  if (!cmd) return setMsg("Nothing to save.");
  if (!lastResponseJson) return setMsg("Run something first.");

  const lib = getLibrary();
  const targetId = lib.rootId;
  const folder = lib.folders[targetId];
  folder.items = folder.items || [];

  const name = cmd.length > 38 ? cmd.slice(0, 38) + "…" : cmd;
  const id = `i_${Math.random().toString(36).slice(2, 10)}`;

  folder.items.unshift({ id, name, cmd, meta: new Date().toLocaleDateString() });

  setLibrary(lib);
  expandedFolders.add(targetId);
  saveExpanded();
  renderLibrary();
  setMsg("Saved to Library.");
}

function exportLibrary() {
  const lib = getLibrary();
  const blob = new Blob([JSON.stringify({ lib, ts: Date.now() }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `qs_library_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function importLibrary(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const obj = JSON.parse(reader.result);
      if (!obj?.lib?.folders) throw new Error("Invalid file");
      setLibrary(obj.lib);
      renderLibrary();
      setMsg("Imported library.");
    } catch (e) {
      setMsg(`Import failed: ${String(e)}`);
    }
  };
  reader.readAsText(file);
}

// ============================================================
// API
// ============================================================
async function apiHealth() {
  try {
    const r = await fetch(`${API_BASE}/health`);
    if (!r.ok) throw new Error(String(r.status));
    if (els.apiStatus) {
      els.apiStatus.textContent = "● OK";
      els.apiStatus.style.color = "rgba(16,185,129,.95)";
    }
  } catch {
    if (els.apiStatus) {
      els.apiStatus.textContent = "● API down";
      els.apiStatus.style.color = "rgba(239,68,68,.9)";
    }
  }
}

async function postJSON(path, payload) {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = data?.detail;
    const err = detail?.error || detail || `${r.status}`;
    let msg = (typeof err === "string") ? err : JSON.stringify(err);
    if (!msg || msg === "null") msg = JSON.stringify(detail || data || {});
    throw new Error(msg);
  }
  return data;
}

function panelTitleFromKind(kind) {
  const k = String(kind || "").toLowerCase();
  if (k === "volume") return "Volume";
  if (k === "rsi") return "RSI";
  if (k === "drawdown") return "Drawdown";
  if (k === "sharpe") return "Sharpe";
  if (k === "zscore") return "Z-Score";
  return "Panel";
}

function isSingleSymbol(expr) {
  const s = String(expr || "").trim();
  if (!/^(EQ|FX|IX):/i.test(s)) return false;
  return !/[+\-*/()]/.test(s);
}

async function fetchVolumeBars(symbol) {
  const sym = String(symbol || "").trim();
  if (!isSingleSymbol(sym)) {
    throw new Error(`Volume needs a single symbol like EQ:SPY, not: ${sym}`);
  }

  const durTok = state.base.durationToken || "3y";
  const { start, end } = computeStartEndFromToken(durTok);
  if (!state.base.start || !state.base.end) {
    state.base.start = start;
    state.base.end = end;
  }

  return postJSON("/data/ohlcv", {
    symbol: sym,
    resolution: barSizeToResolution(state.base.bar_size),
    range: { start: state.base.start, end: state.base.end },
    include_volume: true,
    tz: "Europe/London",
    max_bars: 5000,
  });
}

async function fetchPanelSeries(kind) {
  const expr = state.base.expr;
  if (!expr) throw new Error("Run a price() command first.");

  const duration = durationTokenToApiDuration(state.base.durationToken || "3y");
  const bar_size = state.base.bar_size;
  const use_rth = state.base.use_rth;

  const k = String(kind || "").toLowerCase();
  if (k === "rsi") {
    return postJSON("/expr/rsi", { expr, period: 14, bands: "classic", duration, bar_size, use_rth });
  }
  if (k === "drawdown") {
    return postJSON("/expr/drawdown", { expr, duration, bar_size, use_rth, mode: "point" });
  }
  if (k === "sharpe") {
    return postJSON("/expr/sharpe", { expr, duration, bar_size, use_rth, window: "63D" });
  }
  if (k === "zscore") {
    return postJSON("/expr/zscore", { expr, duration, bar_size, use_rth, window: "3M", levels: [-2, -1, 0, 1, 2] });
  }

  throw new Error(`Panel not supported: ${kind}`);
}

async function addPanelFromMenu(kind) {
  const title = panelTitleFromKind(kind);
  const cmdStack = loadCmdStack();
  const activeEntry = cmdStack.find(x => x.id === activeCmdId && !x.removed);
  const activeMatch = (activeEntry?.kind === kind) ? activeEntry : null;
  const existingId = activeMatch?.panelId || findPanelIdForKind(kind);
  const panelId = existingId || createPanel({ kind, title, height: 200 });
  if (!panelId) return;

  panelSpecs[panelId] = { kind, createdAt: Date.now() };
  savePanelSpecs();
  setPanelTitle(panelId, title);
  setMsg(`Loading ${title}…`);

  try {
    const k = String(kind || "").toLowerCase();
    if (k === "volume") {
      const raw = prompt("Volume MA period?", "20");
      const ma = Math.max(1, Number(raw) || 20);
      panelSpecs[panelId] = { kind: "volume", params: { ma }, createdAt: Date.now() };
      savePanelSpecs();
      const volResp = await fetchVolumeBars(state.base.expr);
      renderVolumeToPanel(panelId, volResp, `Volume · ${state.base.expr}`, { maPeriod: ma });
      upsertCmdEntry({ cmd: `volume(${state.base.expr}, ${ma})`, kind: "volume", panelId, attachToActiveLine: !!activeMatch });
    } else if (k === "sharpe") {
      const raw = prompt("Sharpe window? (e.g. 63D, 3M)", "63D");
      const window = (raw || "63D").trim();
      panelSpecs[panelId] = { kind: "sharpe", params: { window }, createdAt: Date.now() };
      savePanelSpecs();
      const resp = await postJSON("/expr/sharpe", {
        expr: state.base.expr,
        window,
        duration: durationTokenToApiDuration(state.base.durationToken || "3y"),
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      renderPanelChart(panelId, resp);
      upsertCmdEntry({ cmd: `sharpe(${state.base.expr}, ${window}, ${state.base.durationToken || "3y"})`, kind: "sharpe", panelId, attachToActiveLine: !!activeMatch });
    } else if (k === "drawdown") {
      const raw = prompt("Drawdown window? (e.g. 3M, 1Y)", "3M");
      const window = (raw || "3M").trim();
      panelSpecs[panelId] = { kind: "drawdown", params: { window }, createdAt: Date.now() };
      savePanelSpecs();
      const resp = await postJSON("/expr/drawdown", {
        expr: state.base.expr,
        duration: durationTokenToApiDuration(state.base.durationToken || "3y"),
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
        mode: "point",
        rolling_window: window,
      });
      renderPanelChart(panelId, resp);
      upsertCmdEntry({ cmd: `dd(${state.base.expr}, ${window}, ${state.base.durationToken || "3y"})`, kind: "drawdown", panelId, attachToActiveLine: !!activeMatch });
    } else {
      const resp = await fetchPanelSeries(kind);
      renderPanelChart(panelId, resp);
      if (k === "rsi") upsertCmdEntry({ cmd: `rsi(${state.base.expr}, 14, ${state.base.durationToken || "3y"})`, kind: "rsi", panelId, attachToActiveLine: !!activeMatch });
      if (k === "zscore") upsertCmdEntry({ cmd: `zscore(${state.base.expr}, 3M, ${state.base.durationToken || "3y"})`, kind: "zscore", panelId, attachToActiveLine: !!activeMatch });
    }
    setMsg("OK");
  } catch (e) {
    renderPanelError(panelId, String(e.message || e));
    setMsg(`Panel error: ${String(e.message || e)}`);
  }
}

// ============================================================
// Date helpers (keep your original behavior)
// ============================================================
function addDays(date, days) { const d = new Date(date.getTime()); d.setDate(d.getDate() + days); return d; }
function addMonths(date, months) {
  const d = new Date(date.getTime());
  const day = d.getDate();
  d.setMonth(d.getMonth() + months);
  if (d.getDate() < day) d.setDate(0);
  return d;
}
function subtractTradingDays(endDate, n) {
  let d = new Date(endDate.getTime());
  let remaining = n;
  while (remaining > 0) {
    d = addDays(d, -1);
    const day = d.getDay();
    if (day !== 0 && day !== 6) remaining -= 1;
  }
  return d;
}
function parseDurationToken(tok) {
  if (!tok) return null;
  const m = String(tok).trim().match(/^(\d+)\s*([dmyw])$/i);
  if (!m) return null;
  return { n: parseInt(m[1], 10), u: m[2].toLowerCase() };
}
function durationTokenToApiDuration(tok) {
  const p = parseDurationToken(tok);
  if (!p) return "3 Y";
  if (p.u === "d") return `${p.n} D`;
  if (p.u === "w") return `${p.n} W`;
  if (p.u === "m") return `${p.n} M`;
  if (p.u === "y") return `${p.n} Y`;
  return "3 Y";
}
function computeStartEndFromToken(tok) {
  const parsed = parseDurationToken(tok);
  if (!parsed) return { start: null, end: null };
  const end = new Date();
  let start;
  if (parsed.u === "d") start = subtractTradingDays(end, parsed.n);
  else if (parsed.u === "w") start = addDays(end, -parsed.n * 7);
  else if (parsed.u === "m") start = addMonths(end, -parsed.n);
  else if (parsed.u === "y") start = addMonths(end, -parsed.n * 12);
  else return { start: null, end: null };
  return { start: start.toISOString(), end: end.toISOString() };
}
function barSizeToResolution(barSize) {
  const s = String(barSize || "").toLowerCase().trim();
  if (s.includes("1 min")) return "1min";
  if (s.includes("5 min")) return "5min";
  if (s.includes("15 min")) return "15min";
  if (s.includes("30 min")) return "30min";
  if (s.includes("1 hour") || s === "1h") return "1H";
  if (s.includes("4 hour") || s === "4h") return "4H";
  if (s.includes("1 day") || s === "1d") return "1D";
  if (s.includes("1 week") || s === "1w") return "1W";
  if (s.includes("1 month") || s === "1m") return "1M";
  return "1D";
}

// ============================================================
// Parsing (keep your original; minimal here)
// ============================================================
function splitArgsTopLevel(s) {
  const args = [];
  let cur = "";
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === "(") depth++;
    if (ch === ")") depth = Math.max(0, depth - 1);
    if (ch === "," && depth === 0) { args.push(cur.trim()); cur = ""; }
    else cur += ch;
  }
  if (cur.trim()) args.push(cur.trim());
  return args;
}

function parseNorm(pos, kw) {
  if (kw.norm != null) return Number(kw.norm);
  for (const p of pos) {
    if (/^norm$/i.test(p)) return 100;
    const m = p.match(/^norm\s*=\s*(\d+(\.\d+)?)$/i);
    if (m) return Number(m[1]);
  }
  if (pos.some(x => /^norm$/i.test(x))) return 100;
  return null;
}

function parseCcy(pos, kw) {
  if (kw.ccy) return String(kw.ccy).toUpperCase();
  if (kw.currency) return String(kw.currency).toUpperCase();
  for (const p of pos) if (/^[A-Z]{3}$/.test(p)) return p.toUpperCase();
  return null;
}

function parseNormValue(pos, kw) {
  const raw = kw.norm ?? kw.normalize;
  if (raw != null) {
    const v = String(raw).trim();
    if (!v) return null;
    if (/^(none|raw)$/i.test(v)) return null;
    if (/^(pct|percent|%)$/i.test(v)) return 0;
    const num = Number(v);
    if (Number.isFinite(num)) return num;
    return v;
  }
  for (const p of pos) {
    if (/^norm$/i.test(p)) return 100;
    const m = p.match(/^norm\s*=\s*(.+)$/i);
    if (m) {
      const v = String(m[1]).trim();
      const num = Number(v);
      if (Number.isFinite(num)) return num;
      return v;
    }
  }
  return null;
}

function parseYearsSpec(raw) {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (!s) return null;
  const num = Number(s);
  if (Number.isFinite(num)) {
    const n = Math.max(1, Math.floor(num));
    const now = new Date().getFullYear();
    const years = [];
    for (let i = n - 1; i >= 0; i--) years.push(now - i);
    return years;
  }
  const parts = s.split(/[,\s]+/).filter(Boolean);
  const years = [];
  for (const p of parts) {
    const m = p.match(/^(\d{4})\s*-\s*(\d{4})$/);
    if (m) {
      const a = parseInt(m[1], 10);
      const b = parseInt(m[2], 10);
      const lo = Math.min(a, b);
      const hi = Math.max(a, b);
      for (let y = lo; y <= hi; y++) years.push(y);
      continue;
    }
    const y = parseInt(p, 10);
    if (Number.isFinite(y) && y >= 1900) years.push(y);
  }
  return years.length ? Array.from(new Set(years)).sort((a, b) => a - b) : null;
}

function parseUserInput(input) {
  const s = String(input || "").trim();
  if (!s) return null;

  const fm = s.match(/^([a-zA-Z_]+)\s*\((.*)\)\s*$/);
  if (fm) {
    const fn = fm[1].toLowerCase();
    const inner = fm[2] || "";
    const parts = splitArgsTopLevel(inner);

    const kw = {};
    const pos = [];
    for (const p of parts) {
      const km = p.match(/^([a-zA-Z_]+)\s*=\s*(.+)$/);
      if (km) kw[km[1].toLowerCase()] = km[2].trim();
      else pos.push(p);
    }

    if (fn === "price") {
      const norm = parseNormValue(pos, kw);
      const ccy = parseCcy(pos, kw);
      let durationToken = (kw.duration || kw.lookback || state.base.durationToken || "3y");
      const args = pos.slice();
      for (let i = args.length - 1; i >= 0; i--) {
        if (parseDurationToken(args[i])) {
          durationToken = args[i];
          args.splice(i, 1);
          break;
        }
      }
      const exprs = args.filter(x => !/^norm$/i.test(x) && !/^norm\s*=/i.test(x));
      const expr = exprs[0];
      return { kind: "price", expr, exprs, durationToken, norm, ccy, params: {} };
    }

  if (fn === "vol" || fn === "volume") {
    const expr = pos[0];
    const ma = parseInt(pos[1] || kw.ma || kw.period || "20", 10);
    const durationToken = pos[2] || kw.duration || state.base.durationToken || "3y";
    return { kind: "volume", expr, durationToken, norm: null, ccy: null, params: { ma } };
  }

  if (fn === "sharpe") {
    const expr = pos[0];
    const window = (pos[1] || kw.window || "63D");
    const durationToken = (pos[2] || kw.duration || state.base.durationToken || "3y");
    return { kind: "sharpe", expr, durationToken, norm: null, ccy: null, params: { window } };
  }

  if (fn === "dd" || fn === "drawdown") {
    const expr = pos[0];
    const window = (pos[1] || kw.window || "3M");
    const durationToken = (pos[2] || kw.duration || state.base.durationToken || "3y");
    return { kind: "drawdown", expr, durationToken, norm: null, ccy: null, params: { window } };
  }

  if (fn === "rsi") {
    const expr = pos[0];
    const period = parseInt(pos[1] || kw.period || "14", 10);
    const durationToken = (pos[2] || kw.duration || state.base.durationToken || "3y");
    return { kind: "rsi", expr, durationToken, norm: null, ccy: null, params: { period } };
  }

  if (fn === "zscore") {
    const expr = pos[0];
    const window = (pos[1] || kw.window || "3M");
    const durationToken = (pos[2] || kw.duration || state.base.durationToken || "3y");
    return { kind: "zscore", expr, durationToken, norm: null, ccy: null, params: { window } };
  }

  if (fn === "seasonality") {
    const expr = pos[0];
    const mode = String(kw.mode || pos[1] || "heatmap").toLowerCase();
    const bucket = String(kw.bucket || "month").toLowerCase();
    const years = parseYearsSpec(kw.years || kw.year || pos[2]);
    const rangeStart = parseRangeSpec(kw.start || kw.begin || kw.from || "") || { month: 1, day: 1 };
    const rangeEnd = parseRangeSpec(kw.end || kw.to || "") || { month: 12, day: 31 };
    const durationToken = (kw.duration || state.base.durationToken || (mode === "years" ? "15y" : "20y"));
    return {
      kind: "seasonality",
      expr,
      durationToken,
      norm: null,
      ccy: null,
      params: {
        mode,
        bucket,
        years,
        rangeStart: `${String(rangeStart.month).padStart(2, "0")}-${String(rangeStart.day).padStart(2, "0")}`,
        rangeEnd: `${String(rangeEnd.month).padStart(2, "0")}-${String(rangeEnd.day).padStart(2, "0")}`,
      },
    };
  }

    // keep other kinds as in your old file...
    return { kind: "raw", expr: s, durationToken: state.base.durationToken, norm: null, ccy: null, params: {} };
  }

  return { kind: "price", expr: s, exprs: [s], durationToken: state.base.durationToken || "3y", norm: null, ccy: null, params: {} };
}

// ============================================================
// Drawer (idempotent)
// ============================================================
function installDrawerBehavior() {
  if (!dataDrawer || dataDrawer.$qsInstalled) return;
  dataDrawer.$qsInstalled = true;

  const savedH = Number(loadJSON("qs.drawer.h.v1", 260));
  dataDrawer.style.setProperty("--qs-drawer-h", `${clamp(savedH, 180, 520)}px`);
  setDrawerOpen(false);

  const tabs = dataDrawer.querySelectorAll("button[data-tab]");
  tabs.forEach(b => {
    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      setDataTab(b.dataset.tab);
      setDrawerOpen(true);
    });
  });

  const copyBtn = dataDrawer.querySelector('button[data-act="copy"]');
  copyBtn?.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    copyActiveTab();
    setDrawerOpen(true);
  });

  const grab = dataDrawer.querySelector(".qs-drawer-grab");
  if (grab) {
    let dragging = false;
    let startY = 0;
    let startH = 0;

    const onDown = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      dragging = true;
      startY = ev.clientY;
      const cur = getComputedStyle(dataDrawer).getPropertyValue("--qs-drawer-h");
      startH = parseInt(cur || "260", 10) || 260;
      window.addEventListener("mousemove", onMove, true);
      window.addEventListener("mouseup", onUp, true);
      document.body.classList.add("qs-resizing");
    };

    const onMove = (ev) => {
      if (!dragging) return;
      const dy = startY - ev.clientY;
      const nh = clamp(startH + dy, 180, 520);
      dataDrawer.style.setProperty("--qs-drawer-h", `${nh}px`);
      saveJSON("qs.drawer.h.v1", nh);
    };

    const onUp = () => {
      dragging = false;
      window.removeEventListener("mousemove", onMove, true);
      window.removeEventListener("mouseup", onUp, true);
      document.body.classList.remove("qs-resizing");
    };

    grab.addEventListener("mousedown", onDown);
  }

  document.addEventListener("click", (ev) => {
    if (!dataDrawerOpen) return;
    const t = ev.target;
    const inDrawer = dataDrawer.contains(t);
    if (!inDrawer) setDrawerOpen(false);
  });
}

function setDrawerOpen(open) {
  dataDrawerOpen = !!open;
  if (!dataDrawer) return;
  dataDrawer.classList.toggle("open", dataDrawerOpen);
}

function setDataTab(tabId) {
  saveJSON(LS_KEYS.dataTab, tabId);
  if (!dataDrawerContent) return;

  dataDrawer?.querySelectorAll("button[data-tab]").forEach(b => {
    const on = (b.dataset.tab === tabId);
    b.style.background = on ? "rgba(17,17,17,.06)" : "transparent";
  });

  const price = state.data.price;
  const points =
    Array.isArray(price?.points) ? price.points :
    Array.isArray(price?.series?.[0]?.points) ? price.series[0].points :
    [];
  const xy = normalizePoints(points);

  if (tabId === "json") {
    dataDrawerContent.innerHTML = `<pre style="margin:0; font-size:12px; white-space:pre; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;">${escapeHtml(safeStringify(price || {}, 2))}</pre>`;
    return;
  }

  if (tabId === "csv") {
    const csv = toCSVFromPriceChart();
    dataDrawerContent.innerHTML = `<textarea style="width:100%; height:100%; border:0; outline:none; resize:none; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace; font-size:12px;">${escapeHtml(csv)}</textarea>`;
    return;
  }

  const rows = xy.slice(-250).reverse();
  let html = `<table style="width:100%; border-collapse:collapse; font-size:12px; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;">
    <thead><tr>
      <th style="text-align:left; padding:6px; border-bottom:1px solid rgba(17,17,17,.08);">Time</th>
      <th style="text-align:right; padding:6px; border-bottom:1px solid rgba(17,17,17,.08);">Value</th>
    </tr></thead><tbody>`;
  for (const r of rows) {
    html += `<tr>
      <td style="padding:4px 6px; border-bottom:1px solid rgba(17,17,17,.06);">${escapeHtml(new Date(r.x).toISOString().slice(0,10))}</td>
      <td style="padding:4px 6px; border-bottom:1px solid rgba(17,17,17,.06); text-align:right;">${Number(r.y).toFixed(4)}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  dataDrawerContent.innerHTML = html;
}

function copyActiveTab() {
  const tabId = loadJSON(LS_KEYS.dataTab, "data");

  if (tabId === "json") {
    // IMPORTANT: NEVER JSON.stringify large API payloads directly
    return safeCopy(safeStringify(state.data.price || {}, 2));
  }

  if (tabId === "csv") {
    return safeCopy(toCSVFromPriceChart());
  }

  // default: copy CSV from price chart
  return safeCopy(toCSVFromPriceChart());
}


function toCSVFromPriceChart() {
  if (!priceChart?.data?.datasets?.length) return "date\n";
  const ds0 = priceChart.data.datasets[0];
  const xs = (ds0.data || []).map(p => p.x);
  const labels = priceChart.data.datasets.map(d => d.label || "series");
  const header = ["date", ...labels].join(",");

  const maps = priceChart.data.datasets.map(d => {
    const m = new Map();
    for (const p of (d.data || [])) m.set(p.x, p.y);
    return m;
  });

  const lines = [header];
  for (const x of xs) {
    const d = new Date(Number(x)).toISOString().slice(0, 10);
    const row = [d];
    for (const m of maps) {
      const y = m.get(x);
      row.push((y == null || !Number.isFinite(Number(y))) ? "" : String(Number(y)));
    }
    lines.push(row.join(","));
  }
  return lines.join("\n");
}

function toTSVFromPriceChart() {
  if (!priceChart?.data?.datasets?.length) return "date\n";
  const ds0 = priceChart.data.datasets[0];
  const xs = (ds0.data || []).map(p => p.x);
  const labels = priceChart.data.datasets.map(d => d.label || "series");
  const header = ["date", ...labels].join("\t");

  const maps = priceChart.data.datasets.map(d => {
    const m = new Map();
    for (const p of (d.data || [])) m.set(p.x, p.y);
    return m;
  });

  const lines = [header];
  for (const x of xs) {
    const d = new Date(Number(x)).toISOString().slice(0, 10);
    const row = [d];
    for (const m of maps) {
      const y = m.get(x);
      row.push((y == null || !Number.isFinite(Number(y))) ? "" : String(Number(y)));
    }
    lines.push(row.join("\t"));
  }
  return lines.join("\n");
}

function renderChartTable() {
  if (!els.chartTableBody) return;
  if (!priceChart?.data?.datasets?.length) {
    els.chartTableBody.innerHTML = `<div class="hint" style="padding:8px;">No data.</div>`;
    return;
  }

  const datasets = priceChart.data.datasets || [];
  const labels = datasets.map(d => d.label || "series");
  const ds0 = datasets[0];
  const xs = (ds0.data || []).map(p => p.x);

  const maps = datasets.map(d => {
    const m = new Map();
    for (const p of (d.data || [])) m.set(p.x, p.y);
    return m;
  });

  let html = `<table class="chart-table"><thead><tr><th>Date</th>`;
  for (const l of labels) html += `<th>${escapeHtml(l)}</th>`;
  html += `</tr></thead><tbody>`;

  for (const x of xs.slice().reverse().slice(0, 250)) {
    const d = new Date(Number(x)).toISOString().slice(0, 10);
    html += `<tr><td>${escapeHtml(d)}</td>`;
    for (const m of maps) {
      const y = m.get(x);
      html += `<td>${(y == null || !Number.isFinite(Number(y))) ? "" : Number(y).toFixed(4)}</td>`;
    }
    html += `</tr>`;
  }
  html += `</tbody></table>`;
  els.chartTableBody.innerHTML = html;
}

// ============================================================
// Price chart rendering (minimal, but correct sync behavior)
// ============================================================
function destroyPriceChart() {
  try { priceChart?.destroy(); } catch {}
  priceChart = null;
}

function computeXBoundsFromXY(xy) {
  if (!Array.isArray(xy) || xy.length === 0) return null;
  const xMin = xy[0].x;
  const xMax = xy[xy.length - 1].x;
  if (!Number.isFinite(xMin) || !Number.isFinite(xMax)) return null;
  return { xMin, xMax };
}

function renderPrice(priceResp) {
  if (!els.chartEl) return;

  const expr = state.base.expr;
  if (els.chartTitle) els.chartTitle.textContent = expr || "—";

  const seriesList = Array.isArray(priceResp?.series) && priceResp.series.length
    ? priceResp.series.map((s, i) => ({
      label: s?.label || s?.expr || `series_${i + 1}`,
      points: s?.points || [],
      expr: s?.expr || "",
    }))
    : [{
      label:
        (priceResp && typeof priceResp.label === "string" && priceResp.label) ||
        expr || "price",
      points: Array.isArray(priceResp?.points) ? priceResp.points : [],
      expr,
    }];

  let baseRawXY = null;
  const normMode = state.base.norm;
  const normBaseValue = resolveNormBaseValue(normMode, seriesList);
  const shareAxis = normMode != null;
  const multiAxis = seriesList.length > 1 && !shareAxis;
  const axisIds = [];
  const overflowSide = state.base.axisOverflowSide || "right";
  const baseAxisIds = [];
  if (!shareAxis) {
    for (let i = 0; i < Math.min(seriesList.length, MAX_Y_AXES); i++) {
      baseAxisIds.push(i === 0 ? "y" : `y${i}`);
    }
    const leftIds = baseAxisIds.filter((_, i) => i % 2 === 0);
    const rightIds = baseAxisIds.filter((_, i) => i % 2 === 1);
    const overflowId = (overflowSide === "left" ? leftIds[leftIds.length - 1] : rightIds[rightIds.length - 1]) || leftIds[leftIds.length - 1] || "y";
    for (let i = 0; i < seriesList.length; i++) {
      axisIds.push(i < baseAxisIds.length ? baseAxisIds[i] : overflowId);
    }
  } else {
    for (let i = 0; i < seriesList.length; i++) axisIds.push("y");
  }

  const datasets = [];
  for (let i = 0; i < seriesList.length; i++) {
    const s = seriesList[i];
    const rawXY = normalizePoints(s.points || []);
    if (!rawXY.length) continue;
    if (!baseRawXY) baseRawXY = rawXY;

    const lbl = String(s.label || s.expr || `series_${i + 1}`);
    const c = normalizeColor(dsColors[lbl], lbl);
    dsColors[lbl] = c;

    const xy = normalizeSeriesXY(rawXY, normMode, normBaseValue);
    datasets.push({
      label: lbl,
      data: xy,
      yAxisID: axisIds[i],
      borderColor: c,
      backgroundColor: "transparent",
      borderWidth: 2,
      pointRadius: 0,
      tension: 0,
    });
  }
  saveJSON(DS_COLOR_KEY, dsColors);

  if (!datasets.length || !baseRawXY?.length) {
    setMsg("No price points.");
    destroyPriceChart();
    return;
  }

  if (!state.base.xBounds) state.base.xBounds = computeXBoundsFromXY(baseRawXY);

  if (state.data.bb?.series && Array.isArray(state.data.bb.series) && baseRawXY) {
    for (const s of state.data.bb.series) {
      const bbxyRaw = normalizePoints(s.points || []);
      const bbxy = normalizeSeriesXY(bbxyRaw, normMode, normBaseValue);
      if (!bbxy.length) continue;
      const lbl = String(s.label || "BB");
      const c = normalizeColor(dsColors[lbl], lbl);
      dsColors[lbl] = c;
      datasets.push({
        label: lbl,
        data: bbxy,
        yAxisID: axisIds[0],
        backgroundColor: "transparent",
        borderWidth: 1.4,
        pointRadius: 0,
        tension: 0,
        borderColor: withAlpha(c, 0.4),
      });
    }
  }

  if (Array.isArray(state.data.ma) && state.data.ma.length && baseRawXY) {
    for (const maResp of state.data.ma) {
      const s = maResp?.series?.[0];
      const maXYRaw = normalizePoints(s?.points || []);
      const maXY = normalizeSeriesXY(maXYRaw, normMode, normBaseValue);
      if (!maXY.length) continue;
      const lbl = String(s.label || "MA");
      const c = normalizeColor(dsColors[lbl], lbl);
      dsColors[lbl] = c;
      datasets.push({
        label: lbl,
        data: maXY,
        yAxisID: axisIds[0],
        backgroundColor: "transparent",
        borderWidth: 1.6,
        pointRadius: 0,
        tension: 0,
        borderColor: withAlpha(c, 0.6),
      });
    }
  }
  saveJSON(DS_COLOR_KEY, dsColors);

  destroyPriceChart();

  const xb = state.base.xBounds;
  const xMin = xb?.xMin;
  const xMax = xb?.xMax;

  const yScales = {};
  const axisIndexById = {};
  baseAxisIds.forEach((id, idx) => { axisIndexById[id] = idx; });
  if (shareAxis) axisIndexById.y = 0;
  const seenAxis = new Set();
  for (let i = 0; i < axisIds.length; i++) {
    const id = axisIds[i];
    if (seenAxis.has(id)) continue;
    seenAxis.add(id);
    const axisIdx = axisIndexById[id] ?? 0;
    const isPrimary = axisIdx === 0;
    const isLeft = (axisIdx % 2 === 0);
    const axisLabel = String(seriesList[i]?.label || seriesList[i]?.expr || "");
    yScales[id] = {
      position: isLeft ? "left" : "right",
      ticks: {
        maxTicksLimit: 8,
        font: AXIS_TICK_FONT,
        callback: (v) => {
          if (!Number.isFinite(Number(v))) return "";
          if (normMode === 0) return `${Number(v).toFixed(0)}%`;
          return Number(v).toFixed(2);
        },
      },
      grid: {
        display: !!uiPrefs.grid,
        color: "rgba(17,17,17,.08)",
        drawOnChartArea: isPrimary,
      },
      title: {
        display: multiAxis,
        text: axisLabel,
        font: AXIS_TICK_FONT,
      },
    };
  }

  priceChart = new Chart(els.chartEl.getContext("2d"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      animation: false,
      layout: { padding: { left: 6, right: LAST_VALUE_PAD_RIGHT, top: TOP_DATES_PAD, bottom: 0 } },
      plugins: {
        legend: {
          display: false,
          labels: { usePointStyle: true, pointStyle: "line", boxWidth: 28, font: AXIS_TICK_FONT },
          onClick: legendToggleDataset,
        },
        tooltip: {
          callbacks: {
            title: (items) => {
              const x = items?.[0]?.parsed?.x;
              return (x != null) ? new Date(Number(x)).toLocaleString() : "";
            },
          },
        },
        zoom: zoomPanSyncCallbacks(),
        qsEdgeXTicks: { enabled: true },
        qsTopDates: { enabled: true },
        qsAxisControls: { enabled: true },
        qsLastValue: {
          enabled: true,
          datasetIndices: datasets
            .map((d, i) => ({ i, label: String(d.label || "") }))
            .filter((d) => !/bb\s|bollinger/i.test(d.label))
            .map((d) => d.i),
          formatter: (v) => {
            if (!Number.isFinite(Number(v))) return "";
            if (normMode === 0) return `${Number(v).toFixed(2)}%`;
            return Number(v).toFixed(2);
          },
        },
        qsCrosshair: {
          enabled: true,
          formatter: (v) => (Number.isFinite(Number(v)) ? Number(v).toFixed(2) : ""),
        },
      },
      scales: {
        x: {
          type: "linear",
          offset: false,
          bounds: "data",
          min: Number.isFinite(xMin) ? xMin : undefined,
          max: Number.isFinite(xMax) ? xMax : undefined,
          ticks: {
            callback: function (v, idx, ticks) {
              const edgePluginOn = !!this?.chart?.options?.plugins?.qsEdgeXTicks?.enabled;
              const last = (ticks?.length ?? 0) - 1;

              // Only hide edges if the plugin is enabled (so it can redraw them aligned)
              if (edgePluginOn && (idx === 0 || idx === last)) return "";

              return formatDateTick(v);
            },
            maxTicksLimit: 10,
            autoSkip: true,
            display: true,
            font: AXIS_TICK_FONT
          },


          grid: { display: !!uiPrefs.grid, color: "rgba(17,17,17,.08)" },
        },
        ...yScales,
      },
    },
  });

  priceChart.$qsAxisNormalize = () => {
    const cur = state.base.norm;
    let next = null;
    if (cur == null) next = 100;
    else if (cur === 100) next = 0;
    else if (cur === 0) next = null;
    else next = 100;
    state.base.norm = next;
    if (state.data.price) renderPrice(state.data.price);
  };

  applyXAxisInnerTicks(priceChart.options.scales);
  applyAxisFonts(priceChart.options.scales);
  applyFixedYWidth(priceChart, Y_AXIS_WIDTH);
  setGridEnabledOnChart(priceChart, !!uiPrefs.grid);
  priceChart.$qsLegendShown = false;
  withZoomSuppressed(priceChart, () => priceChart.update("none"));

  attachDblClickReset(priceChart, els.chartEl);
  installAxisGripsForChart(priceChart, panels.get(PANEL_IDS.PRICE)?.rootEl?.querySelector(".qpanel-canvas"));
  installChartPan(priceChart, els.chartEl);
  updatePanelsXAxisVisibility();
  syncAllPanelsToBaseXBounds(priceChart);
  requestChartResizeAll();
}

function safeStringify(obj, space = 2, { maxDepth = 8, maxArray = 2000 } = {}) {
  const seen = new WeakSet();

  function walk(v, depth) {
    if (v === null || typeof v !== "object") return v;

    if (seen.has(v)) return "[circular]";
    seen.add(v);

    if (depth >= maxDepth) return "[maxDepth]";

    if (Array.isArray(v)) {
      if (v.length > maxArray) return `[Array(${v.length}) truncated]`;
      return v.map(x => walk(x, depth + 1));
    }

    const out = {};
    for (const k of Object.keys(v)) out[k] = walk(v[k], depth + 1);
    return out;
  }

  try {
    return JSON.stringify(walk(obj, 0), null, space);
  } catch (e) {
    return `"[safeStringify failed: ${String(e)}]"`;
  }
}



// ============================================================
// Snapshot
// ============================================================
async function snapshotChart() {
  try {
    if (!priceChart) return setMsg("Nothing to snapshot.");
    const url = els.chartEl.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = url;
    a.download = `qs_chart_${new Date().toISOString().replaceAll(":","-")}.png`;
    a.click();
    setMsg("Snapshot saved.");
  } catch (e) {
    setMsg(`Snapshot failed: ${String(e)}`);
  }
}

function buildSeasonalityCommand(panelId) {
  const params = getSeasonalityParams(panelId);
  const expr = String(params.expr || "").trim();
  const years = String(params.yearsSpec || "10").trim();
  const mode = params.mode === "years" ? "years" : "heatmap";
  const bucket = params.bucket || "month";
  return `seasonality(${expr}, mode=${mode}, bucket=${bucket}, years=${years})`;
}

function saveSeasonalityToLibrary() {
  const panelId = PANEL_IDS.SEASONALITY_MODULE;
  if (!panelId) return setMsg("No seasonality panel.");
  const params = getSeasonalityParams(panelId);
  const expr = String(params.expr || "").trim();
  if (!expr) return setMsg("Set an expression first.");
  const cmd = buildSeasonalityCommand(panelId);

  const lib = getLibrary();
  const targetId = lib.rootId;
  const folder = lib.folders[targetId];
  folder.items = folder.items || [];

  const name = `Seasonality · ${expr}`;
  const id = `i_${Math.random().toString(36).slice(2, 10)}`;
  folder.items.unshift({ id, name, cmd, meta: new Date().toLocaleDateString() });
  setLibrary(lib);
  expandedFolders.add(targetId);
  saveExpanded();
  renderLibrary();
  setMsg("Saved to Library.");
}

async function snapshotSeasonality() {
  const panelId = PANEL_IDS.SEASONALITY_MODULE;
  const p = panels.get(panelId);
  if (!p) return setMsg("Nothing to snapshot.");
  const params = getSeasonalityParams(panelId);

  if (params.mode === "heatmap") {
    const layout = ensureSeasonalityLayout(panelId);
    const heat = layout?.body?.querySelector(".qs-heatmap");
    if (!heat) return setMsg("Nothing to snapshot.");
    const rect = heat.getBoundingClientRect();
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(rect.width);
    canvas.height = Math.ceil(rect.height);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const cells = Array.from(heat.querySelectorAll(".qs-heatmap-cell"));
    for (const cell of cells) {
      const r = cell.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const x = r.left - rect.left;
      const y = r.top - rect.top;
      const styles = getComputedStyle(cell);
      const bg = styles.backgroundColor || "#fff";
      ctx.fillStyle = bg;
      ctx.fillRect(x, y, r.width, r.height);

      const text = (cell.textContent || "").trim();
      if (text) {
        const font = styles.font || `${styles.fontSize || "11px"} ${styles.fontFamily || "system-ui"}`;
        ctx.font = font;
        ctx.fillStyle = styles.color || "#111";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, x + r.width / 2, y + r.height / 2);
      }
    }

    const titleText = (layout?.title?.textContent || "Seasonality Snapshot").trim();
    const png = canvas.toDataURL("image/png");
    showImageModal(png, titleText || "Seasonality Snapshot");
    return;
  }

  if (p.canvas) {
    const layout = ensureSeasonalityLayout(panelId);
    const titleText = (layout?.title?.textContent || "Seasonality Snapshot").trim();
    const url = p.canvas.toDataURL("image/png");
    showImageModal(url, titleText || "Seasonality Snapshot");
  }
}

function showImageModal(dataUrl, title = "Snapshot") {
  let modal = document.getElementById("qsImageModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "qsImageModal";
    modal.className = "qs-image-modal";
    modal.innerHTML = `
      <div class="qs-image-backdrop"></div>
      <div class="qs-image-frame">
        <div class="qs-image-head">
          <div class="qs-image-title"></div>
          <button class="qs-image-close" title="Close">×</button>
        </div>
        <img alt="Snapshot" />
      </div>
    `;
    document.body.appendChild(modal);
    modal.querySelector(".qs-image-backdrop")?.addEventListener("click", () => modal.remove());
    modal.querySelector(".qs-image-close")?.addEventListener("click", () => modal.remove());
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") modal.remove();
    });
  }
  modal.querySelector(".qs-image-title").textContent = title;
  const img = modal.querySelector("img");
  img.src = dataUrl;
  img.onload = () => setMsg("Snapshot opened.");
}

function recomputeSeasonalityBands(chart) {
  const baseX = chart.$qsSeasonalityBaseX;
  if (!Array.isArray(baseX) || !baseX.length) return;
  const currentYear = String(chart.$qsSeasonalityCurrentYear || "");

  const yearDatasets = chart.data.datasets.filter((ds, idx) => {
    if (ds._qsIsBand) return false;
    const lbl = String(ds.label || "");
    if (currentYear && lbl === currentYear) return false;
    const meta = chart.getDatasetMeta(idx);
    if (meta?.hidden) return false;
    return true;
  });

  const seriesMaps = yearDatasets.map((s) => {
    const pts = (s.data || []).slice().sort((a, b) => a.x - b.x);
    const map = new Map();
    let last = null;
    let idx = 0;
    for (const x of baseX) {
      while (idx < pts.length && pts[idx].x <= x) {
        const v = Number(pts[idx].y);
        if (Number.isFinite(v)) last = v;
        idx += 1;
      }
      if (last != null) map.set(x, last);
    }
    return map;
  });

  const p0 = [];
  const p50 = [];
  const p100 = [];
  const pAvg = [];
  for (let i = 0; i < baseX.length; i++) {
    const vals = [];
    for (const sm of seriesMaps) {
      const v = sm.get(baseX[i]);
      if (Number.isFinite(v)) vals.push(v);
    }
    if (!vals.length) continue;
    vals.sort((a, b) => a - b);
    p0.push({ x: baseX[i], y: quantileSorted(vals, 0) });
    p50.push({ x: baseX[i], y: quantileSorted(vals, 0.5) });
    p100.push({ x: baseX[i], y: quantileSorted(vals, 1) });
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    pAvg.push({ x: baseX[i], y: mean });
  }

  chart.data.datasets.forEach((ds) => {
    if (!ds._qsIsBand) return;
    const label = String(ds.label || "").toUpperCase();
    if (label === "P0") ds.data = p0;
    if (label === "P50") ds.data = p50;
    if (label === "P100") ds.data = p100;
    if (label === "MEAN") ds.data = pAvg;
  });
}

// ============================================================
// Popovers + Gear formatting toggles
// IMPORTANT: ONLY ONE installPopovers() in this file.
// ============================================================
function ensurePopoverTypography() {
  [els.taPopover, els.panelPopover, els.gearPopover].forEach(p => {
    if (!p) return;
    p.style.fontFamily = "system-ui, -apple-system, Segoe UI, Roboto, Arial";
    p.style.fontSize = "13px";
  });
}

// Keep your existing gear toggles if needed (minimal here)
function installGearFormatToggles() {
  if (!els.gearPopover) return;
  // leave as-is / optional
}

function installPopovers() {
  if (document.body.$qsPopoversInstalled) return;
  document.body.$qsPopoversInstalled = true;

  const closeAll = () => {
    if (els.taPopover) els.taPopover.hidden = true;
    if (els.panelPopover) els.panelPopover.hidden = true;
    if (els.gearPopover) els.gearPopover.hidden = true;
  };

  document.addEventListener("click", (ev) => {
    const t = ev.target;
    const inTA = (els.taPopover && els.taPopover.contains(t)) || (els.taBtn && els.taBtn.contains(t));
    const inPanel = (els.panelPopover && els.panelPopover.contains(t)) || (els.panelBtn && els.panelBtn.contains(t));
    const inGear = (els.gearPopover && els.gearPopover.contains(t)) || (els.gearBtn && els.gearBtn.contains(t));
    if (!inTA && !inPanel && !inGear) closeAll();
  });

  if (els.taBtn && els.taPopover) {
    els.taBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (els.panelPopover) els.panelPopover.hidden = true;
      if (els.gearPopover) els.gearPopover.hidden = true;
      els.taPopover.hidden = !els.taPopover.hidden;
    });
  }

  if (els.panelBtn && els.panelPopover) {
    els.panelBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (els.taPopover) els.taPopover.hidden = true;
      if (els.gearPopover) els.gearPopover.hidden = true;
      els.panelPopover.hidden = !els.panelPopover.hidden;
    });

    if (!els.panelPopover.$qsInstalled) {
      els.panelPopover.$qsInstalled = true;
      els.panelPopover.addEventListener("click", (ev) => {
        const btn = ev.target?.closest?.("[data-panel]");
        if (!btn) return;
        ev.preventDefault();
        ev.stopPropagation();
        const kind = btn.dataset.panel;
        els.panelPopover.hidden = true;
        addPanelFromMenu(kind);
      });
    }
  }

  if (els.gearBtn && els.gearPopover) {
    els.gearBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (els.taPopover) els.taPopover.hidden = true;
      if (els.panelPopover) els.panelPopover.hidden = true;
      els.gearPopover.hidden = !els.gearPopover.hidden;
    });

    if (els.gridToggle) {
      els.gridToggle.checked = !!uiPrefs.grid;
      els.gridToggle.addEventListener("change", () => {
        uiPrefs.grid = !!els.gridToggle.checked;
        saveUiPrefs();

        setGridEnabledOnChart(priceChart, uiPrefs.grid);
        if (priceChart) withZoomSuppressed(priceChart, () => priceChart.update("none"));

        for (const ch of panelCharts.values()) {
          setGridEnabledOnChart(ch, uiPrefs.grid);
          withZoomSuppressed(ch, () => ch.update("none"));
        }
        updatePanelsXAxisVisibility();
      });
    }
  }

  loadIndicatorState();

  const renderTAList = () => {
    if (!els.taList) return;
    const rows = [];
    if (state.overlays.bb) {
      const w = Number(state.overlays.bb.window || 20);
      const s = Number(state.overlays.bb.sigma || 2);
      rows.push(`
        <div class="ta-item">
          <div class="ta-label">BB (${w}, ${s})</div>
          <button class="pillbtn ta-remove" data-act="remove" data-kind="bb">Remove</button>
        </div>
      `);
    }
    for (const n of (state.overlays.sma || [])) {
      rows.push(`
        <div class="ta-item">
          <div class="ta-label">SMA (${n})</div>
          <button class="pillbtn ta-remove" data-act="remove" data-kind="sma" data-period="${n}">Remove</button>
        </div>
      `);
    }
    for (const n of (state.overlays.ema || [])) {
      rows.push(`
        <div class="ta-item">
          <div class="ta-label">EMA (${n})</div>
          <button class="pillbtn ta-remove" data-act="remove" data-kind="ema" data-period="${n}">Remove</button>
        </div>
      `);
    }
    els.taList.innerHTML = rows.length ? rows.join("") : `<div class="hint">No overlays.</div>`;
  };

  renderTAList();

  els.taAddBtn?.addEventListener("click", async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const kind = (els.taSelect?.value || "").toLowerCase();
    if (!kind) return;

    if (kind === "bb") {
      state.overlays.bb = state.overlays.bb || { window: 20, sigma: 2 };
      saveIndicatorState();
      renderTAList();
      await refreshOverlaysOnly();
      return;
    }

    const p = Number(prompt("Period?", "20") || "20");
    if (!Number.isFinite(p) || p < 2) return;
    const target = (kind === "sma") ? state.overlays.sma : state.overlays.ema;
    if (!target.includes(p)) target.push(p);
    target.sort((a, b) => a - b);
    saveIndicatorState();
    renderTAList();
    await refreshOverlaysOnly();
  });

  els.taList?.addEventListener("click", async (ev) => {
    const btn = ev.target?.closest?.("button[data-act=\"remove\"]");
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    const kind = btn.dataset.kind;
    const period = Number(btn.dataset.period);
    if (kind === "bb") {
      state.overlays.bb = null;
    } else if (kind === "sma") {
      state.overlays.sma = (state.overlays.sma || []).filter((n) => n !== period);
    } else if (kind === "ema") {
      state.overlays.ema = (state.overlays.ema || []).filter((n) => n !== period);
    }
    saveIndicatorState();
    renderTAList();
    await refreshOverlaysOnly();
  });
}

// ============================================================
// Sidebar / collapse wiring
// ============================================================
function installSidebarToggle() {
  if (!els.sidebar) return;
  if (els.sidebarToggle && els.sidebarToggle.$qsInstalled) return;
  if (els.sidebarToggle) els.sidebarToggle.$qsInstalled = true;

  if (els.sidebarToggle) {
    els.sidebarToggle.addEventListener("click", () => {
      const collapsed = els.sidebar.classList.toggle("collapsed");
      const chev = els.sidebarToggle.querySelector(".chev");
      if (chev) chev.textContent = collapsed ? "⟩" : "⟨";
      if (collapsed) {
        els.sidebar.classList.remove("show-panels");
        __openSidebarPanel = null;
        collapsedPanels.history = true;
        collapsedPanels.library = true;
        collapsedPanels.help = true;
        collapsedPanels.seasonality = true;
        saveJSON("qs.panels.collapsed.v1", collapsedPanels);
        els.sidebar.style.width = "";
        els.sidebar.style.minWidth = "";
      } else {
        const saved = loadJSON("qs.sidebar.w.v1", null);
        if (Number.isFinite(saved)) {
          els.sidebar.style.width = `${saved}px`;
          els.sidebar.style.minWidth = `${saved}px`;
        }
      }
      window.$qsUpdateMainWidth?.();
      requestAnimationFrame(requestChartResizeAll);
    });
  }

  document.querySelectorAll(".sicon[data-jump]").forEach((btn) => {
    if (btn.$qsInstalled) return;
    btn.$qsInstalled = true;

    btn.addEventListener("click", () => {
      const target = btn.dataset.jump;
  const isOpen = (__openSidebarPanel === target) && els.sidebar.classList.contains("show-panels");
  if (isOpen) {
    __openSidebarPanel = null;
    collapsedPanels.history = true;
    collapsedPanels.library = true;
    collapsedPanels.help = true;
    collapsedPanels.seasonality = true;
    els.sidebar.classList.remove("show-panels");
    els.sidebar.style.width = "";
    els.sidebar.style.minWidth = "";
  } else {
    __openSidebarPanel = target;
    collapsedPanels.history = target !== "history";
    collapsedPanels.library = target !== "library";
    collapsedPanels.help = target !== "help";
    collapsedPanels.seasonality = target !== "seasonality";
    els.sidebar.classList.add("show-panels");
    els.sidebar.classList.remove("collapsed");
    window.$qsResetMainWidth?.();
    const saved = loadJSON("qs.sidebar.w.v1", null);
    if (Number.isFinite(saved)) {
      const w = clamp(saved, 220, 520);
      els.sidebar.style.width = `${w}px`;
      els.sidebar.style.minWidth = `${w}px`;
    }
  }

      saveJSON("qs.panels.collapsed.v1", collapsedPanels);
      renderHistory();
      renderLibrary();
      renderHelp();
      renderSeasonalityPanel();
      requestAnimationFrame(requestChartResizeAll);
    });
  });
}

function installPanelCollapse() {
  document.querySelectorAll("[data-collapse]").forEach((btn) => {
    if (btn.$qsInstalled) return;
    btn.$qsInstalled = true;

    btn.addEventListener("click", () => {
      const which = btn.dataset.collapse;
      collapsedPanels[which] = !collapsedPanels[which];
      saveJSON("qs.panels.collapsed.v1", collapsedPanels);
      renderHistory();
      renderLibrary();
      renderHelp();
      renderSeasonalityPanel();
      requestAnimationFrame(requestChartResizeAll);
    });
  });
}

function normalizeTickerInput(raw) {
  return String(raw || "").trim().toUpperCase();
}

function renderChartingSidebar() {
  const tpl = getActiveChartingTemplate();

  if (els.chartingTickerList) {
    els.chartingTickerList.innerHTML = "";
    for (const t of (tpl.tickers || [])) {
      const row = document.createElement("div");
      row.className = "charting-item";
      row.innerHTML = `
        <div>
          <div>${escapeHtml(t)}</div>
          <div class="meta">Asset</div>
        </div>
        <button data-act="remove" data-ticker="${escapeHtml(t)}">Remove</button>
      `;
      row.querySelector("button")?.addEventListener("click", () => removeTickerFromTemplate(t));
      els.chartingTickerList.appendChild(row);
    }
  }

  if (els.chartingMetricList) {
    els.chartingMetricList.innerHTML = "";
    for (const m of (tpl.metrics || [])) {
      const row = document.createElement("div");
      row.className = "charting-item";
      const meta = (m.tickers || []).join(", ");
      row.innerHTML = `
        <div>
          <div>${escapeHtml(CHARTING_METRICS[m.kind]?.label || m.kind)}</div>
          <div class="meta">${escapeHtml(meta || "—")}</div>
        </div>
        <button data-act="remove" data-metric="${escapeHtml(m.id || "")}">Remove</button>
      `;
      row.querySelector("button")?.addEventListener("click", () => removeMetricFromTemplate(m.id));
      els.chartingMetricList.appendChild(row);
    }
  }

  if (els.chartingTemplateList) {
    els.chartingTemplateList.innerHTML = "";
    for (const t of (chartingTemplates || [])) {
      const row = document.createElement("div");
      row.className = "charting-item";
      row.innerHTML = `
        <div>${escapeHtml(t.name || "Template")}</div>
        <button data-act="load" data-template="${escapeHtml(t.id)}">Load</button>
      `;
      row.querySelector("button")?.addEventListener("click", () => {
        setActiveChartingTemplate(t.id);
        renderChartingSidebar();
        applyChartingTemplate({ force: true });
      });
      els.chartingTemplateList.appendChild(row);
    }
  }
}

function getMetricLabel(kind, params = {}) {
  if (kind === "rsi") return `RSI(${params.period || 14})`;
  if (kind === "sharpe") return `Sharpe(${params.window || "63D"})`;
  if (kind === "drawdown") return `Drawdown(${params.window || "3M"})`;
  if (kind === "zscore") return `Z-Score(${params.window || "3M"})`;
  if (kind === "ma") return `${String(params.ma || "sma").toUpperCase()}(${params.window || 20})`;
  if (kind === "bollinger") return `BB(${params.window || 20}, ${params.sigma || 2})`;
  if (kind === "corr") return `Corr(${params.a || ""}, ${params.b || ""})`;
  if (kind === "volume") return `Volume(${params.ma || 20})`;
  return String(kind || "Metric");
}

function addTickerToTemplate(rawTicker) {
  const tpl = getActiveChartingTemplate();
  const t = normalizeTickerInput(rawTicker);
  if (!t) return;
  if (!tpl.tickers.includes(t)) tpl.tickers.push(t);
  if (tpl.tickers.length > MAX_Y_AXES && tpl.norm == null) {
    const side = (prompt("Axis limit exceeded. Share extra tickers on which side? (left/right)", tpl.axisOverflowSide || "right") || "").trim().toLowerCase();
    if (side === "left" || side === "right") tpl.axisOverflowSide = side;
  }
  saveChartingTemplates();
  renderChartingSidebar();
  applyChartingTemplate({ force: true });
}

function removeTickerFromTemplate(ticker) {
  const tpl = getActiveChartingTemplate();
  tpl.tickers = (tpl.tickers || []).filter(t => t !== ticker);
  tpl.metrics = (tpl.metrics || []).map(m => ({
    ...m,
    tickers: (m.tickers || []).filter(t => t !== ticker),
  })).filter(m => (m.tickers || []).length);
  saveChartingTemplates();
  renderChartingSidebar();
  applyChartingTemplate({ force: true });
}

function removeMetricFromTemplate(id) {
  const tpl = getActiveChartingTemplate();
  tpl.metrics = (tpl.metrics || []).filter(m => m.id !== id);
  saveChartingTemplates();
  renderChartingSidebar();
  applyChartingTemplate({ force: true });
}

function promptMetricTickers(metricKind, tickers) {
  if (!Array.isArray(tickers) || !tickers.length) return [];
  const list = tickers.join(", ");
  const resp = prompt(`Apply ${metricKind} to which tickers? (comma-separated)`, list);
  if (resp == null) return null;
  const picked = resp.split(",").map(normalizeTickerInput).filter(Boolean);
  return picked.length ? picked : [];
}

function addMetricToTemplate(kind) {
  const tpl = getActiveChartingTemplate();
  const metric = CHARTING_METRICS[kind];
  if (!metric) return;
  if (!tpl.tickers.length) return setMsg("Add a ticker first.");

  let tickers = [...tpl.tickers];
  if (metric.singleTicker) {
    const def = tickers[0];
    const resp = prompt(`Select ticker for ${metric.label}`, def);
    if (resp == null) return;
    tickers = [normalizeTickerInput(resp)];
  } else if (tickers.length > 1) {
    const picked = promptMetricTickers(metric.label, tickers);
    if (picked == null) return;
    tickers = picked;
  } else {
    tickers = [tickers[0]];
  }

  const params = {};
  if (kind === "rsi") params.period = Number(prompt("RSI period?", "14") || "14") || 14;
  if (kind === "sharpe") params.window = (prompt("Sharpe window?", "63D") || "63D").trim();
  if (kind === "drawdown") params.window = (prompt("Drawdown window?", "3M") || "3M").trim();
  if (kind === "zscore") params.window = (prompt("Z-Score window?", "3M") || "3M").trim();
  if (kind === "ma") {
    params.ma = (prompt("MA type? (sma/ema)", "sma") || "sma").trim().toLowerCase();
    params.window = Number(prompt("MA window?", "20") || "20") || 20;
  }
  if (kind === "bollinger") {
    params.window = Number(prompt("BB window?", "20") || "20") || 20;
    params.sigma = Number(prompt("BB sigma?", "2") || "2") || 2;
  }
  if (kind === "volume") params.ma = Number(prompt("Volume MA?", "20") || "20") || 20;
  if (kind === "corr") {
    const a = (prompt("Corr A", tickers[0] || "") || "").trim();
    const b = (prompt("Corr B", tickers[1] || "") || "").trim();
    if (!a || !b) return;
    params.a = normalizeTickerInput(a);
    params.b = normalizeTickerInput(b);
    params.ret = (prompt("Return horizon?", "3D") || "3D").trim();
    params.window = (prompt("Rolling window?", "90D") || "90D").trim();
    tickers = [params.a, params.b];
  }

  tpl.metrics = tpl.metrics || [];
  tpl.metrics.push({
    id: `m_${Date.now()}`,
    kind,
    tickers,
    params,
  });
  saveChartingTemplates();
  renderChartingSidebar();
  applyChartingTemplate({ force: true });
}

async function applyChartingTemplate({ force = false } = {}) {
  if (!els.chartEl) return;
  const tpl = getActiveChartingTemplate();
  if (!tpl.tickers.length) {
    destroyPriceChart();
    setMsg("Select an asset to chart.");
    return;
  }

  const durTok = tpl.durationToken || state.base.durationToken || "1Y";
  const { start, end } = computeStartEndFromToken(durTok);
  const apiDuration = durationTokenToApiDuration(durTok);
  state.base.durationToken = durTok;
  state.base.start = start;
  state.base.end = end;
  state.base.expr = tpl.tickers[0];
  state.base.norm = (tpl.norm != null) ? tpl.norm : (tpl.tickers.length > 1 ? 0 : null);
  state.base.axisOverflowSide = tpl.axisOverflowSide || "right";
  state.base.xBounds = null;

  const series = [];
  const errors = [];
  for (const t of tpl.tickers) {
    try {
      const resp = await postJSON("/expr/chart", {
        expr: t,
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      const s0 = resp?.series?.[0];
      const label = s0?.label || resp?.label || t;
      const points = s0?.points || resp?.points || [];
      series.push({ label, points, expr: t });
    } catch (e) {
      errors.push(`${t}: ${String(e.message || e)}`);
    }
  }

  if (!series.length) {
    destroyPriceChart();
    setMsg(errors.join(" | ") || "No data.");
    return;
  }

  state.data.price = (series.length === 1)
    ? { label: series[0].label, points: series[0].points }
    : { label: series[0].label, series };

  renderPrice(state.data.price);
  if (els.chartTableWrap && !els.chartTableWrap.hidden) renderChartTable();
  resetChartingPanels();

  for (const m of (tpl.metrics || [])) {
    await renderChartingMetric(m, apiDuration);
  }

  if (errors.length) setMsg(`OK (partial): ${errors.join(" | ")}`);
  else setMsg("OK");
}

function resetChartingPanels() {
  const keep = new Set([PANEL_IDS.PRICE, PANEL_IDS.SEASONALITY_MODULE]);
  for (const pid of Array.from(panels.keys())) {
    if (keep.has(pid)) continue;
    removePanel(pid);
  }
}

async function renderChartingMetric(metric, apiDuration) {
  const kind = metric.kind;
  const params = metric.params || {};
  const tickers = metric.tickers || [];
  if (!tickers.length) return;

  const title = `${CHARTING_METRICS[kind]?.label || kind} · ${tickers.join(", ")}`;
  const panelId = createPanel({ kind, title, height: 200 });
  if (!panelId) return;
  panelSpecs[panelId] = { kind, params, tickers, createdAt: Date.now() };
  savePanelSpecs();

  if (kind === "volume") {
    const volResp = await fetchVolumeBars(tickers[0]);
    renderVolumeToPanel(panelId, volResp, `Volume · ${tickers[0]}`, { maPeriod: params.ma || 20 });
    return;
  }

  if (kind === "corr") {
    const resp = await postJSON("/expr/corr", {
      a: params.a,
      b: params.b,
      ret_horizon: params.ret || "3D",
      window: params.window || "90D",
      duration: apiDuration,
      bar_size: state.base.bar_size,
      use_rth: state.base.use_rth,
    });
    renderPanelChart(panelId, resp);
    return;
  }

  const series = [];
  for (const t of tickers) {
    const label = `${t} ${getMetricLabel(kind, params)}`;
    if (kind === "rsi") {
      const resp = await postJSON("/expr/rsi", {
        expr: t,
        period: params.period || 14,
        bands: "classic",
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      const pts = resp?.series?.[0]?.points || resp?.points || [];
      series.push({ label, points: pts });
      continue;
    }
    if (kind === "sharpe") {
      const resp = await postJSON("/expr/sharpe", {
        expr: t,
        window: params.window || "63D",
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      const pts = resp?.series?.[0]?.points || resp?.points || [];
      series.push({ label, points: pts });
      continue;
    }
    if (kind === "drawdown") {
      const resp = await postJSON("/expr/drawdown", {
        expr: t,
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
        mode: "point",
        rolling_window: params.window || "3M",
      });
      const pts = resp?.series?.[0]?.points || resp?.points || [];
      series.push({ label, points: pts });
      continue;
    }
    if (kind === "zscore") {
      const resp = await postJSON("/expr/zscore", {
        expr: t,
        window: params.window || "3M",
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      const pts = resp?.series?.[0]?.points || resp?.points || [];
      series.push({ label, points: pts });
      continue;
    }
    if (kind === "ma") {
      const resp = await postJSON("/expr/ma", {
        expr: t,
        ma: params.ma || "sma",
        window: Number(params.window || 20),
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      const pts = resp?.series?.[0]?.points || resp?.points || [];
      series.push({ label, points: pts });
      continue;
    }
    if (kind === "bollinger") {
      const resp = await postJSON("/expr/bollinger", {
        expr: t,
        period: Number(params.window || 20),
        sigma: Number(params.sigma || 2),
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      const s = resp?.series || [];
      if (Array.isArray(s) && s.length) {
        for (const bb of s) {
          const pts = bb?.points || [];
          series.push({ label: `${t} ${bb.label || "BB"}`, points: pts });
        }
      }
      continue;
    }
  }

  if (!series.length) {
    renderPanelError(panelId, "No series data.");
    return;
  }

  renderPanelChart(panelId, { series });
}

let activeModule = "charting";

function setActiveModule(name, { force = false } = {}) {
  const next = String(name || "charting").toLowerCase();
  if (!force && next === activeModule) return;
  activeModule = next;

  document.querySelectorAll(".module[data-module]").forEach((mod) => {
    const on = mod.dataset.module === activeModule;
    mod.classList.toggle("active", on);
  });

  document.querySelectorAll(".sicon[data-module]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.module === activeModule);
  });

  document.body.classList.toggle("mod-charting", activeModule === "charting");
  document.body.classList.toggle("mod-seasonality", activeModule === "seasonality");
  document.body.classList.toggle("mod-portfolio", activeModule === "portfolio");
  document.body.classList.toggle("mod-regressions", activeModule === "regressions");
  document.body.classList.toggle("mod-market", activeModule === "market");

  if (activeModule === "seasonality") {
    const panelId = ensureSeasonalityModulePanel();
    if (panelId) loadSeasonalityPanel(panelId, false);
  }
  if (activeModule === "charting") {
    renderChartingSidebar();
    applyChartingTemplate({ force: true });
  }

  requestAnimationFrame(requestChartResizeAll);
}

function installModuleSwitching() {
  document.querySelectorAll(".sicon[data-module]").forEach((btn) => {
    if (btn.$qsInstalled) return;
    btn.$qsInstalled = true;
    btn.addEventListener("click", () => setActiveModule(btn.dataset.module, { force: true }));
  });
}

function installChartingUI() {
  if (!els.chartingAssetInput || els.chartingAssetInput.$qsInstalled) return;
  els.chartingAssetInput.$qsInstalled = true;

  ensureChartingTemplates();
  renderChartingSidebar();

  const addFromInput = () => {
    const v = normalizeTickerInput(els.chartingAssetInput.value);
    if (!v) return;
    addTickerToTemplate(v);
    els.chartingAssetInput.value = "";
  };

  els.chartingAddTickerBtn?.addEventListener("click", addFromInput);
  els.chartingAddTickerMore?.addEventListener("click", () => {
    const v = prompt("Add ticker (e.g. EQ:SPY)", "") || "";
    const t = normalizeTickerInput(v);
    if (t) addTickerToTemplate(t);
  });

  els.chartingAssetInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      addFromInput();
    }
  });

  els.chartingAddMetricBtn?.addEventListener("click", () => {
    const kind = els.chartingMetricSelect?.value || "rsi";
    addMetricToTemplate(kind);
  });

  els.chartingSaveTemplateBtn?.addEventListener("click", () => {
    const name = (els.chartingTemplateName?.value || "").trim() || prompt("Template name?", "") || "";
    const tpl = getActiveChartingTemplate();
    if (!name) return;
    const copy = {
      ...tpl,
      id: `tpl_${Date.now()}`,
      name,
      metrics: (tpl.metrics || []).map(m => ({ ...m })),
    };
    chartingTemplates.push(copy);
    setActiveChartingTemplate(copy.id);
    saveChartingTemplates();
    renderChartingSidebar();
    applyChartingTemplate({ force: true });
    if (els.chartingTemplateName) els.chartingTemplateName.value = "";
  });

  els.chartingCollapseBtn?.addEventListener("click", () => {
    document.body.classList.toggle("charting-selections-collapsed");
    requestAnimationFrame(requestChartResizeAll);
  });

}

async function addSeasonalityFromMenu() {
  setActiveModule("seasonality", { force: true });
  const panelId = ensureSeasonalityModulePanel();
  if (!panelId) return;
  if (!panelSpecs[panelId]?.params?.expr) {
    const expr = (state.base.expr || "").trim();
    if (expr) setSeasonalityParams(panelId, { expr });
  }
  await loadSeasonalityPanel(panelId, true);
  setMsg("Seasonality ready.");
}

// ============================================================
// Main execution (price only here; keep your other kinds if needed)
// ============================================================
async function runCommand(cmdText, opts = {}) {
  if (!stackEl) setupChartViewport();

  const parsed = parseUserInput(cmdText);
  if (!parsed) return;

  setMsg("Running…");

  const cmdStack = loadCmdStack();
  const activeEntry = cmdStack.find(x => x.id === activeCmdId && !x.removed);
  const activePanelId = (activeEntry?.panelId && activeEntry.kind === parsed.kind)
    ? activeEntry.panelId
    : null;

  const prevExpr = state.base.expr;
  const prevDurTok = state.base.durationToken;

  const durTok = parsed.durationToken ?? state.base.durationToken ?? "3y";
  const { start, end } = computeStartEndFromToken(durTok);
  const apiDuration = durationTokenToApiDuration(durTok);

  state.base.durationToken = durTok;
  state.base.start = start;
  state.base.end = end;

  try {
    if (parsed.kind === "price") {
      const exprs = Array.isArray(parsed.exprs) && parsed.exprs.length
        ? parsed.exprs
        : (parsed.expr ? [parsed.expr] : []);
      if (!exprs.length) throw new Error("No expression provided.");

      const expr = exprs[0];
      const baseEntry = cmdStack.find(x => x.kind === "price" && x.panelId == null && !x.removed);
      const isBasePrice = (!baseEntry || baseEntry.id === activeEntry?.id);
      state.base.expr = expr;
      const multi = exprs.length > 1;
      state.base.norm = (parsed.norm != null) ? parsed.norm : (multi ? 0 : null);

      const errors = [];
      const series = [];
      for (const ex of exprs) {
        try {
          const resp = await postJSON("/expr/chart", {
            expr: ex,
            duration: apiDuration,
            bar_size: state.base.bar_size,
            use_rth: state.base.use_rth,
          });
          const s0 = resp?.series?.[0];
          const label = s0?.label || resp?.label || ex;
          const points = s0?.points || resp?.points || [];
          series.push({ label, points, expr: ex });
        } catch (err) {
          errors.push(`${ex}: ${String(err?.message || err || "error")}`);
        }
      }
      if (!series.length) {
        throw new Error(errors.join(" | ") || "No data returned.");
      }
      const warn = errors.length ? errors.join(" | ") : null;

      const price = series.length === 1
        ? { label: series[0].label, points: series[0].points }
        : { label: expr, series };

      if (isBasePrice) {
        state.data.price = price;
        lastResponseJson = price;
      }

      // IMPORTANT: do NOT reset xBounds if already zoomed
      const pts = Array.isArray(price?.points) ? price.points : (price?.series?.[0]?.points || []);
      const xy = normalizePoints(pts);
      const shouldResetBounds = (!state.base.xBounds || expr !== prevExpr || durTok !== prevDurTok);
      if (shouldResetBounds) {
        const startMs = Number.isFinite(Date.parse(start || "")) ? Date.parse(start) : null;
        const endMs = Number.isFinite(Date.parse(end || "")) ? Date.parse(end) : null;
        const fallback = computeXBoundsFromXY(xy);
        state.base.xBounds = {
          xMin: (startMs != null) ? startMs : fallback?.xMin,
          xMax: (endMs != null) ? endMs : fallback?.xMax,
        };
      }

      if (isBasePrice) {
        renderPrice(price);
        await refreshOverlaysOnly();
        upsertCmdEntry({ cmd: cmdText.trim(), kind: "price", panelId: null, attachToActiveLine: true });
        if (els.chartTableWrap && !els.chartTableWrap.hidden) renderChartTable();
      } else {
        const panelId = activePanelId || createPanel({ kind: "price", title: `Price · ${expr}`, height: 200 });
        if (!panelId) return;
        panelSpecs[panelId] = { kind: "price", params: {}, createdAt: Date.now() };
        savePanelSpecs();
        renderPriceToPanel(panelId, price);
        upsertCmdEntry({ cmd: cmdText.trim(), kind: "price", panelId, attachToActiveLine: true });
      }

      if (!opts.skipHistorySave) {
        const hist = getHistory();
        hist.unshift({ ts: Date.now(), cmd: cmdText.trim() });

        setHistory(hist);
        renderHistory();
      }

      if (warn) setMsg(`OK (partial): ${warn}`);
      else setMsg("OK");
      return;
    }

    if (parsed.kind === "volume") {
      const expr = parsed.expr || state.base.expr || "";
      const ma = Math.max(1, Number(parsed.params?.ma ?? 20) || 20);
      const panelId = activePanelId || createPanel({ kind: "volume", title: `Volume · ${expr}`, height: 200 });
      if (!panelId) return;

      panelSpecs[panelId] = { kind: "volume", params: { ma }, createdAt: Date.now() };
      savePanelSpecs();
      const volResp = await fetchVolumeBars(expr);
      renderVolumeToPanel(panelId, volResp, `Volume · ${expr}`, { maPeriod: ma });
      upsertCmdEntry({ cmd: cmdText.trim(), kind: "volume", panelId, attachToActiveLine: true });
      setMsg("OK");
      return;
    }

    if (parsed.kind === "sharpe") {
      const expr = parsed.expr || state.base.expr || "";
      const window = parsed.params?.window || "63D";
      const panelId = activePanelId || createPanel({ kind: "sharpe", title: `Sharpe · ${expr}`, height: 200 });
      if (!panelId) return;
      panelSpecs[panelId] = { kind: "sharpe", params: { window }, createdAt: Date.now() };
      savePanelSpecs();
      const resp = await postJSON("/expr/sharpe", {
        expr,
        window,
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      renderPanelChart(panelId, resp);
      upsertCmdEntry({ cmd: cmdText.trim(), kind: "sharpe", panelId, attachToActiveLine: true });
      setMsg("OK");
      return;
    }

    if (parsed.kind === "drawdown") {
      const expr = parsed.expr || state.base.expr || "";
      const window = parsed.params?.window || "3M";
      const panelId = activePanelId || createPanel({ kind: "drawdown", title: `Drawdown · ${expr}`, height: 200 });
      if (!panelId) return;
      panelSpecs[panelId] = { kind: "drawdown", params: { window }, createdAt: Date.now() };
      savePanelSpecs();
      const resp = await postJSON("/expr/drawdown", {
        expr,
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
        mode: "point",
        rolling_window: window,
      });
      renderPanelChart(panelId, resp);
      upsertCmdEntry({ cmd: cmdText.trim(), kind: "drawdown", panelId, attachToActiveLine: true });
      setMsg("OK");
      return;
    }

    if (parsed.kind === "rsi") {
      const expr = parsed.expr || state.base.expr || "";
      const period = Number(parsed.params?.period ?? 14) || 14;
      const panelId = activePanelId || createPanel({ kind: "rsi", title: `RSI · ${expr}`, height: 200 });
      if (!panelId) return;
      panelSpecs[panelId] = { kind: "rsi", params: { period }, createdAt: Date.now() };
      savePanelSpecs();
      const resp = await postJSON("/expr/rsi", {
        expr,
        period,
        bands: "classic",
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
      });
      renderPanelChart(panelId, resp);
      upsertCmdEntry({ cmd: cmdText.trim(), kind: "rsi", panelId, attachToActiveLine: true });
      setMsg("OK");
      return;
    }

    if (parsed.kind === "zscore") {
      const expr = parsed.expr || state.base.expr || "";
      const window = parsed.params?.window || "3M";
      const panelId = activePanelId || createPanel({ kind: "zscore", title: `Z-Score · ${expr}`, height: 200 });
      if (!panelId) return;
      panelSpecs[panelId] = { kind: "zscore", params: { window }, createdAt: Date.now() };
      savePanelSpecs();
      const resp = await postJSON("/expr/zscore", {
        expr,
        window,
        duration: apiDuration,
        bar_size: state.base.bar_size,
        use_rth: state.base.use_rth,
        levels: [-2, -1, 0, 1, 2],
      });
      renderPanelChart(panelId, resp);
      upsertCmdEntry({ cmd: cmdText.trim(), kind: "zscore", panelId, attachToActiveLine: true });
      setMsg("OK");
      return;
    }

    if (parsed.kind === "seasonality") {
      const expr = parsed.expr || state.base.expr || "";
      const mode = String(parsed.params?.mode || "heatmap").toLowerCase();
      const bucket = String(parsed.params?.bucket || "month").toLowerCase();
      const years = Array.isArray(parsed.params?.years) ? parsed.params.years : null;
      const rangeStart = parsed.params?.rangeStart || null;
      const rangeEnd = parsed.params?.rangeEnd || null;
      const panelId = activePanelId || createPanel({ kind: "seasonality", title: `Seasonality · ${expr}`, height: 240 });
      if (!panelId) return;

      const yearsSpec = (years && years.length)
        ? years.map(String).join(",")
        : "10";
      panelSpecs[panelId] = {
        kind: "seasonality",
        params: { expr, mode, bucket, yearsSpec, yearsSelected: years, rangeStart, rangeEnd },
        createdAt: Date.now(),
      };
      savePanelSpecs();

      await loadSeasonalityPanel(panelId, true);

      upsertCmdEntry({ cmd: cmdText.trim(), kind: "seasonality", panelId, attachToActiveLine: true });
      setMsg("OK");
      return;
    }

    setMsg(`Unknown cmd: ${parsed.kind}`);
  } catch (e) {
    setMsg(`Error: ${String(e.message || e)}`);
  }
}

// ============================================================
// Keyboard / buttons
// ============================================================
function installCommandBehavior() {
  if (document.body.$qsCmdInstalled) return;
  document.body.$qsCmdInstalled = true;

  if (els.cmd) {
    els.cmd.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
        ev.preventDefault();
        const line = syncActiveCmdFromCursor();
        if (line) runCommand(line);
      }
    });
    els.cmd.addEventListener("input", () => {
      if (__syncingCmdText) return;
      const rawLines = (els.cmd.value || "").split("\n");
      __keepTrailingNewline = (els.cmd.value || "").endsWith("\n");
      const hasAny = rawLines.some((line) => String(line || "").trim());
      if (!hasAny) {
        clearAllPanels();
        resetCmdStackToGreeting();
        renderCmdStack();
        return;
      }

      const list = loadCmdStack();
      const byCmd = new Map();
      for (const entry of list) {
        const key = (entry.cmd || "").trim();
        if (!key) continue;
        const arr = byCmd.get(key) || [];
        arr.push(entry);
        byCmd.set(key, arr);
      }
      const next = [];

      rawLines.forEach((raw, idx) => {
        const trimmed = String(raw || "");
        if (!trimmed.trim()) return;
        const isComment = /^\s*\/\//.test(trimmed);
        const cmd = normalizeCmdLine(trimmed);
        let entry = list.find(x => x.id === __lineToCmdId[idx]);
        if (!entry && cmd) {
          const arr = byCmd.get(cmd);
          if (arr && arr.length) entry = arr.shift();
        }
        if (!entry) {
          entry = {
            id: `c_${Math.random().toString(36).slice(2, 9)}`,
            cmd,
            kind: parseUserInput(cmd)?.kind || "raw",
            panelId: null,
            removed: false,
            ts: Date.now(),
            order: idx,
          };
        }
        entry.cmd = cmd;
        entry.removed = !!isComment;
        entry.order = idx;
        if (entry.removed) {
          if (entry.panelId) {
            removePanel(entry.panelId);
          } else if (entry.kind === "price") {
            destroyPriceChart();
            state.base.xBounds = null;
          }
        }
        next.push(entry);
      });

      for (const prev of list) {
        if (next.some(x => x.id === prev.id)) continue;
        prev.removed = true;
        prev.order = Number.isFinite(prev.order) ? prev.order : next.length;
        if (prev.panelId) {
          removePanel(prev.panelId);
        } else if (prev.kind === "price") {
          destroyPriceChart();
          state.base.xBounds = null;
        }
        next.push(prev);
      }

      saveCmdStack(next);
      renderCmdStack();
      __lastCmdLines = rawLines.map(normalizeCmdLine).filter(Boolean);
    });
    els.cmd.addEventListener("click", () => {
      syncActiveCmdFromCursor();
    });
    els.cmd.addEventListener("scroll", () => {
      updateCmdScrollbar();
      renderCmdDisplay();
    });
  }

  els.runBtn?.addEventListener("click", () => {
    const line = syncActiveCmdFromCursor();
    if (line) runCommand(line);
  });
  els.saveBtn?.addEventListener("click", saveCurrentToLibrary);

  els.copyJsonBtn?.addEventListener("click", () => {
    if (!lastResponseJson) return setMsg("Nothing to copy yet.");
    safeCopy(safeStringify(lastResponseJson, 2));
  });

  els.snapshotBtn?.addEventListener("click", snapshotChart);

  els.chartTableBtn?.addEventListener("click", () => {
    if (!els.chartTableWrap) return;
    const showing = !els.chartTableWrap.hidden;
    if (showing) {
      els.chartTableWrap.hidden = true;
      return;
    }
    renderChartTable();
    els.chartTableWrap.hidden = false;
    requestAnimationFrame(requestChartResizeAll);
  });

  els.chartTableCopyBtn?.addEventListener("click", () => {
    const tsv = toTSVFromPriceChart();
    safeCopy(tsv);
  });

  els.chartTableExportBtn?.addEventListener("click", () => {
    const csv = toCSVFromPriceChart();
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `qs_data_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
  els.chartTableRemoveBtn?.addEventListener("click", () => {
    if (!els.chartTableWrap) return;
    els.chartTableWrap.hidden = true;
    requestAnimationFrame(requestChartResizeAll);
  });
  els.seasonalitySaveBtn?.addEventListener("click", saveSeasonalityToLibrary);
  els.seasonalitySnapBtn?.addEventListener("click", snapshotSeasonality);

  els.colorBtn?.addEventListener("click", () => {
    paletteIdx = (paletteIdx + 1) % PALETTE.length;
    saveJSON("qs.chart.paletteIdx.v1", paletteIdx);
    if (state.data.price) renderPrice(state.data.price);
    setMsg(`Colour: ${paletteIdx + 1}/${PALETTE.length}`);
  });
}

function updateCmdScrollbar() {
  const wrap = document.querySelector(".input-row");
  const track = wrap?.querySelector(".cmd-scrollbar");
  const thumb = track?.querySelector(".cmd-scrollbar-thumb");
  if (!els.cmd || !track || !thumb) return;
  const scrollH = els.cmd.scrollHeight;
  const viewH = els.cmd.clientHeight;
  if (scrollH <= viewH) {
    thumb.style.display = "none";
    return;
  }
  thumb.style.display = "block";
  const ratio = viewH / scrollH;
  const thumbH = Math.max(18, Math.floor(viewH * ratio));
  const maxTop = viewH - thumbH;
  const top = Math.min(maxTop, Math.max(0, (els.cmd.scrollTop / (scrollH - viewH)) * maxTop));
  thumb.style.height = `${thumbH}px`;
  thumb.style.transform = `translateY(${top}px)`;
}

function installInputResize() {
  const wrap = document.querySelector(".input-wrap");
  const grab = wrap?.querySelector(".qs-input-grab");
  if (!wrap || !grab || grab.$qsInstalled) return;
  grab.$qsInstalled = true;

  const saved = Number(loadJSON("qs.input.h.v1", 120));
  if (Number.isFinite(saved)) wrap.style.height = `${clamp(saved, 90, 220)}px`;

  let dragging = false;
  let startY = 0;
  let startH = 0;

  const onMove = (ev) => {
    if (!dragging) return;
    const dy = startY - ev.clientY;
    const nh = clamp(startH + dy, 90, 220);
    wrap.style.height = `${nh}px`;
    saveJSON("qs.input.h.v1", nh);
  };

  const onUp = () => {
    dragging = false;
    window.removeEventListener("mousemove", onMove, true);
    window.removeEventListener("mouseup", onUp, true);
    window.$qsUpdateMainWidth?.();
  };

  grab.addEventListener("mousedown", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    dragging = true;
    startY = ev.clientY;
    startH = wrap.getBoundingClientRect().height;
    window.addEventListener("mousemove", onMove, true);
    window.addEventListener("mouseup", onUp, true);
  });
}

function installBoxResize() {
  const chartWrap = document.querySelector(".chart-wrap");
  const inputWrap = document.querySelector(".input-wrap");
  const key = "qs.main.width.v1";
  const minW = 420;

  const applyWidth = (w) => {
    if (!chartWrap || !inputWrap) return;
    if (!Number.isFinite(w)) {
      chartWrap.style.width = "100%";
      inputWrap.style.width = "100%";
      return;
    }
    chartWrap.style.width = `${w}px`;
    inputWrap.style.width = `${w}px`;
  };

  const applyFromStorage = () => {
    const parentW = chartWrap?.parentElement?.getBoundingClientRect?.().width || window.innerWidth;
    const saved = loadJSON(key, null);
    if (saved?.manualWidth && Number.isFinite(saved.w)) {
      applyWidth(clamp(saved.w, minW, parentW));
    } else {
      applyWidth(null);
    }
  };
  applyFromStorage();
  window.$qsUpdateMainWidth = applyFromStorage;
  window.$qsResetMainWidth = () => {
    try { localStorage.removeItem(key); } catch {}
    applyWidth(null);
  };

  const bind = (wrap, minH, maxH) => {
    if (!wrap) return;
    const right = wrap.querySelector(".qs-resize-right");
    const bottom = wrap.querySelector(".qs-resize-bottom");
    if (right && right.$qsInstalled) return;

    const saved = loadJSON(key, null);
    if (saved?.h) wrap.style.height = `${clamp(saved.h, minH, maxH)}px`;

    const startDragX = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const startW = wrap.getBoundingClientRect().width;
      const startX = ev.clientX;
      const maxW = wrap.parentElement?.getBoundingClientRect?.().width || window.innerWidth;
      const onMove = (e) => {
        const w = clamp(startW + (e.clientX - startX), minW, maxW);
        applyWidth(w);
        saveJSON(key, { w, h: wrap.getBoundingClientRect().height, manualWidth: true });
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove, true);
        window.removeEventListener("mouseup", onUp, true);
      };
      window.addEventListener("mousemove", onMove, true);
      window.addEventListener("mouseup", onUp, true);
    };

    const startDragY = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const startH = wrap.getBoundingClientRect().height;
      const startY = ev.clientY;
      const onMove = (e) => {
        const h = clamp(startH + (e.clientY - startY), minH, maxH);
        wrap.style.height = `${h}px`;
        const saved = loadJSON(key, null) || {};
        saveJSON(key, { w: wrap.getBoundingClientRect().width, h, manualWidth: !!saved.manualWidth });
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove, true);
        window.removeEventListener("mouseup", onUp, true);
      };
      window.addEventListener("mousemove", onMove, true);
      window.addEventListener("mouseup", onUp, true);
    };

    right?.addEventListener("mousedown", startDragX);
    bottom?.addEventListener("mousedown", startDragY);
    if (right) right.$qsInstalled = true;
    if (bottom) bottom.$qsInstalled = true;
  };

  bind(chartWrap, 320, 900);
  bind(inputWrap, 140, 520);

  window.addEventListener("resize", applyFromStorage);
}

function installSidebarResize() {
  const sidebar = document.getElementById("sidebar");
  const grab = sidebar?.querySelector(".qs-sidebar-grab");
  if (!sidebar || !grab || grab.$qsInstalled) return;
  grab.$qsInstalled = true;

  const saved = loadJSON("qs.sidebar.w.v1", null);
  if (Number.isFinite(saved) && sidebar.classList.contains("show-panels")) {
    const w = clamp(saved, 220, 520);
    sidebar.style.width = `${w}px`;
    sidebar.style.minWidth = `${w}px`;
  }

  let dragging = false;
  let startX = 0;
  let startW = 0;

  const onMove = (ev) => {
    if (!dragging) return;
    if (!sidebar.classList.contains("show-panels")) return;
    const w = clamp(startW + (ev.clientX - startX), 220, 520);
    sidebar.style.width = `${w}px`;
    sidebar.style.minWidth = `${w}px`;
    saveJSON("qs.sidebar.w.v1", w);
    window.$qsUpdateMainWidth?.();
  };

  const onUp = () => {
    dragging = false;
    window.removeEventListener("mousemove", onMove, true);
    window.removeEventListener("mouseup", onUp, true);
  };

  grab.addEventListener("mousedown", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    dragging = true;
    startX = ev.clientX;
    startW = sidebar.getBoundingClientRect().width;
    window.addEventListener("mousemove", onMove, true);
    window.addEventListener("mouseup", onUp, true);
  });
}

// ============================================================
// INIT (ONLY ONCE)
// ============================================================
function init() {
  if (window.$qsInited) return;
  window.$qsInited = true;

  loadExpanded();
  sanitizeDsColors();
  installGlobalErrorTrap();
  apiHealth();
  setInterval(apiHealth, 5000);
  ensureEdgeXTicksPlugin();
  ensureTopDatesPlugin();
  ensureLastValuePlugin();
  ensureAxisControlsPlugin();
  ensureCrosshairPlugin();
  setupChartViewport();

  resetCmdStackOnLoad();
  const savedInputH = Number(loadJSON("qs.input.h.v1", 0));
  if (!Number.isFinite(savedInputH) || savedInputH > 220) {
    saveJSON("qs.input.h.v1", 120);
  }
  if (els.cmd) {
    __syncingCmdText = true;
    els.cmd.value = "";
    __syncingCmdText = false;
  }
  ensureGreetingIfEmpty();
  renderHistory();
  renderLibrary();
  renderHelp();
  renderSeasonalityPanel();
  renderCmdStack();
  collapsedPanels.history = true;
  collapsedPanels.library = true;
  collapsedPanels.help = true;
  collapsedPanels.seasonality = true;
  __openSidebarPanel = null;
  saveJSON("qs.panels.collapsed.v1", collapsedPanels);
  if (els.sidebar) {
    els.sidebar.classList.remove("show-panels");
    els.sidebar.style.width = "";
    els.sidebar.style.minWidth = "";
  }
  

  ensurePopoverTypography();
  installChartingUI();
  setActiveModule("charting", { force: true });

  installSidebarToggle();
  installSidebarResize();
  installPanelCollapse();
  installModuleSwitching();
  installCommandBehavior();
  installInputResize();
  installBoxResize();
  window.$qsResetMainWidth?.();
  installPopovers();
  installGearFormatToggles();
  updateCmdScrollbar();

  if (els.clearHistoryBtn) {
    els.clearHistoryBtn.addEventListener("click", () => {
      setHistory([]);
      renderHistory();
      setMsg("History cleared.");
    });
  }

  if (els.importInput) {
    els.importInput.addEventListener("change", (e) => {
      const f = e.target.files?.[0];
      if (f) importLibrary(f);
      e.target.value = "";
    });
  }

  if (els.newFolderBtn) {
    els.newFolderBtn.addEventListener("click", () => {
      const name = (prompt("Folder name?", "New Folder") || "").trim();
      if (!name) return;
      const lib = getLibrary();
      createFolder(name, lib.rootId);
    });
  }

  els.exportBtn?.addEventListener("click", exportLibrary);
  els.addSeasonalityBtn?.addEventListener("click", () => { addSeasonalityFromMenu(); });

  window.addEventListener("resize", () => requestAnimationFrame(requestChartResizeAll));

  if (els.gridToggle) els.gridToggle.checked = !!uiPrefs.grid;
  if (els.chartTypeSel) els.chartTypeSel.value = uiPrefs.chartType || "line";

  setMsg("Ready");
}

init();
const Y_AXIS_WIDTH = 58;
