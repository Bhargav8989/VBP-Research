(() => {
  const state = {
    symbol: "RELIANCE",
    eventType: "RESULTS",
    before: 20,
    after: 10,
    dayMode: "trading",
    normalizeTo: "start",
    limit: 8,
    includeNifty: true,
    customDates: "",
    data: null,
    selectedEventIndex: null,
    dropdownItems: [],
    dropdownActiveIdx: -1,
  };

  // DOM refs
  const stockSearchEl = document.getElementById("stockSearch");
  const selectedSymbolBadgeEl = document.getElementById("selectedSymbolBadge");
  const searchDropdownEl = document.getElementById("searchDropdown");
  const beforeDaysEl = document.getElementById("beforeDays");
  const afterDaysEl = document.getElementById("afterDays");
  const limitSelectEl = document.getElementById("limitSelect");
  const includeNiftyEl = document.getElementById("includeNifty");
  const customDatesRowEl = document.getElementById("customDatesRow");
  const customDatesInputEl = document.getElementById("customDatesInput");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const refreshBtn = document.getElementById("refreshBtn");
  const exportCsvBtn = document.getElementById("exportCsvBtn");
  const statusBannerEl = document.getElementById("statusBanner");
  const loadingStateEl = document.getElementById("loadingState");
  const resultsContainerEl = document.getElementById("resultsContainer");
  const upcomingBannerEl = document.getElementById("upcomingBanner");
  const recommendationsSectionEl = document.getElementById("recommendationsSection");
  const recommendationsGridEl = document.getElementById("recommendationsGrid");
  const recommendationsDisclaimerEl = document.getElementById("recommendationsDisclaimer");
  const rangeComparisonBoxEl = document.getElementById("rangeComparisonBox");
  const rangeComparisonBodyEl = document.getElementById("rangeComparisonBody");
  const kpiGridEl = document.getElementById("kpiGrid");
  const eventsTableBodyEl = document.getElementById("eventsTableBody");
  const eventCountBadgeEl = document.getElementById("eventCountBadge");
  const showPriceLineEl = document.getElementById("showPriceLine");
  const showIndividualLinesEl = document.getElementById("showIndividualLines");
  const showMedianLineEl = document.getElementById("showMedianLine");
  const drilldownSectionEl = document.getElementById("drilldownSection");
  const closeDrilldownBtn = document.getElementById("closeDrilldownBtn");

  let overlayChart = null;
  let drilldownChart = null;
  let searchTimer = null;

  // --- Global Theme Controller (Light / Dark) ---
  const themeToggleBtn = document.getElementById("themeToggleBtn");
  const getSavedTheme = () => localStorage.getItem("vbp_theme") || "light";
  const applyTheme = (theme) => {
    const isDark = theme === "dark";
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
    if (themeToggleBtn) {
      themeToggleBtn.textContent = isDark ? "☀️ Light" : "🌙 Dark";
    }
    localStorage.setItem("vbp_theme", isDark ? "dark" : "light");
  };
  applyTheme(getSavedTheme());

  window.VBPTheme = {
    isDark: () => document.documentElement.getAttribute("data-theme") === "dark",
    chartColors: () => {
      const dark = document.documentElement.getAttribute("data-theme") === "dark";
      return {
        bg: dark ? "#111827" : "#ffffff",
        text: dark ? "#cbd5e1" : "#475569",
        axis: dark ? "#334155" : "#cbd5e1",
        split: dark ? "#1f2937" : "#e2e8f0",
        tooltipBg: dark ? "rgba(15, 23, 42, 0.96)" : "rgba(255, 255, 255, 0.98)",
        tooltipBorder: dark ? "#334155" : "#cbd5e1",
        tooltipText: dark ? "#f1f5f9" : "#0f172a",
      };
    },
  };

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const next = window.VBPTheme.isDark() ? "light" : "dark";
      applyTheme(next);
      if (state.data) {
        renderOverlayChart();
        if (state.selectedEventIndex !== null && state.data.events[state.selectedEventIndex]) {
          renderDrilldown(state.data.events[state.selectedEventIndex]);
        } else if (state.data.events && state.data.events.length > 0 && !drilldownSectionEl.classList.contains("hidden")) {
          renderDrilldown(state.data.events[0]);
        }
      }
      window.dispatchEvent(new CustomEvent("vbp-theme-change", { detail: { theme: next } }));
    });
  }

  // Formatters
  const fmtPct = (v) => {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const sign = v > 0 ? "+" : "";
    return `${sign}${Number(v).toFixed(2)}%`;
  };
  const pctClass = (v) => {
    if (v === null || v === undefined) return "neu-text";
    if (v > 0) return "pos-text";
    if (v < 0) return "neg-text";
    return "neu-text";
  };
  const fmtPrice = (v) =>
    v === null || v === undefined
      ? "—"
      : `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // Single consistent date format everywhere: DD Mon YYYY (e.g. 16 Jan 2025)
  const fmtDate = (iso) => {
    if (!iso || typeof iso !== "string") return "";
    const parts = iso.split("-");
    if (parts.length !== 3) return iso;
    const m = parseInt(parts[1], 10) - 1;
    return `${parts[2]} ${MONTHS_SHORT[m] || parts[1]} ${parts[0]}`;
  };
  const fmtShortDate = fmtDate;

  const normalizeLabelDates = (text) => {
    if (!text) return "";
    return String(text)
      .replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (_, y, m, d) => `${d} ${MONTHS_SHORT[parseInt(m, 10) - 1] || m} ${y}`)
      .replace(/\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b/g, (_, d, mon, y) => `${String(d).padStart(2, "0")} ${mon} ${y}`);
  };

  const getEventBadgeMeta = (eventType) => {
    const t = (eventType || "").toUpperCase();
    if (t === "AGM") return { icon: "A", name: "AGM", color: "#9333ea", bg: "#7e22ce" };
    if (t === "CUSTOM") return { icon: "C", name: "Custom", color: "#0d9488", bg: "#0f766e" };
    return { icon: "R", name: "Result", color: "#e11d48", bg: "#be123c" };
  };

  const getBiasBadgeClasses = (bias) => {
    const b = (bias || "").toLowerCase();
    if (b.includes("bullish")) return "bg-emerald-50 text-emerald-700 border-emerald-200";
    if (b.includes("bearish")) return "bg-rose-50 text-rose-700 border-rose-200";
    if (b.includes("volatile")) return "bg-purple-50 text-purple-700 border-purple-200";
    if (b.includes("range")) return "bg-amber-50 text-amber-700 border-amber-200";
    return "bg-slate-100 text-slate-700 border-slate-300";
  };

  function showBanner(message, type = "error") {
    statusBannerEl.classList.remove(
      "hidden",
      "bg-rose-50", "border-rose-200", "text-rose-700",
      "bg-sky-50", "border-sky-200", "text-sky-700"
    );
    if (type === "error") {
      statusBannerEl.classList.add("bg-rose-50", "border-rose-200", "text-rose-700");
    } else {
      statusBannerEl.classList.add("bg-sky-50", "border-sky-200", "text-sky-700");
    }
    statusBannerEl.textContent = message;
  }

  function hideBanner() {
    statusBannerEl.classList.add("hidden");
  }

  function syncUrlParams() {
    const params = new URLSearchParams();
    params.set("symbol", state.symbol);
    params.set("event", state.eventType);
    params.set("before", state.before);
    params.set("after", state.after);
    params.set("day_mode", state.dayMode);
    params.set("normalize_to", state.normalizeTo);
    params.set("limit", state.limit);
    if (state.customDates) params.set("custom_dates", state.customDates);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }

  function loadUrlParams() {
    const p = new URLSearchParams(window.location.search);
    if (p.get("symbol")) {
      state.symbol = p.get("symbol").toUpperCase();
      stockSearchEl.value = state.symbol;
      selectedSymbolBadgeEl.textContent = state.symbol;
    }
    if (["RESULTS", "AGM", "CUSTOM"].includes((p.get("event") || "").toUpperCase())) {
      state.eventType = p.get("event").toUpperCase();
    }
    if (p.get("before")) state.before = Math.max(1, Math.min(120, parseInt(p.get("before"), 10) || 20));
    if (p.get("after")) state.after = Math.max(1, Math.min(120, parseInt(p.get("after"), 10) || 10));
    if (["trading", "calendar"].includes(p.get("day_mode"))) state.dayMode = p.get("day_mode");
    if (["start", "event"].includes(p.get("normalize_to"))) state.normalizeTo = p.get("normalize_to");
    if (p.get("limit")) state.limit = parseInt(p.get("limit"), 10) || 8;
    if (p.get("custom_dates")) state.customDates = p.get("custom_dates");

    beforeDaysEl.value = state.before;
    afterDaysEl.value = state.after;
    limitSelectEl.value = String(state.limit);
    customDatesInputEl.value = state.customDates;
    updateSegmentedControls();
  }

  function updateSegmentedControls() {
    document.querySelectorAll(".event-type-btn").forEach((btn) => {
      const isAct = btn.dataset.event === state.eventType;
      btn.classList.toggle("active", isAct);
      btn.classList.toggle("text-slate-600", !isAct);
    });
    document.querySelectorAll(".day-mode-btn").forEach((btn) => {
      const isAct = btn.dataset.daymode === state.dayMode;
      btn.classList.toggle("active", isAct);
      btn.classList.toggle("text-slate-600", !isAct);
    });
    document.querySelectorAll(".norm-btn").forEach((btn) => {
      const isAct = btn.dataset.norm === state.normalizeTo;
      btn.classList.toggle("active", isAct);
      btn.classList.toggle("text-slate-600", !isAct);
    });
    customDatesRowEl.classList.toggle("hidden", state.eventType !== "CUSTOM");
  }

  // --- Stock Autocomplete ---
  async function fetchStockSuggestions(q) {
    try {
      const resp = await fetch(`/api/stocks/search?q=${encodeURIComponent(q)}&limit=12`);
      if (!resp.ok) return;
      const payload = await resp.json();
      state.dropdownItems = payload.results || [];
      state.dropdownActiveIdx = -1;
      renderDropdown();
    } catch (e) {
      console.error("Stock search error:", e);
    }
  }

  function renderDropdown() {
    if (!state.dropdownItems.length) {
      searchDropdownEl.classList.add("hidden");
      return;
    }
    searchDropdownEl.innerHTML = state.dropdownItems
      .map(
        (item, idx) => `
        <div
          data-idx="${idx}"
          class="dropdown-item px-2.5 py-1.5 flex items-center justify-between gap-2 cursor-pointer hover:bg-slate-50 ${idx === state.dropdownActiveIdx ? "active" : ""}"
        >
          <div class="min-w-0">
            <div class="font-semibold text-xs sm:text-sm text-slate-900">${item.symbol}</div>
            <div class="text-[11px] text-slate-500 truncate">${item.name}</div>
          </div>
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 shrink-0">${item.series || "EQ"}</span>
        </div>`
      )
      .join("");
    searchDropdownEl.classList.remove("hidden");

    searchDropdownEl.querySelectorAll(".dropdown-item").forEach((el) => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        selectStock(state.dropdownItems[Number(el.dataset.idx)]);
      });
    });
  }

  function selectStock(item) {
    if (!item) return;
    state.symbol = item.symbol.toUpperCase();
    stockSearchEl.value = state.symbol;
    selectedSymbolBadgeEl.textContent = state.symbol;
    searchDropdownEl.classList.add("hidden");
    runAnalysis(false);
  }

  // --- Core API Fetch & Render ---
  async function runAnalysis(forceRefresh = false) {
    hideBanner();
    state.before = Math.max(1, Math.min(120, parseInt(beforeDaysEl.value, 10) || 20));
    state.after = Math.max(1, Math.min(120, parseInt(afterDaysEl.value, 10) || 10));
    state.limit = parseInt(limitSelectEl.value, 10) || 8;
    state.includeNifty = includeNiftyEl ? includeNiftyEl.checked : true;
    state.customDates = customDatesInputEl.value.trim();

    if (state.eventType === "CUSTOM" && !state.customDates) {
      showBanner("Please enter at least one custom date (YYYY-MM-DD) when using Custom mode.");
      return;
    }

    const typedSymbol = stockSearchEl.value.trim().toUpperCase();
    if (typedSymbol && typedSymbol !== state.symbol) {
      state.symbol = typedSymbol;
      selectedSymbolBadgeEl.textContent = state.symbol;
    }

    syncUrlParams();
    if (window.VBPYantraLoader) {
      window.VBPYantraLoader.show(
        `Analyzing ${state.symbol}`,
        "Fetching NSE corporate events & price history. For educational research only — not SEBI-registered investment advice."
      );
    } else {
      loadingStateEl.classList.remove("hidden");
    }
    resultsContainerEl.classList.add("hidden");
    drilldownSectionEl.classList.add("hidden");
    state.selectedEventIndex = null;
    analyzeBtn.disabled = true;

    try {
      const qs = new URLSearchParams({
        event_type: state.eventType,
        before: state.before,
        after: state.after,
        day_mode: state.dayMode,
        normalize_to: state.normalizeTo,
        limit: state.limit,
        include_nifty: state.includeNifty,
        refresh: forceRefresh,
      });
      if (state.customDates) qs.set("custom_dates", state.customDates);

      const peersQs = new URLSearchParams({
        event_type: state.eventType,
        before: state.before,
        after: state.after,
        limit: state.limit,
      });

      const [resp, peerResp] = await Promise.all([
        fetch(`/api/analyze/${encodeURIComponent(state.symbol)}?${qs.toString()}`),
        state.eventType !== "CUSTOM"
          ? fetch(`/api/analyze/${encodeURIComponent(state.symbol)}/peers?${peersQs.toString()}`).catch(() => null)
          : Promise.resolve(null),
      ]);
      const payload = await resp.json();

      if (!resp.ok) {
        throw new Error(payload.detail || `Server error (${resp.status})`);
      }

      let peerData = null;
      if (peerResp && peerResp.ok) {
        peerData = await peerResp.json().catch(() => null);
      }

      state.data = payload;
      renderAll(payload, peerData);
      exportCsvBtn.disabled = !payload.events || payload.events.length === 0;
    } catch (err) {
      showBanner(err.message || "Failed to analyze stock. Please try again.");
    } finally {
      if (window.VBPYantraLoader) {
        window.VBPYantraLoader.hide();
      }
      loadingStateEl.classList.add("hidden");
      analyzeBtn.disabled = false;
    }
  }

  function renderAll(payload, peerData = null) {
    const { stock, params, summary, events, recommendations, upcoming_event, range_comparison } = payload;

    document.getElementById("stockTitle").textContent = `${stock.symbol} — ${stock.name}`;
    document.getElementById("stockTickerBadge").textContent = stock.ticker;
    document.getElementById("stockSubtitle").textContent =
      `${params.event_type} · T-${params.before} to T+${params.after} (${params.day_mode}) · 0% at ${params.normalize_to === "event" ? "T0" : "Start"}`;
    document.getElementById("latestPrice").textContent = fmtPrice(stock.latest_close);
    document.getElementById("latestDate").textContent = `Close: ${fmtDate(stock.latest_date)}`;

    renderUpcomingBanner(upcoming_event, params);
    renderRecommendations(recommendations);
    renderKpis(summary, params);
    renderRangeComparison(range_comparison, params);
    resultsContainerEl.classList.remove("hidden");

    renderOverlayChart();
    renderEventsTable(events);
    renderPeerComparison(peerData);
    if (events && events.length > 0) {
      renderDrilldown(events[0]);
    } else {
      drilldownSectionEl.classList.add("hidden");
    }
  }

  function renderPeerComparison(peerData) {
    const sec = document.getElementById("peerComparisonSection");
    const body = document.getElementById("peerComparisonBody");
    const title = document.getElementById("peerComparisonTitle");
    if (!sec || !body) return;

    const peers = (peerData && peerData.peers) || [];
    if (!peers.length) {
      sec.classList.add("hidden");
      return;
    }

    title.textContent = `${peerData.sector || "Sector"} — Auto Peer Comparison (Top ${peers.length})`;
    body.innerHTML = peers
      .map(
        (p) => `
      <tr data-peer="${p.symbol}" class="peer-jump-row cursor-pointer hover:bg-sky-50/70 transition">
        <td class="py-1.5 px-2 font-bold text-sky-700">${p.symbol}</td>
        <td class="py-1.5 px-2 text-right font-mono text-slate-600">${p.events_analyzed}</td>
        <td class="py-1.5 px-2 text-right font-mono font-semibold ${pctClass(p.avg_pre_return_pct)}">${fmtPct(p.avg_pre_return_pct)}</td>
        <td class="py-1.5 px-2 text-right font-mono ${pctClass(p.avg_event_day_return_pct)}">${fmtPct(p.avg_event_day_return_pct)}</td>
        <td class="py-1.5 px-2 text-right font-mono font-semibold ${pctClass(p.avg_post_return_pct)}">${fmtPct(p.avg_post_return_pct)}</td>
        <td class="py-1.5 px-2 text-right font-mono font-bold ${pctClass(p.avg_total_return_pct)}">${fmtPct(p.avg_total_return_pct)}</td>
        <td class="py-1.5 px-2 text-right font-mono text-slate-700">${p.total_win_rate_pct ?? "—"}%</td>
      </tr>`
      )
      .join("");

    body.querySelectorAll(".peer-jump-row").forEach((tr) => {
      tr.addEventListener("click", () => {
        const sym = tr.dataset.peer;
        if (sym) {
          state.symbol = sym;
          stockSearchEl.value = sym;
          selectedSymbolBadgeEl.textContent = sym;
          runAnalysis(false);
        }
      });
    });

    sec.classList.remove("hidden");
  }

  function renderRangeComparison(rows, params) {
    if (!rows || !rows.length) {
      rangeComparisonBoxEl.classList.add("hidden");
      return;
    }
    rangeComparisonBoxEl.classList.remove("hidden");
    rangeComparisonBodyEl.innerHTML = rows
      .map((r) => {
        const isCurrent = r.before === params.before && r.after === params.after;
        const bestTag = r.is_best
          ? `<span class="ml-1 text-[9px] font-bold px-1 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-300">★ Best</span>`
          : "";
        return `
        <tr data-before="${r.before}" data-after="${r.after}" class="range-row cursor-pointer hover:bg-sky-50/70 transition ${isCurrent ? "bg-sky-50 font-semibold" : ""}">
          <td class="py-1.5 px-2 font-mono text-slate-900 whitespace-nowrap">T-${r.before}/T+${r.after}${bestTag}</td>
          <td class="py-1.5 px-1.5 text-slate-600 whitespace-nowrap">${r.style}</td>
          <td class="py-1.5 px-1.5 text-right font-mono ${pctClass(r.avg_pre_return_pct)}">${fmtPct(r.avg_pre_return_pct)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono ${pctClass(r.avg_post_return_pct)}">${fmtPct(r.avg_post_return_pct)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono font-bold ${pctClass(r.avg_total_return_pct)}">${fmtPct(r.avg_total_return_pct)}</td>
          <td class="py-1.5 px-2 text-right font-mono text-slate-700">${r.total_win_rate_pct ?? "—"}%</td>
        </tr>`;
      })
      .join("");

    rangeComparisonBodyEl.querySelectorAll(".range-row").forEach((tr) => {
      tr.addEventListener("click", () => {
        beforeDaysEl.value = tr.dataset.before;
        afterDaysEl.value = tr.dataset.after;
        runAnalysis(false);
      });
    });
  }

  function renderUpcomingBanner(upcoming, params) {
    const badge = getEventBadgeMeta(params.event_type);
    upcomingBannerEl.classList.remove(
      "hidden",
      "bg-emerald-50", "border-emerald-200", "text-emerald-900",
      "bg-slate-50", "border-slate-200", "text-slate-600"
    );

    if (upcoming) {
      upcomingBannerEl.classList.add("bg-emerald-50", "border-emerald-200", "text-emerald-900");
      const liveMoveHtml = upcoming.in_pre_window && upcoming.current_pre_return_pct !== null
        ? `<span class="font-mono font-bold px-1.5 py-0.5 rounded bg-white border border-emerald-300 ${pctClass(upcoming.current_pre_return_pct)}">Live Pre-Move: ${fmtPct(upcoming.current_pre_return_pct)}</span>`
        : `<span class="text-[11px] text-emerald-700">Pre-window starts at T-${params.before}</span>`;

      upcomingBannerEl.innerHTML = `
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="inline-flex items-center justify-center w-5 h-5 rounded-full text-white font-bold text-[10px]" style="background:${badge.color}">${badge.icon}</span>
          <span class="font-bold">Upcoming ${badge.name}: ${fmtDate(upcoming.event_date)}</span>
          <span class="text-[11px] text-emerald-800">(in ${upcoming.trading_days_until} trading / ${upcoming.calendar_days_until} calendar days · ${upcoming.source})</span>
        </div>
        <div>${liveMoveHtml}</div>`;
    } else {
      upcomingBannerEl.classList.add("bg-slate-50", "border-slate-200", "text-slate-600");
      upcomingBannerEl.innerHTML = `
        <div class="flex items-center gap-1.5">
          <span class="inline-flex items-center justify-center w-4 h-4 rounded-full text-white font-bold text-[9px]" style="background:${badge.color}">${badge.icon}</span>
          <span>No upcoming NSE ${badge.name} date announced yet for <strong>${state.symbol}</strong>. Use <strong>Custom</strong> mode to simulate a future date.</span>
        </div>`;
    }
  }

  function renderRecommendations(recs) {
    if (!recs || !recs.regular || !recs.fo) {
      recommendationsSectionEl.classList.add("hidden");
      return;
    }
    const confColors = {
      High: "bg-emerald-50 text-emerald-700 border-emerald-200",
      Medium: "bg-amber-50 text-amber-700 border-amber-200",
      Low: "bg-slate-100 text-slate-600 border-slate-300",
    };
    const confCls = confColors[recs.confidence] || confColors.Low;

    const buildCard = (item, tagLabel, accentBorder, tagColors, extraMetricHtml = "") => `
      <div class="card-box rounded-md p-2 flex flex-col justify-between gap-1.5 border-l-4 ${accentBorder}">
        <div class="flex flex-wrap items-center justify-between gap-1">
          <div class="flex items-center gap-1.5">
            <span class="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${tagColors}">${tagLabel}</span>
            <span class="text-xs font-bold text-slate-900">${item.title}</span>
          </div>
          <div class="flex items-center gap-1">
            <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded border ${getBiasBadgeClasses(item.bias)}">${item.bias}</span>
            <span class="text-[10px] font-medium px-1.5 py-0.5 rounded border ${confCls}">${recs.confidence} (${recs.sample_size})</span>
          </div>
        </div>
        <div class="text-sm font-bold text-slate-900 tracking-tight">${item.signal}</div>
        <div class="grid grid-cols-3 gap-1 bg-slate-50 border border-slate-200/80 rounded p-1.5 text-[11px]">
          <div>
            <div class="text-slate-500 text-[10px]">Entry</div>
            <div class="font-semibold text-slate-800 truncate" title="${item.entry}">${item.entry}</div>
          </div>
          <div>
            <div class="text-slate-500 text-[10px]">Exit</div>
            <div class="font-semibold text-slate-800 truncate" title="${item.exit}">${item.exit}</div>
          </div>
          <div>
            <div class="text-slate-500 text-[10px]">Hist. SL</div>
            <div class="font-semibold text-rose-600">${item.stop_loss_pct}%</div>
          </div>
        </div>
        ${extraMetricHtml}
        <p class="text-[11px] text-slate-600 leading-snug">${item.reason}</p>
      </div>`;

    const foExtra =
      recs.fo.avg_t0_abs_move_pct !== undefined
        ? `<div class="text-[10px] text-slate-500">Avg |T0| Event-Day Swing: <strong class="text-slate-800">${recs.fo.avg_t0_abs_move_pct}%</strong></div>`
        : "";

    recommendationsGridEl.innerHTML =
      buildCard(recs.regular, "REGULAR", "border-l-sky-600", "bg-sky-50 text-sky-700 border-sky-200") +
      buildCard(recs.fo, "F&O", "border-l-violet-600", "bg-violet-50 text-violet-700 border-violet-200", foExtra);
    recommendationsDisclaimerEl.textContent = recs.disclaimer || "";
    recommendationsSectionEl.classList.remove("hidden");
  }

  function renderKpis(s, params) {
    if (!s || !s.events_analyzed) {
      kpiGridEl.innerHTML = "";
      return;
    }

    const cards = [
      {
        label: `Pre (T-${params.before}→T0)`,
        val: fmtPct(s.avg_pre_return_pct),
        cls: pctClass(s.avg_pre_return_pct),
        sub: `Win: ${s.pre_win_rate_pct ?? "—"}% · Med: ${fmtPct(s.median_pre_return_pct)}`,
      },
      {
        label: "Event Day (T0)",
        val: fmtPct(s.avg_event_day_return_pct),
        cls: pctClass(s.avg_event_day_return_pct),
        sub: `${s.events_analyzed} events analyzed`,
      },
      {
        label: `Post (T0→T+${params.after})`,
        val: fmtPct(s.avg_post_return_pct),
        cls: pctClass(s.avg_post_return_pct),
        sub: `Win: ${s.post_win_rate_pct ?? "—"}% · Med: ${fmtPct(s.median_post_return_pct)}`,
      },
      {
        label: `Total (T-${params.before}→T+${params.after})`,
        val: fmtPct(s.avg_total_return_pct),
        cls: pctClass(s.avg_total_return_pct),
        sub: `Win rate: ${s.total_win_rate_pct ?? "—"}%`,
      },
      {
        label: "Nifty 50 Alpha",
        val: fmtPct(s.avg_total_alpha_pct),
        cls: pctClass(s.avg_total_alpha_pct),
        sub: "Excess vs ^NSEI",
      },
      {
        label: "Volume Surge",
        val: s.avg_volume_surge_ratio ? `${s.avg_volume_surge_ratio.toFixed(2)}x` : "—",
        cls: s.avg_volume_surge_ratio >= 1.3 ? "text-amber-600" : "text-slate-800",
        sub: s.best_event ? `Best: ${fmtPct(s.best_event.total_return_pct)}` : "Around T0 vs 20d avg",
      },
    ];

    kpiGridEl.innerHTML = cards
      .map(
        (c) => `
      <div class="card-box rounded-md p-2 flex flex-col justify-between">
        <div class="text-[10px] font-semibold uppercase tracking-wide text-slate-500 truncate">${c.label}</div>
        <div class="text-base sm:text-lg font-bold mt-0.5 ${c.cls}">${c.val}</div>
        <div class="text-[10px] text-slate-500 truncate" title="${c.sub}">${c.sub}</div>
      </div>`
      )
      .join("");
  }

  function renderOverlayChart() {
    if (!state.data) return;
    const { events, average_trace, params } = state.data;
    const container = document.getElementById("overlayChart");

    if (!overlayChart) {
      overlayChart = echarts.init(container);
      window.addEventListener("resize", () => overlayChart && overlayChart.resize());
    }

    const badge = getEventBadgeMeta(params.event_type);
    const offsets = average_trace.map((pt) => pt.offset);
    const offsetToIdx = new Map(offsets.map((o, i) => [o, i]));
    const t0Idx = offsetToIdx.get(0);

    // Reference event for x-axis date labels & ₹ Price line (selected event, or latest event)
    const refEvent =
      state.selectedEventIndex !== null && events[state.selectedEventIndex]
        ? events[state.selectedEventIndex]
        : events[0] || null;
    const refDateByOffset = new Map();
    const refPriceArr = new Array(offsets.length).fill(null);
    if (refEvent) {
      refEvent.trace.forEach((pt) => {
        refDateByOffset.set(pt.offset, pt.date);
        const i = offsetToIdx.get(pt.offset);
        if (i !== undefined) refPriceArr[i] = pt.close;
      });
    }

    const xLabels = offsets.map((o) => {
      const tLbl = o === 0 ? "T0" : o > 0 ? `T+${o}` : `T${o}`;
      const d = refDateByOffset.get(o);
      return d ? `${tLbl}\n${fmtShortDate(d)}` : tLbl;
    });
    const t0XLabel = t0Idx !== undefined ? xLabels[t0Idx] : "T0";

    const chartSubEl = document.getElementById("chartSubtitle");
    if (chartSubEl) {
      const refDesc = refEvent ? ` · ₹ Price & dates: ${fmtShortDate(refEvent.t0_date)}` : "";
      chartSubEl.textContent = `Aligned at [${badge.icon}] ${badge.name} Day (T0)${refDesc}`;
    }

    // Lookup map for tooltip: seriesName -> Map(offset -> {date, close})
    const seriesPointLookup = new Map();
    const series = [];

    // Individual event lines (% return)
    if (showIndividualLinesEl.checked) {
      const palette = [
        "#3b82f6", "#8b5cf6", "#ec4899", "#f97316", "#10b981",
        "#06b6d4", "#eab308", "#a855f7", "#0284c7", "#f43f5e",
      ];
      events.forEach((ev, idx) => {
        const isSelected = state.selectedEventIndex === idx;
        const arr = new Array(offsets.length).fill(null);
        const ptMap = new Map();
        ev.trace.forEach((pt) => {
          const i = offsetToIdx.get(pt.offset);
          if (i !== undefined) {
            arr[i] = pt.pct_change;
            ptMap.set(pt.offset, { date: pt.date, close: pt.close });
          }
        });
        const seriesName = fmtDate(ev.t0_date);
        seriesPointLookup.set(seriesName, ptMap);

        const sObj = {
          name: seriesName,
          type: "line",
          yAxisIndex: 0,
          data: arr,
          connectNulls: true,
          showSymbol: isSelected,
          symbolSize: isSelected ? 5 : 3,
          lineStyle: {
            width: isSelected ? 2.8 : 1.2,
            opacity: state.selectedEventIndex === null ? 0.35 : isSelected ? 1 : 0.14,
            color: isSelected ? "#d97706" : palette[idx % palette.length],
          },
          itemStyle: {
            color: isSelected ? "#d97706" : palette[idx % palette.length],
          },
          z: isSelected ? 8 : 2,
        };

        if (isSelected && t0Idx !== undefined && arr[t0Idx] !== null) {
          sObj.markPoint = {
            symbol: "pin",
            symbolSize: 38,
            itemStyle: { color: badge.color, borderColor: "#ffffff", borderWidth: 1.5 },
            label: { show: true, formatter: badge.icon, color: "#ffffff", fontWeight: "bold", fontSize: 12 },
            data: [{ name: `${badge.name} (${ev.t0_date})`, coord: [t0Idx, arr[t0Idx]] }],
          };
        }

        series.push(sObj);
      });
    }

    // Average line (bold primary)
    const avgData = average_trace.map((pt) => pt.avg_pct_change);
    const avgT0Val = t0Idx !== undefined ? avgData[t0Idx] : null;
    const t0LineLabel = refEvent
      ? `[${badge.icon}] ${badge.name} · ${fmtShortDate(refEvent.t0_date)}`
      : `[${badge.icon}] ${badge.name} (T0)`;

    series.push({
      name: "Average %",
      type: "line",
      yAxisIndex: 0,
      data: avgData,
      connectNulls: true,
      showSymbol: false,
      lineStyle: { width: 3, color: "#0284c7" },
      itemStyle: { color: "#0284c7" },
      markPoint:
        t0Idx !== undefined && avgT0Val !== null
          ? {
              symbol: "pin",
              symbolSize: 40,
              itemStyle: { color: badge.color, borderColor: "#ffffff", borderWidth: 1.5 },
              label: { show: true, formatter: badge.icon, color: "#ffffff", fontWeight: "bold", fontSize: 12 },
              data: [{ name: `${badge.name} Day (T0)`, coord: [t0Idx, avgT0Val] }],
            }
          : undefined,
      markLine: {
        silent: true,
        symbol: "none",
        data: [
          {
            xAxis: t0XLabel,
            lineStyle: { color: badge.color, type: "dashed", width: 1.5 },
            label: {
              formatter: t0LineLabel,
              color: "#ffffff",
              backgroundColor: badge.bg,
              padding: [2, 6],
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 600,
              position: "insideEndTop",
            },
          },
          {
            yAxis: 0,
            lineStyle: { color: "#94a3b8", type: "dotted", width: 1 },
            label: { show: false },
          },
        ],
      },
      z: 10,
    });

    // ₹ Price Line (Right Y-Axis) for reference event
    const showPriceAxis = showPriceLineEl.checked && refEvent && refPriceArr.some((v) => v !== null);
    if (showPriceAxis) {
      series.push({
        name: `Price ₹ (${fmtShortDate(refEvent.t0_date)})`,
        type: "line",
        yAxisIndex: 1,
        data: refPriceArr,
        connectNulls: true,
        showSymbol: false,
        lineStyle: { width: 2.2, color: "#059669" },
        itemStyle: { color: "#059669" },
        z: 9,
      });
    }

    // Optional Median line
    if (showMedianLineEl.checked) {
      series.push({
        name: "Median %",
        type: "line",
        yAxisIndex: 0,
        data: average_trace.map((pt) => pt.median_pct_change),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { width: 2, type: "dashed", color: "#d97706" },
        itemStyle: { color: "#d97706" },
        z: 8,
      });
    }

    // Optional Live Upcoming Event pre-window trace
    const upcoming = state.data.upcoming_event;
    if (upcoming && upcoming.in_pre_window && upcoming.trace && upcoming.trace.length) {
      const liveArr = new Array(offsets.length).fill(null);
      const livePtMap = new Map();
      upcoming.trace.forEach((pt) => {
        const i = offsetToIdx.get(pt.offset);
        if (i !== undefined) {
          liveArr[i] = pt.pct_change;
          livePtMap.set(pt.offset, { date: pt.date, close: pt.close });
        }
      });
      const liveSeriesName = `Live Upcoming (${fmtDate(upcoming.event_date)})`;
      seriesPointLookup.set(liveSeriesName, livePtMap);
      series.push({
        name: liveSeriesName,
        type: "line",
        yAxisIndex: 0,
        data: liveArr,
        connectNulls: true,
        showSymbol: true,
        symbolSize: 5,
        lineStyle: { width: 2.8, type: "dashed", color: "#e11d48" },
        itemStyle: { color: "#e11d48" },
        z: 11,
      });
    }

    // Optional Nifty 50 benchmark average
    if (params.include_nifty && average_trace.some((pt) => pt.avg_benchmark_pct_change !== null)) {
      series.push({
        name: "Nifty 50 %",
        type: "line",
        yAxisIndex: 0,
        data: average_trace.map((pt) => pt.avg_benchmark_pct_change),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { width: 1.8, type: "dashed", color: "#64748b" },
        itemStyle: { color: "#64748b" },
        z: 7,
      });
    }

    const tc = window.VBPTheme.chartColors();
    overlayChart.setOption(
      {
        backgroundColor: tc.bg,
        tooltip: {
          trigger: "axis",
          backgroundColor: tc.tooltipBg,
          borderColor: tc.tooltipBorder,
          textStyle: { color: tc.tooltipText, fontSize: 11 },
          formatter: (items) => {
            if (!items || !items.length) return "";
            const idx = items[0].dataIndex;
            const offset = offsets[idx];
            const tLabel = offset === 0 ? "T0" : offset > 0 ? `T+${offset}` : `T${offset}`;
            const badgeHtml =
              offset === 0
                ? `<span style="display:inline-block;margin-left:5px;padding:1px 6px;border-radius:999px;background:${badge.color};color:#fff;font-weight:700;font-size:10px;">${badge.icon} · ${badge.name}</span>`
                : "";
            const lines = [
              `<div style="font-weight:700;margin-bottom:4px;border-bottom:1px solid #e2e8f0;padding-bottom:3px;">${tLabel}${badgeHtml}</div>`,
            ];

            items.forEach((it) => {
              if (it.value === null || it.value === undefined) return;
              const isPriceSeries = it.seriesName.startsWith("Price ₹");
              if (isPriceSeries) {
                lines.push(
                  `<div style="display:flex;justify-content:space-between;gap:12px;line-height:1.5;">
                    <span>${it.marker}${it.seriesName}</span>
                    <span style="font-family:monospace;font-weight:700;color:#059669;">${fmtPrice(it.value)}</span>
                  </div>`
                );
                return;
              }
              const valStr = `${it.value > 0 ? "+" : ""}${Number(it.value).toFixed(2)}%`;
              const valColor = it.value > 0 ? "#059669" : it.value < 0 ? "#e11d48" : "#475569";
              const ptMap = seriesPointLookup.get(it.seriesName);
              const ptInfo = ptMap ? ptMap.get(offset) : null;
              const extraTag = ptInfo
                ? ` <span style="color:#64748b;font-size:10px;">(${fmtShortDate(ptInfo.date)} · ${fmtPrice(ptInfo.close)})</span>`
                : "";
              lines.push(
                `<div style="display:flex;justify-content:space-between;gap:12px;line-height:1.5;">
                  <span>${it.marker}${it.seriesName}${extraTag}</span>
                  <span style="font-family:monospace;font-weight:600;color:${valColor};">${valStr}</span>
                </div>`
              );
            });
            return lines.join("");
          },
        },
        legend: {
          top: 0,
          type: "scroll",
          textStyle: { color: tc.text, fontSize: 10 },
          pageTextStyle: { color: tc.text },
        },
        grid: { left: 42, right: showPriceAxis ? 54 : 10, top: 36, bottom: 38 },
        xAxis: {
          type: "category",
          data: xLabels,
          axisLine: { lineStyle: { color: tc.axis } },
          axisLabel: { color: tc.text, fontSize: 10, lineHeight: 13 },
        },
        yAxis: [
          {
            type: "value",
            axisLabel: { color: tc.text, fontSize: 10, formatter: "{value}%" },
            splitLine: { lineStyle: { color: tc.split } },
          },
          {
            type: "value",
            show: showPriceAxis,
            scale: true,
            axisLabel: { color: "#059669", fontSize: 10, formatter: "₹{value}" },
            splitLine: { show: false },
          },
        ],
        series,
      },
      true
    );
  }

  function renderEventsTable(events) {
    eventCountBadgeEl.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
    if (!events.length) {
      eventsTableBodyEl.innerHTML = `<tr><td colspan="12" class="py-5 text-center text-slate-500">No events found within available price history.</td></tr>`;
      return;
    }

    eventsTableBodyEl.innerHTML = events
      .map((ev, idx) => {
        const ongoingPill = ev.is_ongoing
          ? `<span class="ml-1 text-[9px] px-1 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300">Live</span>`
          : "";
        const cleanLabel = normalizeLabelDates(ev.label);
        return `
        <tr data-idx="${idx}" class="event-row ${state.selectedEventIndex === idx ? "selected" : ""}">
          <td class="py-1.5 px-2 font-mono font-semibold text-slate-900 whitespace-nowrap">${fmtDate(ev.t0_date)}${ongoingPill}</td>
          <td class="py-1.5 px-1.5">
            <div class="text-slate-800 max-w-[160px] truncate" title="${cleanLabel}">${cleanLabel}</div>
            <div class="text-[10px] text-slate-400">${ev.source}</div>
          </td>
          <td class="py-1.5 px-1.5 text-right font-mono text-slate-600">${fmtPrice(ev.start_price)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono text-slate-900 font-semibold">${fmtPrice(ev.t0_price)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono text-slate-600">${fmtPrice(ev.end_price)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono font-semibold ${pctClass(ev.pre_return_pct)}">${fmtPct(ev.pre_return_pct)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono ${pctClass(ev.event_day_return_pct)}">${fmtPct(ev.event_day_return_pct)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono font-semibold ${pctClass(ev.post_return_pct)}">${fmtPct(ev.post_return_pct)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono font-bold ${pctClass(ev.total_return_pct)}">${fmtPct(ev.total_return_pct)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono ${pctClass(ev.total_alpha_pct)}">${fmtPct(ev.total_alpha_pct)}</td>
          <td class="py-1.5 px-1.5 text-right font-mono text-[10px] whitespace-nowrap">
            <span class="pos-text">${fmtPct(ev.max_gain_pct)}</span>/<span class="neg-text">${fmtPct(ev.max_drawdown_pct)}</span>
          </td>
          <td class="py-1.5 px-2 text-right font-mono text-slate-700">${ev.volume_surge_ratio ? ev.volume_surge_ratio.toFixed(2) + "x" : "—"}</td>
        </tr>`;
      })
      .join("");

    eventsTableBodyEl.querySelectorAll(".event-row").forEach((row) => {
      row.addEventListener("click", () => {
        const idx = Number(row.dataset.idx);
        if (state.selectedEventIndex === idx) {
          state.selectedEventIndex = null;
          drilldownSectionEl.classList.add("hidden");
        } else {
          state.selectedEventIndex = idx;
          renderDrilldown(events[idx]);
        }
        renderOverlayChart();
        renderEventsTable(events);
      });
    });
  }

  function renderDrilldown(ev) {
    const badge = getEventBadgeMeta(state.data?.params?.event_type || state.eventType);
    drilldownSectionEl.classList.remove("hidden");
    document.getElementById("drilldownTitle").textContent = `[${badge.icon}] ${state.symbol} — ${normalizeLabelDates(ev.label)} (${fmtDate(ev.t0_date)})`;
    document.getElementById("drilldownSubtitle").textContent =
      `Start: ${fmtPrice(ev.start_price)} · T0: ${fmtPrice(ev.t0_price)} · End: ${fmtPrice(ev.end_price)} · Pre: ${fmtPct(ev.pre_return_pct)} · Post: ${fmtPct(ev.post_return_pct)}`;

    const container = document.getElementById("drilldownChart");
    if (!drilldownChart) {
      drilldownChart = echarts.init(container);
      window.addEventListener("resize", () => drilldownChart && drilldownChart.resize());
    }

    const dates = ev.trace.map((p) => p.date);
    const shortDates = dates.map(fmtShortDate);
    const closes = ev.trace.map((p) => p.close);
    const volumes = ev.trace.map((p) => p.volume);
    const t0Idx = dates.indexOf(ev.t0_date);
    const t0Close = t0Idx >= 0 ? closes[t0Idx] : null;
    const t0ShortDate = fmtShortDate(ev.t0_date);

    const tc = window.VBPTheme.chartColors();
    drilldownChart.setOption(
      {
        backgroundColor: tc.bg,
        tooltip: {
          trigger: "axis",
          backgroundColor: tc.tooltipBg,
          borderColor: tc.tooltipBorder,
          textStyle: { color: tc.tooltipText, fontSize: 11 },
          formatter: (items) => {
            if (!items || !items.length) return "";
            const i = items[0].dataIndex;
            const pt = ev.trace[i];
            const isT0 = pt.date === ev.t0_date;
            const badgeHtml = isT0
              ? `<span style="display:inline-block;margin-left:5px;padding:1px 6px;border-radius:999px;background:${badge.color};color:#fff;font-weight:700;font-size:10px;">${badge.icon} · ${badge.name}</span>`
              : "";
            const offLabel = pt.offset === 0 ? "T0" : pt.offset > 0 ? `T+${pt.offset}` : `T${pt.offset}`;
            return `
              <div style="font-weight:700;margin-bottom:4px;border-bottom:1px solid #e2e8f0;padding-bottom:3px;">
                ${fmtShortDate(pt.date)} <span style="color:#64748b;">(${offLabel})</span>${badgeHtml}
              </div>
              <div>Close: <strong style="color:#059669;">${fmtPrice(pt.close)}</strong> (${fmtPct(pt.pct_change)})</div>
              <div>Volume: <span style="color:#0284c7;">${Number(pt.volume || 0).toLocaleString("en-IN")}</span></div>
            `;
          },
        },
        grid: { left: 52, right: 10, top: 30, bottom: 24 },
        xAxis: {
          type: "category",
          data: shortDates,
          axisLine: { lineStyle: { color: tc.axis } },
          axisLabel: { color: tc.text, fontSize: 10 },
        },
        yAxis: [
          {
            type: "value",
            scale: true,
            axisLabel: { color: tc.text, fontSize: 10, formatter: "₹{value}" },
            splitLine: { lineStyle: { color: tc.split } },
          },
          {
            type: "value",
            show: false,
            max: (v) => v.max * 4,
          },
        ],
        series: [
          {
            name: "Volume",
            type: "bar",
            yAxisIndex: 1,
            data: volumes,
            itemStyle: { color: "rgba(2, 132, 199, 0.16)" },
          },
          {
            name: "Close (₹)",
            type: "line",
            yAxisIndex: 0,
            data: closes,
            smooth: false,
            symbolSize: 5,
            lineStyle: { color: "#059669", width: 2.5 },
            itemStyle: { color: "#059669" },
            markPoint:
              t0Idx >= 0 && t0Close !== null
                ? {
                    symbol: "pin",
                    symbolSize: 40,
                    itemStyle: { color: badge.color, borderColor: "#ffffff", borderWidth: 1.5 },
                    label: { show: true, formatter: badge.icon, color: "#ffffff", fontWeight: "bold", fontSize: 12 },
                    data: [{ name: `${badge.name} (${t0ShortDate})`, coord: [t0Idx, t0Close] }],
                  }
                : undefined,
            markLine: {
              silent: true,
              symbol: "none",
              data: [
                {
                  xAxis: t0ShortDate,
                  lineStyle: { color: badge.color, type: "dashed", width: 1.5 },
                  label: {
                    formatter: `[${badge.icon}] ${t0ShortDate}`,
                    color: "#ffffff",
                    backgroundColor: badge.bg,
                    padding: [2, 6],
                    borderRadius: 4,
                    fontSize: 10,
                    fontWeight: 600,
                    position: "insideEndTop",
                  },
                },
              ],
            },
          },
        ],
      },
      true
    );
    drilldownChart.resize();
  }

  function exportCsv() {
    if (!state.data || !state.data.events.length) return;
    const headers = [
      "T0 Date", "Event Date", "Label", "Source",
      "Start Price", "T0 Price", "End Price",
      "Pre Return %", "Event Day Return %", "Post Return %", "Total Return %",
      "Nifty Alpha %", "Max Gain %", "Max Drawdown %", "Volume Surge Ratio",
    ];
    const rows = state.data.events.map((e) => [
      fmtDate(e.t0_date), fmtDate(e.event_date), `"${normalizeLabelDates(e.label || "").replace(/"/g, '""')}"`, e.source,
      e.start_price, e.t0_price, e.end_price,
      e.pre_return_pct, e.event_day_return_pct, e.post_return_pct, e.total_return_pct,
      e.total_alpha_pct ?? "", e.max_gain_pct, e.max_drawdown_pct, e.volume_surge_ratio ?? "",
    ]);
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.symbol}_${state.eventType}_T-${state.before}_T+${state.after}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // --- Event Listeners ---
  stockSearchEl.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => fetchStockSuggestions(stockSearchEl.value), 160);
  });

  stockSearchEl.addEventListener("focus", () => {
    fetchStockSuggestions(stockSearchEl.value);
  });

  stockSearchEl.addEventListener("blur", () => {
    setTimeout(() => searchDropdownEl.classList.add("hidden"), 150);
  });

  stockSearchEl.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      state.dropdownActiveIdx = Math.min(state.dropdownItems.length - 1, state.dropdownActiveIdx + 1);
      renderDropdown();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      state.dropdownActiveIdx = Math.max(0, state.dropdownActiveIdx - 1);
      renderDropdown();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (state.dropdownActiveIdx >= 0 && state.dropdownItems[state.dropdownActiveIdx]) {
        selectStock(state.dropdownItems[state.dropdownActiveIdx]);
      } else {
        searchDropdownEl.classList.add("hidden");
        runAnalysis(false);
      }
    } else if (e.key === "Escape") {
      searchDropdownEl.classList.add("hidden");
    }
  });

  document.querySelectorAll(".event-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.eventType = btn.dataset.event;
      updateSegmentedControls();
      if (state.eventType !== "CUSTOM") runAnalysis(false);
    });
  });

  document.querySelectorAll(".day-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.dayMode = btn.dataset.daymode;
      updateSegmentedControls();
      runAnalysis(false);
    });
  });

  document.querySelectorAll(".norm-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.normalizeTo = btn.dataset.norm;
      updateSegmentedControls();
      runAnalysis(false);
    });
  });

  document.querySelectorAll(".preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const [b, a] = btn.dataset.preset.split(",").map(Number);
      beforeDaysEl.value = b;
      afterDaysEl.value = a;
      runAnalysis(false);
    });
  });

  limitSelectEl.addEventListener("change", () => runAnalysis(false));
  if (includeNiftyEl) includeNiftyEl.addEventListener("change", () => runAnalysis(false));
  analyzeBtn.addEventListener("click", () => runAnalysis(false));
  refreshBtn.addEventListener("click", () => runAnalysis(true));
  exportCsvBtn.addEventListener("click", exportCsv);
  showPriceLineEl.addEventListener("change", renderOverlayChart);
  showIndividualLinesEl.addEventListener("change", renderOverlayChart);
  showMedianLineEl.addEventListener("change", renderOverlayChart);
  closeDrilldownBtn.addEventListener("click", () => {
    state.selectedEventIndex = null;
    drilldownSectionEl.classList.add("hidden");
    renderOverlayChart();
    if (state.data) renderEventsTable(state.data.events);
  });

  // Boot
  loadUrlParams();
  runAnalysis(false);
})();
