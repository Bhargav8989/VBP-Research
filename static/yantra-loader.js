(() => {
  let progressInterval = null;
  let loopTimeout = null;
  let isVisible = false;

  const SVG_TEMPLATE = `
    <div class="yantra-aura"></div>
    <div id="shree-yantra-loader" class="relative flex flex-col items-center justify-center w-full" role="status" aria-live="polite">
      <svg id="yantraSvg" class="shree-yantra-svg" viewBox="0 0 500 500" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="sacredGold" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#fff3b0" />
            <stop offset="35%" stop-color="#f7b733" />
            <stop offset="70%" stop-color="#e86f1c" />
            <stop offset="100%" stop-color="#ffd966" />
          </linearGradient>
          <linearGradient id="innerFire" x1="50%" y1="0%" x2="50%" y2="100%">
            <stop offset="0%" stop-color="#fff8d6" />
            <stop offset="50%" stop-color="#ffbe3b" />
            <stop offset="100%" stop-color="#d94e1f" />
          </linearGradient>
        </defs>
        <g id="layer-bhupura" stroke="url(#sacredGold)" stroke-width="2.2">
          <path class="draw-path" style="--len: 2300; --dur: 2.1s; --delay: 0s;"
            d="M 35 35 L 210 35 L 210 18 L 192 18 L 192 8 L 308 8 L 308 18 L 290 18 L 290 35
               L 465 35 L 465 210 L 482 210 L 482 192 L 492 192 L 492 308 L 482 308 L 482 290 L 465 290
               L 465 465 L 290 465 L 290 482 L 308 482 L 308 492 L 192 492 L 192 482 L 210 482 L 210 465
               L 35 465 L 35 290 L 18 290 L 18 308 L 8 308 L 8 192 L 18 192 L 18 210 L 35 210 Z" />
          <path class="draw-path" style="--len: 2150; --dur: 2.0s; --delay: 0.25s;" stroke-width="1.3" stroke-opacity="0.75"
            d="M 45 45 L 218 45 L 218 27 L 202 27 L 202 18 L 298 18 L 298 27 L 282 27 L 282 45
               L 455 45 L 455 218 L 473 218 L 473 202 L 482 202 L 482 298 L 473 298 L 473 282 L 455 282
               L 455 455 L 282 455 L 282 473 L 298 473 L 298 482 L 202 482 L 202 473 L 218 473 L 218 455
               L 45 455 L 45 282 L 27 282 L 27 298 L 18 298 L 18 202 L 27 202 L 27 218 L 45 218 Z" />
          <rect class="draw-path" style="--len: 1600; --dur: 1.6s; --delay: 0.45s;"
            x="56" y="56" width="388" height="388" stroke-width="1.6" />
        </g>
        <g id="layer-rings" stroke="url(#sacredGold)">
          <circle class="draw-path" style="--len: 1185; --dur: 1.5s; --delay: 0.7s;" cx="250" cy="250" r="188" stroke-width="1.8" />
          <circle class="draw-path" style="--len: 1145; --dur: 1.5s; --delay: 0.85s;" cx="250" cy="250" r="182" stroke-width="1.1" stroke-opacity="0.7" />
          <circle class="draw-path" style="--len: 1105; --dur: 1.5s; --delay: 1.0s;" cx="250" cy="250" r="176" stroke-width="1.6" />
        </g>
        <g id="layer-lotus-16" class="rotate-slow-cw" stroke="url(#sacredGold)" stroke-width="1.5"></g>
        <circle class="draw-path" style="--len: 930; --dur: 1.4s; --delay: 1.55s;"
          cx="250" cy="250" r="148" stroke="url(#sacredGold)" stroke-width="1.7" />
        <g id="layer-lotus-8" class="rotate-slow-ccw" stroke="url(#sacredGold)" stroke-width="1.7"></g>
        <circle class="draw-path" style="--len: 755; --dur: 1.3s; --delay: 2.05s;"
          cx="250" cy="250" r="120" stroke="url(#sacredGold)" stroke-width="2" />
        <g id="layer-triangles" stroke="url(#innerFire)" stroke-width="1.85">
          <polygon class="draw-path" style="--len: 660; --dur: 1.3s; --delay: 2.25s;" points="250,368 147,190 353,190" />
          <polygon class="draw-path" style="--len: 660; --dur: 1.3s; --delay: 2.40s;" points="250,132 147,310 353,310" />
          <polygon class="draw-path" style="--len: 560; --dur: 1.2s; --delay: 2.55s;" points="250,348 161,202 339,202" />
          <polygon class="draw-path" style="--len: 560; --dur: 1.2s; --delay: 2.70s;" points="250,152 162,296 338,296" />
          <polygon class="draw-path" style="--len: 450; --dur: 1.1s; --delay: 2.85s;" points="250,326 178,215 322,215" />
          <polygon class="draw-path" style="--len: 430; --dur: 1.1s; --delay: 3.00s;" points="250,174 182,282 318,282" />
          <polygon class="draw-path" style="--len: 330; --dur: 1.0s; --delay: 3.15s;" points="250,301 198,227 302,227" />
          <polygon class="draw-path" style="--len: 270; --dur: 0.95s; --delay: 3.30s;" points="250,202 212,267 288,267" />
          <polygon class="draw-path" style="--len: 210; --dur: 0.9s; --delay: 3.45s;" points="250,276 222,235 278,235" />
        </g>
        <g id="layer-bindu">
          <circle class="bindu-ring" cx="250" cy="250" r="6" fill="none" stroke="#ffe680" stroke-width="1.2" />
          <circle class="bindu-core" cx="250" cy="250" r="4.2" fill="#fffdf5" />
        </g>
      </svg>
      <div class="mt-4 flex flex-col items-center text-center w-full max-w-[300px]">
        <p id="yantraLoadingTitle" class="font-sacred text-sm sm:text-base tracking-[0.2em] uppercase loading-shimmer font-semibold">
          Working On
        </p>
        <p id="yantraLoadingSub" class="mt-1 text-[11px] text-amber-100/80 leading-snug">
          For educational research only — not SEBI-registered investment advice.
        </p>
        <div class="mt-2.5 w-full h-1.5 rounded-full bg-amber-950/80 overflow-hidden border border-amber-500/25 shadow-inner">
          <div id="yantraProgressBar" class="h-full bg-gradient-to-r from-orange-500 via-amber-300 to-yellow-200 rounded-full transition-all duration-150" style="width: 1%;"></div>
        </div>
        <span id="yantraLoadingPercent" class="mt-1.5 text-xs font-mono tracking-widest text-amber-200/85">1%</span>
      </div>
    </div>
  `;

  function generateLotusPetals() {
    const svgNS = "http://www.w3.org/2000/svg";
    const cx = 250;
    const cy = 250;

    const group16 = document.getElementById("layer-lotus-16");
    if (group16) {
      group16.innerHTML = "";
      const rInner16 = 148;
      const rOuter16 = 175.5;
      const step16 = (Math.PI * 2) / 16;
      for (let i = 0; i < 16; i++) {
        const aMid = i * step16 - Math.PI / 2;
        const aStart = aMid - step16 * 0.48;
        const aEnd = aMid + step16 * 0.48;
        const x1 = cx + rInner16 * Math.cos(aStart);
        const y1 = cy + rInner16 * Math.sin(aStart);
        const x2 = cx + rInner16 * Math.cos(aEnd);
        const y2 = cy + rInner16 * Math.sin(aEnd);
        const tipX = cx + rOuter16 * Math.cos(aMid);
        const tipY = cy + rOuter16 * Math.sin(aMid);
        const cpRadius = rInner16 + (rOuter16 - rInner16) * 0.65;
        const cp1X = cx + cpRadius * Math.cos(aStart + step16 * 0.12);
        const cp1Y = cy + cpRadius * Math.sin(aStart + step16 * 0.12);
        const cp2X = cx + cpRadius * Math.cos(aEnd - step16 * 0.12);
        const cp2Y = cy + cpRadius * Math.sin(aEnd - step16 * 0.12);

        const path = document.createElementNS(svgNS, "path");
        path.setAttribute(
          "d",
          `M ${x1.toFixed(2)} ${y1.toFixed(2)} Q ${cp1X.toFixed(2)} ${cp1Y.toFixed(2)} ${tipX.toFixed(2)} ${tipY.toFixed(2)} Q ${cp2X.toFixed(2)} ${cp2Y.toFixed(2)} ${x2.toFixed(2)} ${y2.toFixed(2)}`
        );
        path.classList.add("draw-path");
        path.style.setProperty("--len", "110");
        path.style.setProperty("--dur", "0.9s");
        path.style.setProperty("--delay", `${(1.15 + i * 0.03).toFixed(2)}s`);
        group16.appendChild(path);
      }
    }

    const group8 = document.getElementById("layer-lotus-8");
    if (group8) {
      group8.innerHTML = "";
      const rInner8 = 120;
      const rOuter8 = 147.5;
      const step8 = (Math.PI * 2) / 8;
      for (let i = 0; i < 8; i++) {
        const aMid = i * step8 - Math.PI / 2;
        const aStart = aMid - step8 * 0.47;
        const aEnd = aMid + step8 * 0.47;
        const x1 = cx + rInner8 * Math.cos(aStart);
        const y1 = cy + rInner8 * Math.sin(aStart);
        const x2 = cx + rInner8 * Math.cos(aEnd);
        const y2 = cy + rInner8 * Math.sin(aEnd);
        const tipX = cx + rOuter8 * Math.cos(aMid);
        const tipY = cy + rOuter8 * Math.sin(aMid);
        const cpRadius = rInner8 + (rOuter8 - rInner8) * 0.68;
        const cp1X = cx + cpRadius * Math.cos(aStart + step8 * 0.12);
        const cp1Y = cy + cpRadius * Math.sin(aStart + step8 * 0.12);
        const cp2X = cx + cpRadius * Math.cos(aEnd - step8 * 0.12);
        const cp2Y = cy + cpRadius * Math.sin(aEnd - step8 * 0.12);

        const path = document.createElementNS(svgNS, "path");
        path.setAttribute(
          "d",
          `M ${x1.toFixed(2)} ${y1.toFixed(2)} Q ${cp1X.toFixed(2)} ${cp1Y.toFixed(2)} ${tipX.toFixed(2)} ${tipY.toFixed(2)} Q ${cp2X.toFixed(2)} ${cp2Y.toFixed(2)} ${x2.toFixed(2)} ${y2.toFixed(2)}`
        );
        path.classList.add("draw-path");
        path.style.setProperty("--len", "140");
        path.style.setProperty("--dur", "1.0s");
        path.style.setProperty("--delay", `${(1.65 + i * 0.05).toFixed(2)}s`);
        group8.appendChild(path);
      }
    }
  }

  function startProgress() {
    clearInterval(progressInterval);
    clearTimeout(loopTimeout);
    const bar = document.getElementById("yantraProgressBar");
    const pctText = document.getElementById("yantraLoadingPercent");
    if (!bar || !pctText) return;

    let current = 1;
    bar.style.width = "1%";
    pctText.textContent = "1%";

    progressInterval = setInterval(() => {
      if (!isVisible) {
        clearInterval(progressInterval);
        return;
      }
      current += 1;
      if (current > 98) {
        clearInterval(progressInterval);
        return;
      }
      bar.style.width = current + "%";
      pctText.textContent = current + "%";
    }, 35);
  }

  window.VBPYantraLoader = {
    show(title = "Working On", subtitle = "For educational research only — not SEBI-registered investment advice.") {
      const overlay = document.getElementById("globalYantraOverlay");
      if (!overlay) return;
      const stage = document.getElementById("globalYantraStage");
      if (stage) {
        stage.innerHTML = SVG_TEMPLATE;
      }
      const titleEl = document.getElementById("yantraLoadingTitle");
      const subEl = document.getElementById("yantraLoadingSub");
      if (titleEl) titleEl.textContent = title;
      if (subEl) subEl.textContent = subtitle;

      isVisible = true;
      overlay.classList.remove("hidden");
      generateLotusPetals();
      startProgress();
    },
    hide() {
      isVisible = false;
      clearInterval(progressInterval);
      clearTimeout(loopTimeout);
      const bar = document.getElementById("yantraProgressBar");
      const pctText = document.getElementById("yantraLoadingPercent");
      if (bar) bar.style.width = "100%";
      if (pctText) pctText.textContent = "100%";
      const overlay = document.getElementById("globalYantraOverlay");
      if (overlay) {
        overlay.classList.add("hidden");
      }
    },
  };
})();
