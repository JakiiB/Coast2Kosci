/**
 * Coast to Kosciuszko (C2K) - 60 FPS Broadcast Telemetry HUD, Cutoff Calculator & 241km Elevation Scrubber
 * Zero-reflow architecture: cached canvas dimensions, dynamic course gates, and unified Pointer Events.
 */

window.C2KBroadcastHud = (function () {
  let courseData = null;
  let eleCanvas = null;
  let eleCtx = null;
  let cachedW = 800;
  let cachedH = 112;
  let hoverKm = null;
  let isDraggingProfile = false;
  let lastDomUpdateTs = 0;

  let cutoffGates = [
    { id: "dalgety", name: "Cut-Off #1 • Dalgety (CP5)", km: 149.21, limitHours: 25.0, clockLabel: "Sat 06:30", lat: -36.504593, lon: 148.831006 },
    { id: "jindabyne", name: "Cut-Off #2 • Jindabyne (CP6)", km: 184.88, limitHours: 32.5, clockLabel: "Sat 14:00", lat: -36.409431, lon: 148.59668 },
    { id: "charlotte_out", name: "Cut-Off #3 • Charlotte Pass (CP8)", km: 222.63, limitHours: 41.5, clockLabel: "Sat 23:00", lat: -36.43155, lon: 148.329009 },
    { id: "finish", name: "Final Cut-Off • Charlotte Pass Finish", km: 241.25, limitHours: 46.0, clockLabel: "Sun 03:30", lat: -36.431729, lon: 148.328413 }
  ];

  let profileKeyLabels = [];

  function init(data) {
    courseData = data;
    if (courseData && Array.isArray(courseData.cutoff_gates) && courseData.cutoff_gates.length) {
      cutoffGates = courseData.cutoff_gates;
    }
    buildProfileLabelsFromPois();

    eleCanvas = document.getElementById("elevation-canvas");
    if (eleCanvas) {
      eleCtx = eleCanvas.getContext("2d");
      resizeElevationCanvas();
      window.addEventListener("resize", function () {
        resizeElevationCanvas();
        drawElevationProfile();
      });
      bindElevationEvents();
    }
    initCutoffGatesDom();
    renderWeatherZones((courseData && courseData.weather_zones) || []);
  }

  function buildProfileLabelsFromPois() {
    const pois = (courseData && courseData.pois) || [];
    const labels = [];
    const wanted = [
      { match: "Checkpoint #1", text: "CP1 Towamba" },
      { match: "Checkpoint #2", text: "CP2 Rocky Hall" },
      { match: "Checkpoint #3", text: "CP3 Cathcart" },
      { match: "Checkpoint #4", text: "CP4 Gunningrah" },
      { match: "Checkpoint #5", text: "CP5 Dalgety" },
      { match: "Checkpoint #6", text: "CP6 Jindabyne" },
      { match: "Checkpoint #7", text: "CP7 Perisher" },
      { match: "Summit of Mt Kosciuszko", text: "SUMMIT 2228m" }
    ];
    wanted.forEach(function (item) {
      const hit = pois.find(function (p) { return p.name && p.name.indexOf(item.match) !== -1; });
      if (hit) {
        labels.push({ km: hit.course_km, label: item.text });
      }
    });
    if (!labels.length) {
      profileKeyLabels = [
        { km: 24.38, label: "CP1 Towamba" },
        { km: 51.67, label: "CP2 Rocky Hall" },
        { km: 70.60, label: "CP3 Cathcart" },
        { km: 107.56, label: "CP4 Gunningrah" },
        { km: 148.93, label: "CP5 Dalgety" },
        { km: 184.86, label: "CP6 Jindabyne" },
        { km: 213.87, label: "CP7 Perisher" },
        { km: 231.94, label: "SUMMIT 2228m" }
      ];
    } else {
      profileKeyLabels = labels;
    }
  }

  function resizeElevationCanvas() {
    if (!eleCanvas) return;
    const rect = eleCanvas.parentElement.getBoundingClientRect();
    cachedW = Math.max(200, rect.width || 600);
    cachedH = Math.max(76, rect.height || 105);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    eleCanvas.width = Math.floor(cachedW * dpr);
    eleCanvas.height = Math.floor(cachedH * dpr);
    if (eleCtx) {
      eleCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  }

  function bindElevationEvents() {
    function getKmFromPointerEvent(e) {
      const rect = eleCanvas.getBoundingClientRect();
      const padL = 38;
      const padR = 16;
      const plotW = Math.max(10, rect.width - padL - padR);
      const x = e.clientX - rect.left - padL;
      const frac = Math.max(0, Math.min(1, x / plotW));
      return frac * ((courseData && courseData.meta && courseData.meta.total_distance_km) || 241.25);
    }

    eleCanvas.addEventListener("pointerdown", function (e) {
      isDraggingProfile = true;
      if (eleCanvas.setPointerCapture) {
        try { eleCanvas.setPointerCapture(e.pointerId); } catch (err) {}
      }
      const km = getKmFromPointerEvent(e);
      hoverKm = km;
      if (window.C2KTelemetryClient) {
        window.C2KTelemetryClient.setSimProgressByKm(km);
      }
      drawElevationProfile();
    });

    eleCanvas.addEventListener("pointermove", function (e) {
      hoverKm = getKmFromPointerEvent(e);
      const pt = window.C2KTerrainEngine.getPointAtKm(hoverKm);
      if (pt) {
        window.C2KTerrainEngine.showScrubHoverPin(pt[0], pt[1], true);
      }
      if (isDraggingProfile && window.C2KTelemetryClient) {
        window.C2KTelemetryClient.setSimProgressByKm(hoverKm);
      }
      drawElevationProfile();
    });

    function stopDrag(e) {
      isDraggingProfile = false;
      if (e && e.pointerId !== undefined && eleCanvas.releasePointerCapture) {
        try { eleCanvas.releasePointerCapture(e.pointerId); } catch (err) {}
      }
    }

    eleCanvas.addEventListener("pointerup", stopDrag);
    eleCanvas.addEventListener("pointercancel", stopDrag);

    eleCanvas.addEventListener("pointerleave", function () {
      if (!isDraggingProfile) {
        hoverKm = null;
        window.C2KTerrainEngine.showScrubHoverPin(0, 0, false);
        drawElevationProfile();
      }
    });

    eleCanvas.addEventListener("dblclick", function (e) {
      const km = getKmFromPointerEvent(e);
      const pt = window.C2KTerrainEngine.getPointAtKm(km);
      if (pt) {
        window.C2KTerrainEngine.flyToCoordinate(pt[0], pt[1], 13.4, 64, pt[5]);
      }
    });
  }

  function formatPaceMinKm(speedKmh) {
    if (!speedKmh || speedKmh < 0.8) return "--:--";
    const minsPerKm = 60.0 / speedKmh;
    const m = Math.floor(minsPerKm);
    const s = Math.round((minsPerKm - m) * 60);
    return m + ":" + (s < 10 ? "0" + s : s);
  }

  function formatRaceClock(elapsedHours, mode) {
    const pad = function (n) { return n < 10 ? "0" + n : String(n); };
    if (mode === "LIVE" && elapsedHours < 0) {
      const remH = Math.abs(elapsedHours);
      const d = Math.floor(remH / 24);
      const h = Math.floor(remH % 24);
      const m = Math.floor((remH * 60) % 60);
      return "T-" + d + "d " + pad(h) + "h " + pad(m) + "m • FRI NOV 20 05:30";
    }
    const clampedH = Math.max(0, elapsedHours);
    const h = Math.floor(clampedH);
    const m = Math.floor((clampedH - h) * 60);
    const days = ["FRI", "SAT", "SUN"];
    const totalLocalHours = 5.5 + clampedH;
    const dayIdx = Math.min(2, Math.floor(totalLocalHours / 24));
    const clockH = Math.floor(totalLocalHours % 24);
    const clockM = Math.floor((totalLocalHours * 60) % 60);
    return "+" + pad(h) + "h " + pad(m) + "m • " + days[dayIdx] + " " + pad(clockH) + ":" + pad(clockM);
  }

  function initCutoffGatesDom() {
    const container = document.getElementById("cutoff-gates-list");
    if (!container) return;
    let html = "";
    for (let i = 0; i < cutoffGates.length; i++) {
      const g = cutoffGates[i];
      html +=
        '<div id="cutoff-row-' + g.id + '" class="cutoff-row" data-lon="' + g.lon + '" data-lat="' + g.lat + '">' +
          '<div>' +
            '<div class="cutoff-name">' + g.name + '</div>' +
            '<div class="cutoff-meta">' + g.km.toFixed(1) + ' km • Gate: ' + g.clockLabel + ' (' + g.limitHours + 'h)</div>' +
          '</div>' +
          '<span id="cutoff-badge-' + g.id + '" class="cutoff-margin positive">--</span>' +
        '</div>';
    }
    container.innerHTML = html;
    container.querySelectorAll(".cutoff-row").forEach(function (row) {
      row.addEventListener("click", function () {
        const lon = parseFloat(row.getAttribute("data-lon"));
        const lat = parseFloat(row.getAttribute("data-lat"));
        if (!isNaN(lon) && !isNaN(lat)) {
          window.C2KTerrainEngine.flyToCoordinate(lon, lat, 13.4, 64, -30);
        }
      });
    });
  }

  function applyEpistemicBadge(badgeEl, status, mode) {
    if (!badgeEl) return;
    if (mode === "SIM" || status === "SIMULATION") {
      badgeEl.className = "epistemic-badge hypothesis";
      badgeEl.textContent = "46H SIMULATOR";
    } else if (status === "PRE_RACE_BASELINE") {
      badgeEl.className = "epistemic-badge neutral";
      badgeEl.textContent = "PRE-RACE READY";
    } else if (status === "CONFIRMED_FIX") {
      badgeEl.className = "epistemic-badge confirmed";
      badgeEl.textContent = "CONFIRMED FIX";
    } else if (status === "HYPOTHESIS_PACE_ESTIMATE") {
      badgeEl.className = "epistemic-badge hypothesis";
      badgeEl.textContent = "HYPOTHESIS: PACE EST.";
    } else {
      badgeEl.className = "epistemic-badge stale";
      badgeEl.textContent = "STALE FIX";
    }
  }

  function updateHud(runner, crew, elapsedHours, mode) {
    if (!runner || !crew || !courseData) return;

    const now = performance.now();
    drawElevationProfile();
    if (now - lastDomUpdateTs < 150 && !isDraggingProfile) return;
    lastDomUpdateTs = now;

    const totalKm = courseData.meta.total_distance_km || 241.25;

    const clockEl = document.getElementById("sim-clock-readout");
    if (clockEl) {
      clockEl.textContent = formatRaceClock(elapsedHours, mode);
    }
    const sliderEl = document.getElementById("sim-time-slider");
    if (sliderEl && !isDraggingProfile && mode === "SIM") {
      sliderEl.value = Math.max(0, Math.min(46, elapsedHours)).toFixed(2);
    }

    const rKm = runner.course_km || 0;
    const remKm = Math.max(0, totalKm - rKm);
    setText("r-dist-km", rKm.toFixed(1));
    setText("r-rem-km", remKm.toFixed(1));
    setText("r-ele-m", Math.round(runner.ele_m || 0));
    setText("r-grade-pct", (runner.grade_pct > 0 ? "+" : "") + (runner.grade_pct || 0).toFixed(1) + "%");
    setText("r-speed-kmh", (runner.speed_kmh || 0).toFixed(1));
    setText("r-pace", formatPaceMinKm(runner.speed_kmh));
    setText("r-note", runner.note || "");

    const rBat = runner.battery_pct !== undefined ? " • Bat " + runner.battery_pct + "%" : "";
    const rAge = runner.fix_age_text ? " • " + runner.fix_age_text : "";
    setText("r-source", (runner.source || "Telemetry") + rAge + rBat);

    applyEpistemicBadge(document.getElementById("r-epistemic-badge"), runner.epistemic, mode);
    applyEpistemicBadge(document.getElementById("c-epistemic-badge"), crew.epistemic, mode);

    const checkpoints = (courseData.pois || []).filter(function (p) {
      return p.category === "checkpoint" || p.category === "summit" || p.category === "finish";
    });
    const nextCp = checkpoints.find(function (p) { return p.course_km > rKm + 0.2; }) || checkpoints[checkpoints.length - 1];
    if (nextCp) {
      const distToCp = Math.max(0, nextCp.course_km - rKm);
      const effSpeed = Math.max(4.5, runner.speed_kmh || 6.2);
      const etaMins = Math.round((distToCp / effSpeed) * 60);
      const etaStr = etaMins >= 60 ? Math.floor(etaMins / 60) + "h " + (etaMins % 60) + "m" : etaMins + "m";
      setText(
        "r-next-cp",
        nextCp.name.replace("Mandatory Checkpoint ", "CP") + " (" + distToCp.toFixed(1) + " km • ~" + etaStr + ")"
      );
    }

    const sepKm = window.C2KTelemetryClient.haversineKm(runner.lat, runner.lon, crew.lat, crew.lon);
    setText("c-course-km", (crew.course_km || 0).toFixed(1));
    setText("c-ele-m", Math.round(crew.ele_m || 0));
    setText("c-sep-km", sepKm.toFixed(2));
    setText("c-speed-kmh", Math.round(crew.speed_kmh || 0));
    setText("c-note", crew.note || "");
    setText("c-fix-age", (crew.source || "Crew") + " • " + (crew.fix_age_text || "Ready"));

    setText(
      "mob-summary-text",
      "🏃 " + rKm.toFixed(1) + "k (" + Math.round(runner.ele_m || 0) + "m)  •  🚙 Gap " + sepKm.toFixed(1) + "k"
    );

    updateCutoffGatesInPlace(rKm, Math.max(0, elapsedHours), runner.speed_kmh || 6.2);
  }

  function updateCutoffGatesInPlace(currentKm, elapsedHours, currentSpeedKmh) {
    const avgSpeed = elapsedHours > 0.5 && currentKm > 2
      ? Math.max(4.2, currentKm / elapsedHours)
      : Math.max(5.5, currentSpeedKmh || 6.3);

    let foundActive = false;
    for (let i = 0; i < cutoffGates.length; i++) {
      const g = cutoffGates[i];
      const passed = currentKm >= g.km;
      const isActive = !passed && !foundActive;
      if (isActive) foundActive = true;

      let marginHours = 0;
      if (passed) {
        const estArrivalHrs = g.km / avgSpeed;
        marginHours = g.limitHours - estArrivalHrs;
      } else {
        const remKm = g.km - currentKm;
        const projArrivalHrs = elapsedHours + remKm / avgSpeed;
        marginHours = g.limitHours - projArrivalHrs;
      }

      const absH = Math.floor(Math.abs(marginHours));
      const absM = Math.round((Math.abs(marginHours) - absH) * 60);
      const sign = marginHours >= 0 ? "+" : "-";
      const marginClass = marginHours >= 2.0 ? "positive" : marginHours >= 0 ? "tight" : "danger";
      const statusText = passed
        ? "CLEARED (" + sign + absH + "h" + (absM < 10 ? "0" : "") + absM + "m)"
        : sign + absH + "h " + (absM < 10 ? "0" : "") + absM + "m buf";

      const rowEl = document.getElementById("cutoff-row-" + g.id);
      const badgeEl = document.getElementById("cutoff-badge-" + g.id);
      if (rowEl) {
        rowEl.className = "cutoff-row " + (passed ? "passed" : isActive ? "active-gate" : "");
      }
      if (badgeEl) {
        badgeEl.className = "cutoff-margin " + marginClass;
        badgeEl.textContent = statusText;
      }
    }
  }

  function renderWeatherZones(zones) {
    const container = document.getElementById("weather-zones-list");
    if (!container) return;

    let html = "";
    zones.forEach(function (z) {
      const w = z.weather || {};
      const temp = w.temp_c !== undefined ? Math.round(w.temp_c * 10) / 10 : "--";
      const wind = w.windspeed_kmh !== undefined ? Math.round(w.windspeed_kmh) : "--";
      const dir = w.winddir_deg !== undefined ? Math.round(w.winddir_deg) : 0;
      const clouds = w.cloudcover_pct !== undefined ? Math.round(w.cloudcover_pct) : 0;

      html +=
        '<div class="weather-zone-item" data-lon="' + z.lon + '" data-lat="' + z.lat + '">' +
          '<div class="wz-left">' +
            '<span class="wz-name">' + z.name + ' <span style="opacity:0.6;font-weight:400;">(' + z.ele_m + 'm)</span></span>' +
            '<span class="wz-sub">' + (w.conditions || "Partly Cloudy") + ' • Clouds ' + clouds + '%</span>' +
          '</div>' +
          '<div class="wz-right">' +
            '<div class="wz-temp">' + temp + '°C</div>' +
            '<div class="wz-wind">💨 ' + wind + ' km/h (' + dir + '°)</div>' +
          '</div>' +
        '</div>';
    });

    container.innerHTML = html;
    container.querySelectorAll(".weather-zone-item").forEach(function (item) {
      item.addEventListener("click", function () {
        const lon = parseFloat(item.getAttribute("data-lon"));
        const lat = parseFloat(item.getAttribute("data-lat"));
        window.C2KTerrainEngine.flyToCoordinate(lon, lat, 12.4, 64, -35);
      });
    });
  }

  function drawElevationProfile() {
    if (!eleCtx || !eleCanvas || !courseData || !courseData.track) return;
    const w = cachedW;
    const h = cachedH;
    eleCtx.clearRect(0, 0, w, h);

    const padL = 38;
    const padR = 16;
    const padT = 16;
    const padB = 20;
    const plotW = Math.max(10, w - padL - padR);
    const plotH = Math.max(10, h - padT - padB);

    const totalKm = courseData.meta.total_distance_km || 241.25;
    const maxEle = 2300.0;
    const track = courseData.track;

    const xOfKm = function (km) { return padL + (km / totalKm) * plotW; };
    const yOfEle = function (ele) { return padT + plotH - (Math.max(0, ele) / maxEle) * plotH; };

    eleCtx.strokeStyle = "rgba(255, 255, 255, 0.07)";
    eleCtx.fillStyle = "rgba(148, 163, 184, 0.75)";
    eleCtx.font = "10px 'JetBrains Mono', monospace";
    eleCtx.lineWidth = 1;
    [0, 1000, 2000].forEach(function (elev) {
      const y = yOfEle(elev);
      eleCtx.beginPath();
      eleCtx.moveTo(padL, y);
      eleCtx.lineTo(padL + plotW, y);
      eleCtx.stroke();
      eleCtx.fillText(elev + "m", 2, y + 3);
    });

    const bgGrad = eleCtx.createLinearGradient(0, padT, 0, padT + plotH);
    bgGrad.addColorStop(0, "rgba(148, 163, 184, 0.25)");
    bgGrad.addColorStop(1, "rgba(15, 23, 42, 0.05)");
    eleCtx.fillStyle = bgGrad;
    eleCtx.beginPath();
    eleCtx.moveTo(xOfKm(0), yOfEle(0));
    for (let i = 0; i < track.length; i += 4) {
      eleCtx.lineTo(xOfKm(track[i][3]), yOfEle(track[i][2]));
    }
    eleCtx.lineTo(xOfKm(totalKm), yOfEle(0));
    eleCtx.closePath();
    eleCtx.fill();

    const runner = window.C2KTelemetryClient ? window.C2KTelemetryClient.getRunnerState() : null;
    const rKm = runner ? runner.course_km || 0 : 0;

    if (rKm > 0.2) {
      const doneGrad = eleCtx.createLinearGradient(0, padT, 0, padT + plotH);
      doneGrad.addColorStop(0, "rgba(255, 90, 31, 0.55)");
      doneGrad.addColorStop(1, "rgba(255, 90, 31, 0.06)");
      eleCtx.fillStyle = doneGrad;
      eleCtx.beginPath();
      eleCtx.moveTo(xOfKm(0), yOfEle(0));
      for (let i = 0; i < track.length; i += 2) {
        if (track[i][3] > rKm) break;
        eleCtx.lineTo(xOfKm(track[i][3]), yOfEle(track[i][2]));
      }
      eleCtx.lineTo(xOfKm(rKm), yOfEle(0));
      eleCtx.closePath();
      eleCtx.fill();
    }

    eleCtx.strokeStyle = "#f59e0b";
    eleCtx.lineWidth = 1.8;
    eleCtx.beginPath();
    for (let i = 0; i < track.length; i += 3) {
      const x = xOfKm(track[i][3]);
      const y = yOfEle(track[i][2]);
      if (i === 0) eleCtx.moveTo(x, y);
      else eleCtx.lineTo(x, y);
    }
    eleCtx.stroke();

    if (rKm > 0.2) {
      eleCtx.strokeStyle = "#ff5a1f";
      eleCtx.lineWidth = 2.4;
      eleCtx.beginPath();
      for (let i = 0; i < track.length; i += 2) {
        if (track[i][3] > rKm) break;
        const x = xOfKm(track[i][3]);
        const y = yOfEle(track[i][2]);
        if (i === 0) eleCtx.moveTo(x, y);
        else eleCtx.lineTo(x, y);
      }
      eleCtx.stroke();
    }

    eleCtx.font = "9.5px 'JetBrains Mono', monospace";
    const hideLabels = w < 540;
    profileKeyLabels.forEach(function (kl, idx) {
      const x = xOfKm(kl.km);
      eleCtx.strokeStyle = kl.label.indexOf("SUMMIT") !== -1 ? "rgba(251, 191, 36, 0.55)" : "rgba(56, 189, 248, 0.25)";
      eleCtx.beginPath();
      eleCtx.moveTo(x, padT);
      eleCtx.lineTo(x, padT + plotH);
      eleCtx.stroke();

      if (!hideLabels || idx % 2 === 0 || kl.label.indexOf("SUMMIT") !== -1) {
        eleCtx.fillStyle = kl.label.indexOf("SUMMIT") !== -1 ? "#fde047" : "#94a3b8";
        eleCtx.fillText(hideLabels ? kl.label.split(" ")[0] : kl.label, x - 18, padT + plotH + 13);
      }
    });

    const crew = window.C2KTelemetryClient ? window.C2KTelemetryClient.getCrewState() : null;
    if (crew) {
      const cx = xOfKm(crew.course_km || 0);
      const cy = yOfEle(crew.ele_m || 0);
      eleCtx.fillStyle = "#00e5ff";
      eleCtx.beginPath();
      eleCtx.arc(cx, cy, 4.5, 0, Math.PI * 2);
      eleCtx.fill();
    }

    if (runner) {
      const rx = xOfKm(rKm);
      const ry = yOfEle(runner.ele_m || 0);
      eleCtx.strokeStyle = "rgba(255, 90, 31, 0.7)";
      eleCtx.beginPath();
      eleCtx.moveTo(rx, padT);
      eleCtx.lineTo(rx, padT + plotH);
      eleCtx.stroke();

      eleCtx.fillStyle = "#ff5a1f";
      eleCtx.beginPath();
      eleCtx.arc(rx, ry, 6, 0, Math.PI * 2);
      eleCtx.fill();
      eleCtx.strokeStyle = "#ffffff";
      eleCtx.lineWidth = 2;
      eleCtx.stroke();
    }

    if (hoverKm !== null) {
      const hx = xOfKm(hoverKm);
      const hPt = window.C2KTerrainEngine.getPointAtKm(hoverKm);
      const hEle = hPt ? Math.round(hPt[2]) : 0;
      const hGrade = hPt ? hPt[4].toFixed(1) : "0.0";

      eleCtx.strokeStyle = "rgba(255, 255, 255, 0.75)";
      eleCtx.lineWidth = 1;
      eleCtx.beginPath();
      eleCtx.moveTo(hx, padT);
      eleCtx.lineTo(hx, padT + plotH);
      eleCtx.stroke();

      const tipText = hoverKm.toFixed(1) + " km • " + hEle + "m (" + (hGrade > 0 ? "+" : "") + hGrade + "%)";
      const tw = eleCtx.measureText(tipText).width + 12;
      const tx = Math.min(w - tw - 6, Math.max(padL, hx - tw / 2));
      eleCtx.fillStyle = "rgba(8, 12, 22, 0.94)";
      eleCtx.fillRect(tx, 2, tw, 16);
      eleCtx.strokeStyle = "rgba(255, 90, 31, 0.7)";
      eleCtx.strokeRect(tx, 2, tw, 16);
      eleCtx.fillStyle = "#ffffff";
      eleCtx.fillText(tipText, tx + 6, 13);
    }
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el && el.textContent !== String(val)) {
      el.textContent = String(val);
    }
  }

  return {
    init: init,
    updateHud: updateHud,
    renderWeatherZones: renderWeatherZones,
    drawElevationProfile: drawElevationProfile,
    resizeElevationCanvas: resizeElevationCanvas
  };
})();
