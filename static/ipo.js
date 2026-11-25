(() => {
  const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmtDate = (iso) => {
    if (!iso || typeof iso !== "string") return "—";
    const parts = iso.split("-");
    if (parts.length !== 3) return iso;
    const m = parseInt(parts[1], 10) - 1;
    return `${parts[2]} ${MONTHS_SHORT[m] || parts[1]} ${parts[0]}`;
  };
  const fmtMoney = (v) =>
    v === null || v === undefined || Number.isNaN(v)
      ? "—"
      : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

  const ipoState = {
    allIpos: [],
    segment: "ALL",
    exchange: "ALL",
    status: "ALL",
    mode: "auto",
    fundSource: "",
    sebiUrl: null,
    loadedListOnce: false,
    loadedReportOnce: false,
  };

  const ipoLoadingStateEl = document.getElementById("ipoLoadingState");
  const ipoLoadingTitleEl = document.getElementById("ipoLoadingTitle");
  const ipoWorkspaceEl = document.getElementById("ipoWorkspace");
  const ipoManualPanelEl = document.getElementById("ipoManualPanel");
  const ipoReportContainerEl = document.getElementById("ipoReportContainer");

  function setIpoMode(mode, revealWorkspace = true) {
    ipoState.mode = mode === "manual" ? "manual" : "auto";
    const isManual = ipoState.mode === "manual";
    if (revealWorkspace) ipoWorkspaceEl.classList.remove("hidden");
    ipoManualPanelEl.classList.toggle("hidden", !isManual);
    ipoReportContainerEl.classList.toggle("lg:col-span-8", isManual);
    ipoReportContainerEl.classList.toggle("lg:col-span-12", !isManual);
    if (finChart) setTimeout(() => finChart.resize(), 60);
  }

  let finChart = null;

  // --- Top-Level Tab Switcher ---
  const tabEventsEl = document.getElementById("tabEvents");
  const tabIpoEl = document.getElementById("tabIpo");
  const eventHeaderActionsEl = document.getElementById("eventHeaderActions");

  function switchTab(tabName) {
    const isIpo = tabName === "ipo";
    tabEventsEl.classList.toggle("hidden", isIpo);
    tabIpoEl.classList.toggle("hidden", !isIpo);
    if (eventHeaderActionsEl) eventHeaderActionsEl.classList.toggle("hidden", isIpo);

    document.querySelectorAll(".main-tab-btn").forEach((btn) => {
      const active = btn.dataset.tab === tabName;
      btn.classList.toggle("active", active);
      btn.classList.toggle("text-slate-600", !active);
    });

    if (isIpo) {
      if (!ipoState.loadedListOnce) {
        ipoState.loadedListOnce = true;
        loadIpoList(true);
      } else if (finChart) {
        setTimeout(() => finChart.resize(), 50);
      }
    }
  }

  document.querySelectorAll(".main-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // --- IPO Screener List ---
  const ipoListBodyEl = document.getElementById("ipoListBody");
  const ipoFilterInputEl = document.getElementById("ipoFilterInput");

  async function loadIpoList(forceRefresh = false) {
    if (window.VBPYantraLoader) {
      window.VBPYantraLoader.show(
        "Loading Indian IPOs",
        "Fetching Mainboard & SME IPOs from NSE & BSE. For educational research only — not SEBI-registered investment advice."
      );
    }
    ipoListBodyEl.innerHTML = `<tr><td colspan="9" class="py-3 text-center text-slate-500">Loading Mainboard &amp; SME IPOs from NSE &amp; BSE...</td></tr>`;
    try {
      const resp = await fetch(`/api/ipo/list?segment=ALL&status=ALL&exchange=ALL&refresh=${forceRefresh}`);
      const data = await resp.json();
      ipoState.allIpos = data.ipos || [];
      renderIpoList();
    } catch (err) {
      ipoListBodyEl.innerHTML = `<tr><td colspan="9" class="py-3 text-center text-rose-600">Could not load IPO list right now.</td></tr>`;
    } finally {
      if (window.VBPYantraLoader) {
        window.VBPYantraLoader.hide();
      }
    }
  }

  function renderIpoList() {
    const q = (ipoFilterInputEl.value || "").trim().toLowerCase();
    const filtered = ipoState.allIpos.filter((item) => {
      if (ipoState.segment !== "ALL" && item.segment !== ipoState.segment) return false;
      if (ipoState.exchange !== "ALL" && !(item.exchange || "").toUpperCase().includes(ipoState.exchange)) return false;
      if (ipoState.status !== "ALL" && item.status !== ipoState.status) return false;
      if (q && !(item.company_name.toLowerCase().includes(q) || item.symbol.toLowerCase().includes(q))) {
        return false;
      }
      return true;
    });

    if (!filtered.length) {
      ipoListBodyEl.innerHTML = `<tr><td colspan="9" class="py-3 text-center text-slate-500">No matching IPOs found in this filter.</td></tr>`;
      return;
    }

    const stColors = {
      OPEN: "bg-emerald-50 text-emerald-700 border-emerald-200",
      ALLOTMENT: "bg-amber-50 text-amber-800 border-amber-300",
      UPCOMING: "bg-sky-50 text-sky-700 border-sky-200",
      LISTED: "bg-slate-100 text-slate-600 border-slate-200",
    };

    ipoListBodyEl.innerHTML = filtered
      .map((item, idx) => {
        const segBadge =
          item.segment === "SME"
            ? `<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200">SME</span>`
            : `<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-sky-50 text-sky-700 border border-sky-200">Regular</span>`;
        const exBadge = `<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">${item.exchange || "NSE"}</span>`;
        const stBadge = `<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded border ${stColors[item.status] || stColors.LISTED}">${item.status}</span>`;
        const priceBand =
          item.price_min && item.price_max && item.price_min !== item.price_max
            ? `₹${item.price_min}–₹${item.price_max}`
            : item.price_max
              ? `₹${item.price_max}`
              : "—";
        const dateStr =
          item.open_date && item.close_date
            ? `${fmtDate(item.open_date)} – ${fmtDate(item.close_date)}`
            : item.open_date
              ? fmtDate(item.open_date)
              : "—";
        const allotListStr = item.listing_date
          ? `List: ${fmtDate(item.listing_date)}`
          : item.allotment_date
            ? `Allot: ${fmtDate(item.allotment_date)}`
            : "—";

        return `
        <tr data-symbol="${item.symbol}" data-idx="${idx}" class="ipo-pick-row hover:bg-sky-50/70 transition">
          <td class="py-1.5 px-2 font-semibold text-slate-900">${item.company_name} <span class="text-[10px] font-mono text-slate-400">(${item.symbol})</span></td>
          <td class="py-1.5 px-1.5">${segBadge}</td>
          <td class="py-1.5 px-1.5">${exBadge}</td>
          <td class="py-1.5 px-1.5">${stBadge}</td>
          <td class="py-1.5 px-1.5 text-slate-600 whitespace-nowrap">${dateStr}</td>
          <td class="py-1.5 px-1.5 text-slate-600 whitespace-nowrap">${allotListStr}</td>
          <td class="py-1.5 px-1.5 text-right font-mono text-slate-800 whitespace-nowrap">${priceBand}</td>
          <td class="py-1.5 px-1.5 text-right font-mono text-slate-700">${item.issue_size_cr ? item.issue_size_cr : "—"}</td>
          <td class="py-1 px-2 text-right whitespace-nowrap">
            <div class="inline-flex items-center gap-1">
              <button type="button" data-idx="${idx}" class="ipo-btn-analyze px-2 py-0.5 rounded text-[11px] font-semibold bg-sky-600 hover:bg-sky-700 text-white transition">Analyze</button>
              <button type="button" data-idx="${idx}" class="ipo-btn-predict px-2 py-0.5 rounded text-[11px] font-semibold bg-violet-600 hover:bg-violet-700 text-white transition">Predict</button>
            </div>
          </td>
        </tr>`;
      })
      .join("");

    ipoListBodyEl.querySelectorAll(".ipo-btn-analyze").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const item = filtered[Number(btn.dataset.idx)];
        if (item) selectIpoFromList(item, "auto");
      });
    });

    ipoListBodyEl.querySelectorAll(".ipo-btn-predict").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const item = filtered[Number(btn.dataset.idx)];
        if (item) selectIpoFromList(item, "manual");
      });
    });
  }

  async function selectIpoFromList(item, mode = "auto") {
    setIpoMode(mode, false);
    ipoWorkspaceEl.classList.add("hidden");
    if (window.VBPYantraLoader) {
      window.VBPYantraLoader.show(
        `Researching ${item.company_name || item.symbol}`,
        "Fetching live NSE/BSE details & RHP financials. For educational research only — not SEBI-registered investment advice."
      );
    } else {
      ipoLoadingTitleEl.textContent = `Researching ${item.company_name || item.symbol}...`;
      ipoLoadingStateEl.classList.remove("hidden");
    }
    const loadStartedAt = Date.now();
    ipoState.loadedReportOnce = true;
    document.getElementById("ipoCompany").value = item.company_name || item.symbol;
    document.getElementById("ipoSegment").value = item.segment || "MAINBOARD";
    document.getElementById("ipoPriceMax").value = item.price_max ?? "";
    document.getElementById("ipoLotSize").value = item.lot_size ?? "";
    document.getElementById("ipoIssueSize").value = item.issue_size_cr ?? "";
    document.getElementById("ipoFreshPct").value = item.fresh_issue_pct ?? "100";
    document.getElementById("ipoSubTotal").value = item.subscription_total ?? "";
    document.getElementById("ipoSubQib").value = "";
    document.getElementById("ipoSubNii").value = "";
    document.getElementById("ipoSubRetail").value = "";

    // Clear old RHP numbers before pulling live detail + Yahoo Finance
    ["ipoEps", "ipoRev1", "ipoRev2", "ipoRev3", "ipoPat1", "ipoPat2", "ipoPat3", "ipoNetWorth", "ipoDebt", "ipoMcap"].forEach(
      (id) => (document.getElementById(id).value = "")
    );

    ipoState.fundSource = "";
    ipoState.sebiUrl = null;
    if (item.symbol) {
      try {
        const shouldRefresh = item.status === "OPEN";
        const resp = await fetch(
          `/api/ipo/detail/${encodeURIComponent(item.symbol)}?name=${encodeURIComponent(item.company_name || "")}&ch_url=${encodeURIComponent(item.chittorgarh_url || "")}&refresh=${shouldRefresh}`
        );
        const d = await resp.json();
        if (d) {
          ipoState.sebiUrl = d.sebi_prospectus_url || null;
          if (d.price_max) document.getElementById("ipoPriceMax").value = d.price_max;
          if (d.lot_size) document.getElementById("ipoLotSize").value = d.lot_size;
          if (d.issue_size_cr) document.getElementById("ipoIssueSize").value = d.issue_size_cr;
          if (d.fresh_issue_pct !== null && d.fresh_issue_pct !== undefined) {
            document.getElementById("ipoFreshPct").value = d.fresh_issue_pct;
          }
          if (d.sub_qib !== null && d.sub_qib !== undefined) document.getElementById("ipoSubQib").value = d.sub_qib;
          if (d.sub_nii !== null && d.sub_nii !== undefined) document.getElementById("ipoSubNii").value = d.sub_nii;
          if (d.sub_retail !== null && d.sub_retail !== undefined) document.getElementById("ipoSubRetail").value = d.sub_retail;
          if (d.sub_total !== null && d.sub_total !== undefined) document.getElementById("ipoSubTotal").value = d.sub_total;

          const f = d.fundamentals;
          if (f && f.found) {
            ipoState.fundSource = f.source || "Yahoo Finance";
            if (!document.getElementById("ipoPriceMax").value && f.current_price) {
              document.getElementById("ipoPriceMax").value = f.current_price;
            }
            if (f.eps !== null && f.eps !== undefined) document.getElementById("ipoEps").value = f.eps;
            if (f.market_cap_cr) document.getElementById("ipoMcap").value = f.market_cap_cr;
            if (f.net_worth_cr) document.getElementById("ipoNetWorth").value = f.net_worth_cr;
            if (f.total_debt_cr !== null && f.total_debt_cr !== undefined) document.getElementById("ipoDebt").value = f.total_debt_cr;
            if (f.rev_fy1 !== null) document.getElementById("ipoRev1").value = f.rev_fy1;
            if (f.rev_fy2 !== null) document.getElementById("ipoRev2").value = f.rev_fy2;
            if (f.rev_fy3 !== null) document.getElementById("ipoRev3").value = f.rev_fy3;
            if (f.pat_fy1 !== null) document.getElementById("ipoPat1").value = f.pat_fy1;
            if (f.pat_fy2 !== null) document.getElementById("ipoPat2").value = f.pat_fy2;
            if (f.pat_fy3 !== null) document.getElementById("ipoPat3").value = f.pat_fy3;
          }
        }
      } catch (e) {
        console.warn("Could not auto-fill live IPO detail:", e);
      }
    }

    await runIpoAnalysis();
    const elapsed = Date.now() - loadStartedAt;
    if (elapsed < 600) {
      await new Promise((resolve) => setTimeout(resolve, 600 - elapsed));
    }
    if (window.VBPYantraLoader) {
      window.VBPYantraLoader.hide();
    }
    ipoLoadingStateEl.classList.add("hidden");
    ipoWorkspaceEl.classList.remove("hidden");
    if (finChart) setTimeout(() => finChart.resize(), 60);
  }

  // --- Run Fundamental & Valuation Report ---
  const numVal = (id) => {
    const raw = document.getElementById(id).value;
    if (raw === "" || raw === null || raw === undefined) return null;
    const n = Number(raw);
    return Number.isNaN(n) ? null : n;
  };

  async function runIpoAnalysis() {
    const btn = document.getElementById("ipoAnalyzeBtn");
    btn.disabled = true;
    btn.textContent = "Analyzing...";

    const peersRaw = document.getElementById("ipoPeers").value || "";
    const peerSymbols = peersRaw
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);

    const payload = {
      company_name: document.getElementById("ipoCompany").value.trim() || "IPO Analysis",
      segment: document.getElementById("ipoSegment").value,
      price_max: numVal("ipoPriceMax"),
      lot_size: numVal("ipoLotSize"),
      issue_size_cr: numVal("ipoIssueSize"),
      fresh_issue_pct: numVal("ipoFreshPct"),
      eps: numVal("ipoEps"),
      rev_fy1: numVal("ipoRev1"),
      rev_fy2: numVal("ipoRev2"),
      rev_fy3: numVal("ipoRev3"),
      pat_fy1: numVal("ipoPat1"),
      pat_fy2: numVal("ipoPat2"),
      pat_fy3: numVal("ipoPat3"),
      net_worth_cr: numVal("ipoNetWorth"),
      total_debt_cr: numVal("ipoDebt"),
      post_issue_mcap_cr: numVal("ipoMcap"),
      sub_qib: numVal("ipoSubQib"),
      sub_nii: numVal("ipoSubNii"),
      sub_retail: numVal("ipoSubRetail"),
      sub_total: numVal("ipoSubTotal"),
      peer_symbols: peerSymbols,
      peer_median_pe: numVal("ipoPeerPe"),
    };

    try {
      const resp = await fetch("/api/ipo/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const report = await resp.json();
      renderIpoReport(report);
    } catch (err) {
      console.error("IPO analysis error:", err);
    } finally {
      btn.disabled = false;
      btn.textContent = "Generate IPO Report";
    }
  }

  function renderIpoReport(r) {
    document.getElementById("ipoRepTitle").textContent = r.company_name;
    const segBadge = document.getElementById("ipoRepSegmentBadge");
    if (r.segment === "SME") {
      segBadge.textContent = "SME IPO";
      segBadge.className = "text-[10px] font-bold px-1.5 py-0.5 rounded border bg-purple-50 text-purple-700 border-purple-200";
    } else {
      segBadge.textContent = "Regular (Mainboard)";
      segBadge.className = "text-[10px] font-bold px-1.5 py-0.5 rounded border bg-sky-50 text-sky-700 border-sky-200";
    }

    document.getElementById("ipoRepPlainSummary").textContent = r.verdict.plain_summary;
    const scoreEl = document.getElementById("ipoOverallScore");
    scoreEl.textContent = r.scores.overall;
    scoreEl.className =
      "text-2xl font-bold leading-none " +
      (r.scores.overall >= 70 ? "text-emerald-600" : r.scores.overall >= 45 ? "text-amber-600" : "text-rose-600");

    // Data source badge & SEBI Prospectus link
    const srcBadge = document.getElementById("ipoDataSourceBadge");
    if (srcBadge) {
      srcBadge.textContent =
        ipoState.mode === "manual"
          ? "Manual / Edited RHP"
          : ipoState.fundSource
            ? `Auto: NSE + ${ipoState.fundSource}`
            : "Auto: NSE Live";
    }
    const sebiLink = document.getElementById("ipoSebiLink");
    if (sebiLink) {
      if (ipoState.sebiUrl) {
        sebiLink.href = ipoState.sebiUrl;
        sebiLink.classList.remove("hidden");
      } else {
        sebiLink.classList.add("hidden");
      }
    }

    // Listing Price Predictions: 1) Fundamentals Only, 2) Fundamentals + Demand (2 lines for Gain & 1-Lot)
    const lp = r.listing_prediction || {};
    const lpFund = lp.fundamentals_only || {};

    const fillEstimateBox = (rangeId, gainId, lotId, estObj) => {
      const rEl = document.getElementById(rangeId);
      const gEl = document.getElementById(gainId);
      const lEl = document.getElementById(lotId);
      if (lp.available && estObj && estObj.est_low !== undefined) {
        rEl.textContent = `${fmtMoney(estObj.est_low)} – ${fmtMoney(estObj.est_high)}`;
        const gL = estObj.gain_low_pct;
        const gH = estObj.gain_high_pct;
        const cls = "text-xs font-semibold " + (estObj.gain_mid_pct > 2 ? "text-emerald-600" : estObj.gain_mid_pct < -2 ? "text-rose-600" : "text-amber-600");
        gEl.textContent = `Est. Gain: ${gL > 0 ? "+" : ""}${gL}% to ${gH > 0 ? "+" : ""}${gH}%`;
        gEl.className = cls + " mt-0.5";
        if (estObj.lot_profit_mid !== null && estObj.lot_profit_mid !== undefined) {
          lEl.textContent = `Est. 1-Lot: ${estObj.lot_profit_mid >= 0 ? "+" : ""}${fmtMoney(estObj.lot_profit_mid)}`;
          lEl.className = cls;
        } else {
          lEl.textContent = "Est. 1-Lot: —";
          lEl.className = "text-xs font-semibold text-slate-500";
        }
      } else {
        rEl.textContent = "—";
        gEl.textContent = "Price band pending";
        gEl.className = "text-xs font-semibold mt-0.5 text-slate-500";
        lEl.textContent = "";
      }
    };

    fillEstimateBox("ipoFundPriceRange", "ipoFundGainLine", "ipoFundLotLine", lpFund);
    fillEstimateBox("ipoListingPriceRange", "ipoListingGainLine", "ipoListingLotLine", lp);
    document.getElementById("ipoListingPriceNote").textContent = lp.note || "";

    document.getElementById("ipoListingVerdict").textContent = r.verdict.listing;
    document.getElementById("ipoListingNote").textContent = r.verdict.listing_note;
    document.getElementById("ipoLongTermVerdict").textContent = r.verdict.long_term;
    document.getElementById("ipoLongTermNote").textContent = r.verdict.long_term_note;
    document.getElementById("ipoDisclaimer").textContent = r.disclaimer;

    // Valuation & Fundamental KPIs (Categorized)
    const v = r.valuation;
    const f = r.fundamentals;
    const valTagColor =
      v.valuation_tag === "Undervalued" || v.valuation_tag === "Reasonable"
        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
        : v.valuation_tag === "Expensive" || v.valuation_tag === "Loss-Making"
          ? "bg-rose-50 text-rose-700 border-rose-200"
          : "bg-slate-100 text-slate-700 border-slate-200";

    const valTagBadge = document.getElementById("ipoValTagBadge");
    if (valTagBadge) {
      valTagBadge.textContent = v.valuation_tag || "—";
      valTagBadge.className = `text-[10px] font-bold px-1.5 py-0.5 rounded border ${valTagColor}`;
    }

    const valTextColor =
      v.valuation_tag === "Undervalued" || v.valuation_tag === "Reasonable"
        ? "text-emerald-600"
        : v.valuation_tag === "Expensive" || v.valuation_tag === "Loss-Making"
          ? "text-rose-600"
          : "text-slate-900";

    const renderMiniCard = (k) => `
      <div class="bg-slate-50 border border-slate-200 rounded p-2">
        <div class="text-[11px] font-bold uppercase text-slate-700 truncate">${k.label}</div>
        <div class="text-sm sm:text-base font-bold mt-0.5 ${k.cls}">${k.val}</div>
        <div class="text-[11px] text-slate-600 truncate" title="${k.sub}">${k.sub}</div>
      </div>`;

    const valuationCards = [
      {
        label: "Price vs Peers (P/E)",
        val: v.ipo_pe !== null ? `${v.ipo_pe}x` : "—",
        cls: valTextColor,
        sub: v.peer_median_pe ? `Peer Avg: ${v.peer_median_pe}x` : "Offer P/E",
      },
      {
        label: "Fair Value Estimate",
        val: v.implied_fair_price ? fmtMoney(v.implied_fair_price) : "—",
        cls: v.valuation_diff_pct !== null && v.valuation_diff_pct < 0 ? "text-emerald-600" : "text-slate-900",
        sub:
          v.valuation_diff_pct !== null
            ? `${Math.abs(v.valuation_diff_pct)}% ${v.valuation_diff_pct < 0 ? "cheaper" : "costlier"} than peers`
            : "Add Peer P/E in Predict",
      },
      {
        label: "1-Lot Cost",
        val: v.min_investment ? fmtMoney(v.min_investment) : "—",
        cls: "text-slate-900",
        sub: v.lot_size ? `${v.lot_size} shares @ ₹${v.price_max}` : "Lot size pending",
      },
      {
        label: "Money Into Business",
        val: `${v.fresh_issue_pct ?? 100}% Fresh`,
        cls: (v.ofs_pct || 0) >= 60 ? "text-rose-600" : "text-emerald-600",
        sub: `Owner Exit (OFS): ${v.ofs_pct ?? 0}%`,
      },
    ];

    const fundamentalCards = [
      {
        label: "Yearly Sales Growth",
        val: f.rev_cagr_pct !== null ? `${f.rev_cagr_pct > 0 ? "+" : ""}${f.rev_cagr_pct}%` : "—",
        cls: f.rev_cagr_pct > 0 ? "text-emerald-600" : f.rev_cagr_pct < 0 ? "text-rose-600" : "text-slate-900",
        sub: "Last 2 years",
      },
      {
        label: "Yearly Profit Growth",
        val: f.pat_cagr_pct !== null ? `${f.pat_cagr_pct > 0 ? "+" : ""}${f.pat_cagr_pct}%` : "—",
        cls: f.pat_cagr_pct > 0 ? "text-emerald-600" : f.pat_cagr_pct < 0 ? "text-rose-600" : "text-slate-900",
        sub: f.margin_spike_flag ? "⚠ Sudden profit jump" : "Last 2 years",
      },
      {
        label: "Return on Money (ROE)",
        val: f.roe_pct !== null ? `${f.roe_pct}%` : "—",
        cls: f.roe_pct >= 15 ? "text-emerald-600" : "text-slate-900",
        sub: f.roe_pct >= 15 ? "Healthy profitability" : "Profit vs Net Worth",
      },
      {
        label: "Debt vs Net Worth",
        val: f.debt_to_equity !== null ? `${f.debt_to_equity}x` : "—",
        cls: f.debt_to_equity !== null && f.debt_to_equity >= 1.2 ? "text-rose-600" : "text-emerald-600",
        sub: f.debt_to_equity !== null && f.debt_to_equity <= 0.5 ? "Low debt" : "Loan burden",
      },
    ];

    document.getElementById("ipoValuationGrid").innerHTML = valuationCards.map(renderMiniCard).join("");
    document.getElementById("ipoFundamentalGrid").innerHTML = fundamentalCards.map(renderMiniCard).join("");

    // Official Subscription Boxes (QIB / NII / Retail / Total)
    const sub = r.subscription || {};
    const subItems = [
      { label: "QIB", val: sub.qib },
      { label: "NII", val: sub.nii },
      { label: "Retail", val: sub.retail },
      { label: "Total", val: sub.total },
    ];
    document.getElementById("ipoSubBars").innerHTML = subItems
      .map(
        (s) => `
      <div class="bg-slate-50 border border-slate-200 rounded p-1.5 text-center">
        <div class="text-[11px] text-slate-700 font-bold">${s.label}</div>
        <div class="text-xs font-bold font-mono ${s.val >= 10 ? "text-emerald-600" : "text-slate-900"}">${s.val !== null && s.val !== undefined ? s.val + "x" : "—"}</div>
      </div>`
      )
      .join("");

    // Strengths & Risks
    const sList = document.getElementById("ipoStrengthsList");
    sList.innerHTML = r.strengths.length
      ? r.strengths.map((t) => `<li>${t}</li>`).join("")
      : `<li class="text-slate-500">Not enough financial details yet to highlight strengths.</li>`;

    const rList = document.getElementById("ipoRisksList");
    rList.innerHTML = r.risks.length
      ? r.risks.map((t) => `<li>${t}</li>`).join("")
      : `<li class="text-emerald-700">No major risks found in the available numbers.</li>`;

    // Score Breakdown Bars
    const bars = [
      { label: "Company Health", val: r.scores.fundamental, max: r.scores.fundamental_max, color: "#0284c7" },
      { label: "Price Comfort", val: r.scores.valuation, max: r.scores.valuation_max, color: "#059669" },
      { label: "Buyers Demand", val: r.scores.demand, max: r.scores.demand_max, color: "#7c3aed" },
    ];
    document.getElementById("ipoScoreBars").innerHTML = bars
      .map((b) => {
        const pct = Math.round((b.val / b.max) * 100);
        return `
        <div>
          <div class="flex justify-between text-[11px] mb-0.5">
            <span class="text-slate-700 font-medium">${b.label}</span>
            <span class="font-mono font-bold text-slate-900">${b.val}/${b.max}</span>
          </div>
          <div class="w-full h-1.5 bg-slate-100 rounded overflow-hidden">
            <div class="h-full rounded" style="width:${pct}%;background:${b.color};"></div>
          </div>
        </div>`;
      })
      .join("");

    // Listed Peers Table
    const peersWrap = document.getElementById("ipoPeersWrap");
    const peersCard = document.getElementById("ipoPeersCard");
    if (r.peers && r.peers.length) {
      if (peersCard) peersCard.classList.remove("hidden");
      peersWrap.innerHTML = `
        <table class="w-full text-left border-collapse text-[11px] mt-1">
          <thead>
            <tr class="bg-slate-50 text-slate-500 text-[10px] uppercase border-y border-slate-200">
              <th class="py-1 px-1.5">Peer</th>
              <th class="py-1 px-1.5 text-right">Price</th>
              <th class="py-1 px-1.5 text-right">P/E</th>
              <th class="py-1 px-1.5 text-right">ROE</th>
              <th class="py-1 px-1.5 text-right">D/E</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            ${r.peers
              .map(
                (p) => `
              <tr>
                <td class="py-1 px-1.5 font-semibold text-slate-800">${p.symbol}</td>
                <td class="py-1 px-1.5 text-right font-mono">${p.price ? "₹" + p.price : "—"}</td>
                <td class="py-1 px-1.5 text-right font-mono font-semibold">${p.pe ? p.pe + "x" : "—"}</td>
                <td class="py-1 px-1.5 text-right font-mono">${p.roe_pct !== null ? p.roe_pct + "%" : "—"}</td>
                <td class="py-1 px-1.5 text-right font-mono">${p.debt_to_equity !== null ? p.debt_to_equity + "x" : "—"}</td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>`;
    } else {
      if (peersCard) peersCard.classList.toggle("hidden", ipoState.mode !== "manual");
      peersWrap.innerHTML = `<p class="text-xs text-slate-600">Enter listed company symbols (e.g. <code>TCS, INFY</code>) on the left to compare prices.</p>`;
    }

    // Company Details & Valuations Table
    const detailsWrap = document.getElementById("ipoDetailsTableWrap");
    if (detailsWrap) {
      const nwVal = numVal("ipoNetWorth");
      const debtVal = numVal("ipoDebt");
      const tableRows = [
        ["Issue Price", v.price_max ? `₹${v.price_max}` : "—", "IPO Type", r.segment === "SME" ? "SME IPO" : "Regular (Mainboard)"],
        ["Lot Size", v.lot_size ? `${v.lot_size} shares` : "—", "1-Lot Cost", v.min_investment ? fmtMoney(v.min_investment) : "—"],
        ["Issue Size", v.issue_size_cr ? `₹${Number(v.issue_size_cr).toLocaleString("en-IN")} Cr` : "—", "Fresh / Owner Exit", `${v.fresh_issue_pct ?? 100}% / ${v.ofs_pct ?? 0}%`],
        ["Post-Issue Mkt Cap", v.post_issue_mcap_cr ? `₹${Number(v.post_issue_mcap_cr).toLocaleString("en-IN")} Cr` : "—", "EPS (Post-IPO)", v.eps !== null && v.eps !== undefined ? `₹${v.eps}` : "—"],
        ["IPO P/E", v.ipo_pe !== null ? `${v.ipo_pe}x` : "—", "Peer Avg P/E", v.peer_median_pe ? `${v.peer_median_pe}x` : "—"],
        ["Price / Book (P/B)", v.ipo_pb !== null ? `${v.ipo_pb}x` : "—", "Mkt Cap / Sales", v.price_to_sales !== null ? `${v.price_to_sales}x` : "—"],
        ["Net Worth", nwVal !== null ? `₹${Number(nwVal).toLocaleString("en-IN")} Cr` : "—", "Total Debt", debtVal !== null ? `₹${Number(debtVal).toLocaleString("en-IN")} Cr` : "—"],
        ["ROE", f.roe_pct !== null ? `${f.roe_pct}%` : "—", "Debt / Equity", f.debt_to_equity !== null ? `${f.debt_to_equity}x` : "—"],
      ];
      detailsWrap.innerHTML = `
        <table class="w-full text-left border-collapse text-xs">
          <tbody class="divide-y divide-slate-100">
            ${tableRows
              .map(
                ([k1, v1, k2, v2]) => `
              <tr>
                <td class="py-1.5 px-2 text-slate-600 font-medium bg-slate-50/70 w-[24%]">${k1}</td>
                <td class="py-1.5 px-2 font-mono font-semibold text-slate-900 w-[26%]">${v1}</td>
                <td class="py-1.5 px-2 text-slate-600 font-medium bg-slate-50/70 w-[24%]">${k2}</td>
                <td class="py-1.5 px-2 font-mono font-semibold text-slate-900 w-[26%]">${v2}</td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>`;
    }

    // 3-Year Revenue & Profit/Loss Chart
    ipoState.lastYearly = f.yearly || [];
    renderFinancialChart(ipoState.lastYearly);
  }

  window.addEventListener("vbp-theme-change", () => {
    if (ipoState.lastYearly && finChart) {
      renderFinancialChart(ipoState.lastYearly);
    }
  });

  function renderFinancialChart(yearly) {
    const el = document.getElementById("ipoFinChart");
    if (!finChart) {
      finChart = echarts.init(el);
      window.addEventListener("resize", () => finChart && finChart.resize());
    }
    const tc = window.VBPTheme ? window.VBPTheme.chartColors() : {
      bg: "#ffffff", text: "#475569", axis: "#cbd5e1", split: "#e2e8f0",
      tooltipBg: "#ffffff", tooltipBorder: "#cbd5e1", tooltipText: "#0f172a",
    };
    const years = yearly.map((y) => y.year);
    const revs = yearly.map((y) => y.revenue ?? 0);
    const patBars = yearly.map((y) => {
      const val = y.pat ?? 0;
      const isLoss = val < 0;
      return {
        value: val,
        itemStyle: {
          color: isLoss ? "#e11d48" : "#059669",
          borderRadius: isLoss ? [0, 0, 3, 3] : [3, 3, 0, 0],
        },
      };
    });
    const margins = yearly.map((y) => y.margin_pct ?? null);

    finChart.setOption(
      {
        backgroundColor: tc.bg,
        tooltip: {
          trigger: "axis",
          backgroundColor: tc.tooltipBg,
          borderColor: tc.tooltipBorder,
          textStyle: { color: tc.tooltipText, fontSize: 11 },
          formatter: (items) => {
            if (!items || !items.length) return "";
            const title = items[0].axisValue;
            const lines = [`<div style="font-weight:700;margin-bottom:4px;">${title}</div>`];
            items.forEach((it) => {
              const rawVal = typeof it.value === "object" && it.value !== null ? it.value.value : it.value;
              if (rawVal === null || rawVal === undefined) return;
              if (it.seriesName.includes("Margin")) {
                lines.push(`<div>${it.marker}${it.seriesName}: <strong>${rawVal}%</strong></div>`);
              } else if (it.seriesName.includes("Profit")) {
                const lbl = rawVal < 0 ? "Loss" : "Profit";
                const clr = rawVal < 0 ? "#e11d48" : "#059669";
                lines.push(`<div>${it.marker}${lbl}: <strong style="color:${clr};">₹${rawVal} Cr</strong></div>`);
              } else {
                lines.push(`<div>${it.marker}${it.seriesName}: <strong>₹${rawVal} Cr</strong></div>`);
              }
            });
            return lines.join("");
          },
        },
        legend: {
          top: 0,
          textStyle: { color: tc.text, fontSize: 10 },
        },
        grid: { left: 48, right: 40, top: 30, bottom: 24 },
        xAxis: {
          type: "category",
          data: years,
          axisLine: { lineStyle: { color: tc.axis } },
          axisLabel: { color: tc.text, fontSize: 10 },
        },
        yAxis: [
          {
            type: "value",
            axisLabel: { color: tc.text, fontSize: 10, formatter: "₹{value}" },
            splitLine: { lineStyle: { color: tc.split } },
          },
          {
            type: "value",
            axisLabel: { color: "#d97706", fontSize: 10, formatter: "{value}%" },
            splitLine: { show: false },
          },
        ],
        series: [
          {
            name: "Sales (Cr)",
            type: "bar",
            data: revs,
            barMaxWidth: 28,
            itemStyle: { color: "#38bdf8", borderRadius: [3, 3, 0, 0] },
          },
          {
            name: "Profit / Loss (Cr)",
            type: "bar",
            data: patBars,
            barMaxWidth: 28,
            itemStyle: { color: "#059669" },
            markLine: {
              silent: true,
              symbol: "none",
              lineStyle: { color: tc.axis, type: "solid", width: 1 },
              label: { show: false },
              data: [{ yAxis: 0 }],
            },
          },
          {
            name: "PAT Margin %",
            type: "line",
            yAxisIndex: 1,
            data: margins,
            lineStyle: { color: "#d97706", width: 2 },
            itemStyle: { color: "#d97706" },
          },
        ],
      },
      true
    );
    finChart.resize();
  }

  // --- Wire Controls ---
  document.querySelectorAll(".ipo-seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      ipoState.segment = btn.dataset.iposeg;
      document.querySelectorAll(".ipo-seg-btn").forEach((b) => {
        const a = b.dataset.iposeg === ipoState.segment;
        b.classList.toggle("active", a);
        b.classList.toggle("text-slate-600", !a);
      });
      renderIpoList();
    });
  });

  document.querySelectorAll(".ipo-ex-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      ipoState.exchange = btn.dataset.ipoex;
      document.querySelectorAll(".ipo-ex-btn").forEach((b) => {
        const a = b.dataset.ipoex === ipoState.exchange;
        b.classList.toggle("active", a);
        b.classList.toggle("text-slate-600", !a);
      });
      renderIpoList();
    });
  });

  document.querySelectorAll(".ipo-st-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      ipoState.status = btn.dataset.ipost;
      document.querySelectorAll(".ipo-st-btn").forEach((b) => {
        const a = b.dataset.ipost === ipoState.status;
        b.classList.toggle("active", a);
        b.classList.toggle("text-slate-600", !a);
      });
      renderIpoList();
    });
  });

  ipoFilterInputEl.addEventListener("input", renderIpoList);
  document.getElementById("ipoAnalyzeBtn").addEventListener("click", runIpoAnalysis);

  // Auto-update report whenever user edits any field in Manual mode
  ipoManualPanelEl.querySelectorAll("input, select").forEach((el) => {
    el.addEventListener("change", runIpoAnalysis);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runIpoAnalysis();
      }
    });
  });

  document.getElementById("ipoLoadSampleBtn").addEventListener("click", () => {
    const isSme = document.getElementById("ipoSegment").value === "SME";
    if (isSme) {
      document.getElementById("ipoCompany").value = "Apex Precision SME Components Ltd";
      document.getElementById("ipoPriceMax").value = "120";
      document.getElementById("ipoLotSize").value = "1200";
      document.getElementById("ipoIssueSize").value = "38";
      document.getElementById("ipoFreshPct").value = "100";
      document.getElementById("ipoEps").value = "6.5";
      document.getElementById("ipoRev1").value = "42";
      document.getElementById("ipoRev2").value = "58";
      document.getElementById("ipoRev3").value = "81";
      document.getElementById("ipoPat1").value = "2.1";
      document.getElementById("ipoPat2").value = "3.4";
      document.getElementById("ipoPat3").value = "11.5";
      document.getElementById("ipoNetWorth").value = "28";
      document.getElementById("ipoDebt").value = "36";
      document.getElementById("ipoMcap").value = "";
      document.getElementById("ipoSubQib").value = "1.2";
      document.getElementById("ipoSubNii").value = "8.5";
      document.getElementById("ipoSubRetail").value = "22";
      document.getElementById("ipoSubTotal").value = "14";
      document.getElementById("ipoPeerPe").value = "22";
    } else {
      document.getElementById("ipoCompany").value = "Sample Tech India Ltd";
      document.getElementById("ipoPriceMax").value = "250";
      document.getElementById("ipoLotSize").value = "60";
      document.getElementById("ipoIssueSize").value = "450";
      document.getElementById("ipoFreshPct").value = "75";
      document.getElementById("ipoEps").value = "11.5";
      document.getElementById("ipoRev1").value = "180";
      document.getElementById("ipoRev2").value = "240";
      document.getElementById("ipoRev3").value = "325";
      document.getElementById("ipoPat1").value = "18";
      document.getElementById("ipoPat2").value = "27";
      document.getElementById("ipoPat3").value = "42";
      document.getElementById("ipoNetWorth").value = "190";
      document.getElementById("ipoDebt").value = "45";
      document.getElementById("ipoMcap").value = "";
      document.getElementById("ipoSubQib").value = "24";
      document.getElementById("ipoSubNii").value = "18";
      document.getElementById("ipoSubRetail").value = "12";
      document.getElementById("ipoSubTotal").value = "17";
      document.getElementById("ipoPeerPe").value = "28";
    }
    runIpoAnalysis();
  });
})();
