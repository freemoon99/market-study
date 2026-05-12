const state = {
  day: null,
  selectedCode: null,
  filter: "",
  typeFilter: "all",
  themeFilter: "",
  view: "detailView",
};

const $ = (id) => document.getElementById(id);
const fmt = new Intl.NumberFormat("ko-KR");
const chartViews = {};

function number(value, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  return `${fmt.format(Math.round(Number(value) * 100) / 100)}${suffix}`;
}

function signed(value, suffix = "%") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}${suffix}`;
}

function marketCap(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  const uk = Math.round(Number(value) / 100000000);
  if (uk >= 10000) {
    const jo = uk / 10000;
    return `${Number.isInteger(jo) ? fmt.format(jo) : fmt.format(Math.round(jo * 10) / 10)}조원`;
  }
  return `${fmt.format(uk)}억원`;
}

function clsByRate(value) {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "";
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || "요청 실패");
  return data;
}

function setStatus(text) {
  $("status").textContent = text;
}

function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function boot() {
  const dates = await api("/api/dates");
  applyTheme(localStorage.getItem("marketStudyTheme") || "dark");
  $("dateInput").value = dates.dates[0] || dates.today;
  bind();
  if (dates.dates.length) {
    await loadDay($("dateInput").value);
  }
}

function bind() {
  $("loadBtn").addEventListener("click", () => loadDay($("dateInput").value));
  $("refreshBtn").addEventListener("click", () => refreshDay($("dateInput").value));
  $("exportBtn").addEventListener("click", exportMd);
  $("themeBtn").addEventListener("click", toggleTheme);
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
  });
  $("searchInput").addEventListener("input", (event) => {
    state.filter = event.target.value.trim().toLowerCase();
    renderList();
    renderQuadrants();
    renderRrg();
  });
  $("filterSelect").addEventListener("change", (event) => {
    state.typeFilter = event.target.value;
    renderList();
    renderQuadrants();
    renderRrg();
  });
}

function applyTheme(mode) {
  document.body.dataset.theme = mode;
  localStorage.setItem("marketStudyTheme", mode);
  $("themeBtn").setAttribute("aria-pressed", mode === "dark" ? "true" : "false");
  $("themeLabel").textContent = mode === "dark" ? "Dark" : "Light";
}

function toggleTheme() {
  applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
  renderDetail();
  renderQuadrants();
  renderRrg();
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.id === view));
  document.querySelectorAll(".tab").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  if (view === "quadrantView") renderQuadrants();
  if (view === "rrgView") renderRrg();
}

async function loadDay(date) {
  setStatus(`${date} 기록을 불러오는 중입니다.`);
  state.day = await api(`/api/day?date=${encodeURIComponent(date)}`);
  state.selectedCode = state.day.stocks[0]?.code || null;
  render();
  setStatus(state.day.refreshed_at ? `${date} 기록 표시 중 · 마지막 갱신 ${state.day.refreshed_at}` : `${date} 저장 기록이 없습니다.`);
}

async function refreshDay(date) {
  setStatus(`${date} 데이터를 수집하는 중입니다. 종목 수에 따라 조금 걸릴 수 있습니다.`);
  $("refreshBtn").disabled = true;
  try {
    state.day = await api("/api/refresh", {
      method: "POST",
      body: JSON.stringify({ date, sampleOnFail: true }),
    });
    state.selectedCode = state.day.stocks[0]?.code || null;
    render();
    if (state.day.warning) toast(state.day.warning);
    setStatus(`${date} 갱신 완료 · ${state.day.counts.total}종목`);
  } catch (error) {
    const message = `갱신 실패: ${error.message}`;
    setStatus(message);
    toast(message);
  } finally {
    $("refreshBtn").disabled = false;
  }
}

async function exportMd() {
  if (!state.day) return;
  const data = await api(`/api/export?date=${encodeURIComponent(state.day.date)}`);
  const blob = new Blob([data.markdown || ""], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = data.filename || `market-summary-${state.day.date}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  toast("Markdown 다운로드를 시작했습니다.");
}

function render() {
  $("limitCount").textContent = state.day.counts.limit_up;
  $("volumeCount").textContent = state.day.counts.high_volume;
  $("totalCount").textContent = state.day.counts.total;
  renderThemes();
  renderList();
  renderDetail();
  renderQuadrants();
  renderRrg();
  setView(state.view);
}

function renderThemes() {
  const wrap = $("themeTags");
  wrap.innerHTML = "";
  const themes = state.day?.insights?.themes || [];
  const clear = document.createElement("button");
  clear.className = `theme-tag ${state.themeFilter ? "" : "active"}`;
  clear.textContent = "전체";
  clear.addEventListener("click", () => {
    state.themeFilter = "";
    renderThemes();
    renderList();
    renderQuadrants();
    renderRrg();
  });
  wrap.appendChild(clear);
  if (!themes.length) {
    wrap.innerHTML = `<span class="theme-tag muted">테마 없음</span>`;
  }
  themes.forEach((theme) => {
    const chip = document.createElement("button");
    chip.className = `theme-tag ${state.themeFilter === theme.name ? "active" : ""}`;
    chip.textContent = `#${theme.name} ${theme.count}`;
    chip.title = theme.stocks.slice(0, 6).join(", ");
    chip.addEventListener("click", () => {
      state.themeFilter = state.themeFilter === theme.name ? "" : theme.name;
      state.typeFilter = state.themeFilter ? "theme" : "all";
      $("filterSelect").value = state.typeFilter;
      renderThemes();
      renderList();
      renderQuadrants();
      renderRrg();
    });
    wrap.appendChild(chip);
  });
  $("moodText").textContent = state.day?.insights?.mood || "";
}

function getFilteredStocks() {
  return (state.day?.stocks || []).filter((s) => {
    const key = `${s.name} ${s.code} ${(s.themes || []).join(" ")} ${(s.display_tags || s.tags).join(" ")}`.toLowerCase();
    const textOk = !state.filter || key.includes(state.filter);
    const themeOk = !state.themeFilter || (s.themes || []).includes(state.themeFilter);
    let typeOk = true;
    if (state.typeFilter === "limit") typeOk = s.tags.includes("상한가");
    if (state.typeFilter === "volume") typeOk = s.tags.includes("거래량 1000만주");
    if (state.typeFilter === "streak") typeOk = (s.streak_tags || []).length > 0;
    if (state.typeFilter === "theme") typeOk = (s.themes || []).length > 0;
    return textOk && themeOk && typeOk;
  });
}

function renderList() {
  const list = $("stockList");
  list.innerHTML = "";
  const stocks = getFilteredStocks();
  if (!stocks.find((s) => s.code === state.selectedCode)) {
    state.selectedCode = stocks[0]?.code || state.day?.stocks[0]?.code || null;
  }
  for (const stock of stocks) {
    const tpl = $("stockButtonTemplate").content.cloneNode(true);
    const btn = tpl.querySelector("button");
    btn.classList.toggle("active", stock.code === state.selectedCode);
    tpl.querySelector(".stock-button-name").textContent = `${stock.name} (${stock.code})`;
    tpl.querySelector(".stock-button-meta").textContent = `${(stock.display_tags || stock.tags).join(" · ")} · ${signed(stock.change_rate)} · ${number(stock.volume)}주`;
    btn.addEventListener("click", () => {
      state.selectedCode = stock.code;
      renderList();
      renderDetail();
    });
    list.appendChild(tpl);
  }
}

function tagClass(tag) {
  if (tag.includes("상한가")) return "tag limit";
  if (tag.includes("거래량")) return "tag volume";
  if (tag.includes("일째")) return "tag streak";
  return "tag";
}

function renderDetail() {
  const detail = $("detail");
  const stock = state.day?.stocks.find((s) => s.code === state.selectedCode);
  if (!stock) {
    detail.className = "detail empty";
    detail.innerHTML = `<div class="empty-state">표시할 종목이 없습니다. 휴장일이라면 이전 거래일을 선택해보세요.</div>`;
    return;
  }
  detail.className = "detail";
  detail.innerHTML = `
    <div class="detail-head">
      <div>
        <div class="title-row">
          <h2>${escapeHtml(stock.name)}</h2>
          <span class="code">${stock.code}</span>
          ${(stock.display_tags || stock.tags).map((t) => `<span class="${tagClass(t)}">${t}</span>`).join("")}
          ${(stock.themes || []).map((t) => `<span class="tag theme">#${escapeHtml(t)}</span>`).join("")}
        </div>
        <p>${stock.market || "-"} ${stock.sector ? `· ${escapeHtml(stock.sector)}` : ""}</p>
      </div>
      <button class="primary" id="saveBtn">저장</button>
    </div>

    <div class="price-grid">
      ${metric("현재가", `${number(stock.price, "원")}`, clsByRate(stock.change_rate))}
      ${metric("등락률", signed(stock.change_rate), clsByRate(stock.change_rate))}
      ${metric("거래량", `${number(stock.volume)}주`, "")}
      ${metric("거래량 변화", `전일 ${signed(stock.volume_vs_prev_pct)} · 평균 ${signed(stock.volume_vs_avg20_pct)}`, (stock.volume_vs_avg20_pct || 0) > 0 ? "good" : "")}
    </div>

    <div class="chart-wrap">
      <div class="chart-toolbar">
        <span>휠: 확대/축소 · 드래그: 이동</span>
        <div>
          <a href="https://finance.naver.com/item/main.naver?code=${stock.code}" target="_blank" rel="noreferrer">Naver</a>
          <a href="https://www.tradingview.com/chart/?symbol=KRX%3A${stock.code}" target="_blank" rel="noreferrer">TradingView</a>
          <button id="chartResetBtn">초기화</button>
        </div>
      </div>
      <canvas id="chartCanvas" width="1100" height="360"></canvas>
    </div>

    <div class="metric-grid">
      ${metric("시가총액", marketCap(stock.market_cap), "", help("market_cap"))}
      ${metric("PER", compare(stock.per, stock.sector_per), "", help("per"))}
      ${metric("PBR", compare(stock.pbr, stock.sector_pbr), "", help("pbr"))}
      ${metric("ROE", number(stock.roe, "%"), "", help("roe"))}
      ${metric("EPS", number(stock.eps, "원"), "", help("eps"))}
    </div>

    <div class="split">
      <section>
        <h3>상승/거래량 원인 후보</h3>
        <div id="reasons" class="reasons"></div>
        <div class="actions">
          <button id="addReasonBtn">추가</button>
        </div>
      </section>
      <section class="note">
        <h3>학습 노트</h3>
        <p class="note-guide">회사 소개, 사업군, 오늘의 테마는 자동 초안입니다. 필요한 만큼 고치고, 내 의견을 중심으로 복기하세요.</p>
        <textarea id="noteInput" spellcheck="false"></textarea>
      </section>
    </div>
  `;
  $("noteInput").value = stock.note || "";
  renderReasons(stock);
  bindInteractiveChart($("chartCanvas"), stock);
  $("chartResetBtn").addEventListener("click", () => {
    delete chartViews[stock.code];
    bindInteractiveChart($("chartCanvas"), stock);
  });
  $("addReasonBtn").addEventListener("click", () => {
    stock.reasons.push({ text: "", url: "", auto: false });
    renderReasons(stock);
  });
  $("saveBtn").addEventListener("click", () => saveStock(stock));
}

function renderQuadrants() {
  const root = $("quadrants");
  if (!root || !state.day) return;
  const stocks = getFilteredStocks();
  const nodes = layoutNodes(stocks.map((stock) => ({
    stock,
    x: quadrantX(stock),
    y: quadrantY(stock),
  })));
  root.innerHTML = `
    <div class="quad-label top-left">가격 선행</div>
    <div class="quad-label top-right">주도 후보</div>
    <div class="quad-label bottom-left">후순위 관찰</div>
    <div class="quad-label bottom-right">수급 포착</div>
    <div class="axis-caption x-left">거래량 약함</div>
    <div class="axis-caption x-right">거래량 강함</div>
    <div class="axis-caption y-top">상승률 높음</div>
    <div class="axis-caption y-bottom">상승률 낮음</div>
    ${nodes.map((node) => plotNode(node.stock, node.x, node.y)).join("")}
  `;
  bindPlotNodes(root);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function quadrantX(stock) {
  const energyRaw = Number(stock.volume_vs_avg20_pct ?? stock.volume_vs_prev_pct ?? 0);
  return clamp(50 + energyRaw / 8, 12, 88);
}

function quadrantY(stock) {
  const momentumRaw = Number(stock.change_rate || 0);
  return clamp(88 - momentumRaw * 2.45, 12, 88);
}

function layoutNodes(items) {
  const placed = [];
  const offsets = [
    [0, 0], [7, 0], [-7, 0], [0, 5], [0, -5], [7, 5], [-7, 5], [7, -5], [-7, -5],
    [14, 0], [-14, 0], [0, 10], [0, -10], [14, 6], [-14, 6], [14, -6], [-14, -6],
  ];
  const sorted = [...items].sort((a, b) => (b.stock.change_rate || 0) - (a.stock.change_rate || 0));
  for (const item of sorted) {
    let best = { x: item.x, y: item.y };
    for (const [dx, dy] of offsets) {
      const candidate = { x: clamp(item.x + dx, 12, 88), y: clamp(item.y + dy, 12, 88) };
      const overlaps = placed.some((p) => Math.abs(p.x - candidate.x) < 8.5 && Math.abs(p.y - candidate.y) < 4.8);
      if (!overlaps) {
        best = candidate;
        break;
      }
    }
    placed.push({ ...item, ...best });
  }
  return placed;
}

function plotNode(stock, x, y) {
  const cls = stock.tags.includes("상한가") ? "limit" : stock.tags.includes("거래량 1000만주") ? "volume" : "";
  return `<button class="stock-node ${cls}" data-code="${stock.code}" style="left:${x}%; top:${y}%">${escapeHtml(stock.name)}</button>`;
}

function bindPlotNodes(root) {
  root.querySelectorAll(".stock-node").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedCode = node.dataset.code;
      setView("detailView");
      renderList();
      renderDetail();
    });
  });
}

function pctReturn(closes, endIndex, length) {
  const end = endIndex < 0 ? closes.length + endIndex : endIndex;
  const start = end - length;
  if (start < 0 || !closes[start] || !closes[end]) return null;
  return (closes[end] - closes[start]) / closes[start] * 100;
}

function rrgMetricsAt(stock, endOffset = 0) {
  const closes = (stock.chart || []).map((row) => Number(row.close)).filter(Boolean);
  const end = closes.length - 1 - endOffset;
  const strength = pctReturn(closes, end, 20) ?? Number(stock.change_rate || 0);
  const recent = pctReturn(closes, end, 5) ?? 0;
  const prior = pctReturn(closes, end - 5, 5) ?? 0;
  return { strength, momentum: recent - prior };
}

function rrgMetrics(stock) {
  return rrgMetricsAt(stock, 0);
}

function median(values) {
  const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!sorted.length) return 0;
  return sorted[Math.floor(sorted.length / 2)];
}

function renderRrg() {
  const root = $("rrgPlot");
  if (!root || !state.day) return;
  const stocks = getFilteredStocks();
  const metrics = stocks.map((stock) => ({ stock, ...rrgMetrics(stock) }));
  const baseStrength = median(metrics.map((m) => m.strength));
  const nodes = layoutNodes(metrics.map((m) => ({
    stock: m.stock,
    x: clamp(50 + (m.strength - baseStrength) * 1.3, 12, 88),
    y: clamp(50 - m.momentum * 3.2, 12, 88),
  })));
  root.innerHTML = `
    <div class="quad-label top-left">Weakening</div>
    <div class="quad-label top-right">Leading</div>
    <div class="quad-label bottom-left">Lagging</div>
    <div class="quad-label bottom-right">Improving</div>
    <div class="axis-caption x-left">상대강도 낮음</div>
    <div class="axis-caption x-right">상대강도 높음</div>
    <div class="axis-caption y-top">모멘텀 높음</div>
    <div class="axis-caption y-bottom">모멘텀 낮음</div>
    ${nodes.map((node) => plotNode(node.stock, node.x, node.y)).join("")}
  `;
  bindPlotNodes(root);
}

function help(key) {
  const text = state.day.help[key] || "";
  return `<span class="hint" data-tooltip="${escapeAttr(text)}" tabindex="0" aria-label="${escapeAttr(text)}">?</span>`;
}

function compare(value, sectorValue) {
  const base = number(value);
  if (sectorValue === null || sectorValue === undefined) return base;
  return `${base} (업종 ${number(sectorValue)})`;
}

function metric(label, value, className = "", hint = "") {
  return `<div class="metric"><label>${label}${hint}</label><strong class="${className}">${value}</strong></div>`;
}

function renderReasons(stock) {
  const wrap = $("reasons");
  wrap.innerHTML = "";
  stock.reasons.forEach((reason, index) => {
    const row = document.createElement("div");
    row.className = "reason";
    row.innerHTML = `
      <input value="${escapeAttr(reason.text || "")}" placeholder="원인 또는 확인할 뉴스">
      <button title="삭제">×</button>
    `;
    row.querySelector("input").addEventListener("input", (event) => {
      reason.text = event.target.value;
    });
    row.querySelector("button").addEventListener("click", () => {
      stock.reasons.splice(index, 1);
      renderReasons(stock);
    });
    wrap.appendChild(row);
    if (reason.url) {
      const link = document.createElement("a");
      link.href = reason.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "기사 열기";
      wrap.appendChild(link);
    }
  });
}

async function saveStock(stock) {
  stock.note = $("noteInput").value;
  await api(`/api/stocks/${encodeURIComponent(state.day.date)}/${encodeURIComponent(stock.code)}`, {
    method: "POST",
    body: JSON.stringify({ reasons: stock.reasons, note: stock.note }),
  });
  toast(`${stock.name} 저장 완료`);
}

function getChartView(stock) {
  const rows = stock.chart || [];
  if (!chartViews[stock.code]) {
    chartViews[stock.code] = { end: rows.length, count: Math.min(60, rows.length || 60) };
  }
  const view = chartViews[stock.code];
  const minCount = Math.min(20, rows.length || 1);
  const maxCount = Math.max(minCount, rows.length || 60);
  view.count = clamp(view.count, minCount, maxCount);
  view.end = clamp(view.end, view.count, rows.length || view.count);
  return view;
}

function bindInteractiveChart(canvas, stock) {
  const rows = stock.chart || [];
  const view = getChartView(stock);
  drawChart(canvas, rows, view);
  let dragging = false;
  let startX = 0;
  let startEnd = view.end;

  canvas.onwheel = (event) => {
    event.preventDefault();
    const current = getChartView(stock);
    const delta = event.deltaY > 0 ? 6 : -6;
    const minCount = Math.min(20, rows.length || 1);
    const maxCount = Math.max(minCount, rows.length || 60);
    current.count = clamp(current.count + delta, minCount, maxCount);
    current.end = clamp(current.end, current.count, rows.length || current.count);
    drawChart(canvas, rows, current);
  };

  canvas.onmousedown = (event) => {
    dragging = true;
    startX = event.clientX;
    startEnd = getChartView(stock).end;
    canvas.classList.add("dragging");
  };

  window.onmouseup = () => {
    dragging = false;
    canvas.classList.remove("dragging");
  };

  canvas.onmousemove = (event) => {
    if (!dragging) return;
    const current = getChartView(stock);
    const pixelsPerBar = canvas.clientWidth / Math.max(1, current.count);
    const movedBars = Math.round((startX - event.clientX) / pixelsPerBar);
    current.end = clamp(startEnd + movedBars, current.count, rows.length || current.count);
    drawChart(canvas, rows, current);
  };
}

function drawChart(canvas, rows, view = null) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const css = getComputedStyle(document.body);
  const panel = css.getPropertyValue("--panel").trim() || "#fff";
  const line = css.getPropertyValue("--line").trim() || "#e6edf1";
  const muted = css.getPropertyValue("--muted").trim() || "#69757f";
  const red = css.getPropertyValue("--red").trim() || "#d94444";
  const blue = css.getPropertyValue("--blue").trim() || "#246bb2";
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = panel;
  ctx.fillRect(0, 0, w, h);
  if (!rows.length) {
    ctx.fillStyle = muted;
    ctx.fillText("차트 데이터가 없습니다.", 24, 40);
    return;
  }
  const currentView = view || { end: rows.length, count: Math.min(60, rows.length) };
  const data = rows.slice(Math.max(0, currentView.end - currentView.count), currentView.end);
  const pad = { l: 48, r: 18, t: 18, b: 28 };
  const priceH = 235;
  const volTop = 275;
  const maxP = Math.max(...data.map((d) => d.high || d.close));
  const minP = Math.min(...data.map((d) => d.low || d.close));
  const maxV = Math.max(...data.map((d) => d.volume || 0));
  const xStep = (w - pad.l - pad.r) / data.length;
  const priceY = (p) => pad.t + (maxP - p) / Math.max(1, maxP - minP) * priceH;
  const volY = (v) => h - pad.b - (v / Math.max(1, maxV)) * 58;

  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = pad.t + (priceH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }

  ctx.fillStyle = muted;
  ctx.font = "12px sans-serif";
  ctx.fillText(number(maxP), 4, pad.t + 8);
  ctx.fillText(number(minP), 4, pad.t + priceH);
  ctx.fillText("거래량", 4, volTop + 14);

  data.forEach((d, i) => {
    const x = pad.l + i * xStep + xStep / 2;
    const open = d.open || d.close;
    const close = d.close || open;
    const high = d.high || Math.max(open, close);
    const low = d.low || Math.min(open, close);
    const rising = close >= open;
    const color = rising ? red : blue;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, priceY(high));
    ctx.lineTo(x, priceY(low));
    ctx.stroke();
    const bodyTop = Math.min(priceY(open), priceY(close));
    const bodyH = Math.max(2, Math.abs(priceY(open) - priceY(close)));
    ctx.fillRect(x - Math.max(2, xStep * 0.28), bodyTop, Math.max(4, xStep * 0.56), bodyH);
    ctx.globalAlpha = 0.34;
    ctx.fillRect(x - Math.max(2, xStep * 0.28), volY(d.volume || 0), Math.max(4, xStep * 0.56), h - pad.b - volY(d.volume || 0));
    ctx.globalAlpha = 1;
  });

  ctx.fillStyle = muted;
  const first = data[0].trade_date?.slice(5) || "";
  const last = data[data.length - 1].trade_date?.slice(5) || "";
  ctx.fillText(first, pad.l, h - 8);
  ctx.fillText(last, w - 58, h - 8);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

boot().catch((error) => {
  setStatus(error.message);
  toast(error.message);
});
