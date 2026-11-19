/**
 * Coast to Kosciuszko (C2K) - Editorial Live Readout, 6-Gate 2026 Cut-Off Timer,
 * Official Toilets & Aid Tracker, and Hypsometric 241.25 km Elevation Profile.
 */

window.C2KBroadcastHud = (function () {
  let courseData = null;
  let eleCanvas = null;
  let eleCtx = null;
  let cachedW = 800;
  let cachedH = 138;
  let hoverKm = null;
  let isDraggingProfile = false;
  let lastDomUpdateTs = 0;

  let cutoffGates = [
    { id: "cathcart", name: "Cut-Off #1 - Cathcart (CP3)", shortName: "CP3 Cathcart", km: 70.60, scheduleKm: 70, limitHours: 12.0, clockLabel: "Fri 17:30", lat: -36.84325, lon: 149.39124 },
    { id: "gunningrah", name: "Cut-Off #2 - Gunningrah Rd (CP4)", shortName: "CP4 Gunningrah", km: 107.56, scheduleKm: 106, limitHours: 18.0, clockLabel: "Fri 23:30", lat: -36.69087, lon: 149.15996 },
    { id: "dalgety", name: "Cut-Off #3 - Dalgety Bridge (CP5)", shortName: "CP5 Dalgety", km: 149.21, scheduleKm: 148, limitHours: 25.0, clockLabel: "Sat 06:30", lat: -36.50459, lon: 148.83101 },
    { id: "jindabyne", name: "Cut-Off #4 - Jindabyne (CP6)", shortName: "CP6 Jindabyne", km: 184.88, scheduleKm: 184, limitHours: 32.5, clockLabel: "Sat 14:00", lat: -36.40943, lon: 148.59668 },
    { id: "charlotte_out", name: "Cut-Off #5 - Charlotte Pass (CP8)", shortName: "CP8 Charlotte Out", km: 222.63, scheduleKm: 222, limitHours: 41.5, clockLabel: "Sat 23:00", lat: -36.43155, lon: 148.32901 },
    { id: "finish", name: "Final Cut-Off - Charlotte Pass Finish", shortName: "Finish 240km", km: 241.25, scheduleKm: 240, limitHours: 46.0, clockLabel: "Sun 03:30", lat: -36.43173, lon: 148.32841 }
  ];

  const PROFILE_STATIONS = [
    { km: 0.0, glyph: "S", cutoff: false },
    { km: 24.38, glyph: "1", cutoff: false },
    { km: 51.67, glyph: "2", cutoff: false },
    { km: 70.60, glyph: "3", cutoff: true },
    { km: 107.56, glyph: "4", cutoff: true },
    { km: 149.21, glyph: "5", cutoff: true },
    { km: 184.88, glyph: "6", cutoff: true },
    { km: 213.87, glyph: "7", cutoff: false },
    { km: 222.63, glyph: "8", cutoff: true },
    { km: 241.25, glyph: "F", cutoff: true }
  ];

  let profileMilestones = [];
  let effortProfile = [];
  let totalEffortUnits = 300.0;

  let activeRunnerNextStop = null;
  let activeCrewNextStop = null;
  let lastRenderedToiletKey = "";
  let latestHudArgs = null;
  let countdownInterval = null;

  function init(data) {
    courseData = data;
    if (courseData && Array.isArray(courseData.cutoff_gates) && courseData.cutoff_gates.length) {
      cutoffGates = courseData.cutoff_gates;
    }
    buildEffortProfile();
    buildProfileMilestones();

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
    bindNextStopRows();
    renderToiletsAidList(0);
    renderWeatherZones((courseData && courseData.weather_zones) || []);

    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(function () {
      if (latestHudArgs && window.C2KTelemetryClient) {
        const effElapsed = window.C2KTelemetryClient.getSimElapsedHours();
        const curMode = window.C2KTelemetryClient.getMode();
        updateHud(latestHudArgs.runner, latestHudArgs.crew, effElapsed, curMode, true);
      }
    }, 1000);
  }

  function buildEffortProfile() {
    effortProfile = [];
    if (!courseData || !Array.isArray(courseData.track) || !courseData.track.length) return;
    const track = courseData.track;
    const totalKm = (courseData.meta && courseData.meta.total_distance_km) || 241.25;
    let cumEffort = 0.0;
    effortProfile.push({ km: track[0][3], effort: 0.0 });
    for (let i = 1; i < track.length; i++) {
      const prev = track[i - 1];
      const curr = track[i];
      const dsKm = Math.max(0, curr[3] - prev[3]);
      const dEle = Math.max(0, curr[2] - prev[2]);
      const fatigueFactor = 1.0 + 0.22 * Math.min(1.0, curr[3] / totalKm);
      const climbWeight = dEle * 0.008;
      cumEffort += dsKm * fatigueFactor + climbWeight;
      effortProfile.push({ km: curr[3], effort: cumEffort });
    }
    totalEffortUnits = Math.max(1.0, cumEffort);
  }

  function getEffortAtKm(km) {
    if (!effortProfile.length) return Math.max(0, km);
    if (km <= 0) return 0;
    const last = effortProfile[effortProfile.length - 1];
    if (km >= last.km) return last.effort;
    let lo = 0;
    let hi = effortProfile.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (effortProfile[mid].km < km) lo = mid + 1;
      else hi = mid;
    }
    const p1 = effortProfile[Math.max(0, lo - 1)];
    const p2 = effortProfile[lo];
    const span = p2.km - p1.km;
    const t = span > 0.0001 ? (km - p1.km) / span : 0;
    return p1.effort + (p2.effort - p1.effort) * t;
  }

  function buildProfileMilestones() {
    const stations = [
      { km: 0.0, glyph: "S", name: "Boydtown Beach", cutoff: false },
      { km: 24.38, glyph: "1", name: "Towamba", cutoff: false },
      { km: 51.67, glyph: "2", name: "Rocky Hall", cutoff: false },
      { km: 70.60, glyph: "3", name: "Cathcart", cutoff: true },
      { km: 107.56, glyph: "4", name: "Snowy River Way", cutoff: true },
      { km: 149.21, glyph: "5", name: "Dalgety Bridge", cutoff: true },
      { km: 184.88, glyph: "6", name: "Jindabyne", cutoff: true },
      { km: 213.87, glyph: "7", name: "Perisher Valley", cutoff: false },
      { km: 222.63, glyph: "8", name: "Charlotte Pass", cutoff: true },
      { km: 231.94, glyph: "▲", name: "Mt Kosciuszko", cutoff: false },
      { km: 241.25, glyph: "F", name: "Finish", cutoff: true }
    ];
    profileMilestones = stations;
  }

  function getSurfaceAndPlaceAtKm(km) {
    const isUnsealed = (km >= 51.7 && km <= 63.5) || km >= 222.6;
    const surface = isUnsealed ? "unsealed" : "sealed";
    let nearest = profileMilestones[0];
    let minD = Infinity;
    for (let i = 0; i < profileMilestones.length; i++) {
      const d = Math.abs(profileMilestones[i].km - km);
      if (d < minD) {
        minD = d;
        nearest = profileMilestones[i];
      }
    }
    let placeCtx = "";
    if (minD <= 1.6) {
      placeCtx = "at " + nearest.name;
    } else {
      const ahead = profileMilestones.find(function (s) { return s.km > km + 0.1; }) || profileMilestones[profileMilestones.length - 1];
      const rem = Math.max(0, ahead.km - km);
      placeCtx = rem.toFixed(1) + " km to " + ahead.name;
    }
    return { surface: surface, placeCtx: placeCtx };
  }

  function getProfilePadding(width) {
    const compact = width < 520;
    return {
      compact: compact,
      padL: compact ? 30 : 42,
      padR: compact ? 10 : 18,
      padT: compact ? 19 : 24,
      padB: compact ? 18 : 22
    };
  }

  function formatMobileDefaultSummary() {
    if (!latestHudArgs || !latestHudArgs.runner || !latestHudArgs.crew) return "";
    const runner = latestHudArgs.runner;
    const crew = latestHudArgs.crew;
    const rKm = runner.course_km || 0;
    const bib = (runner.bib && runner.bib !== "C2K") ? runner.bib : "43";
    const sepKm = window.C2KTelemetryClient
      ? window.C2KTelemetryClient.haversineKm(runner.lat, runner.lon, crew.lat, crew.lon)
      : 0;
    return "Jesse #" + bib + " " + rKm.toFixed(1) + "k (" + Math.round(runner.ele_m || 0) + "m) · Gap " + sepKm.toFixed(1) + "k";
  }

  function updateReadoutBarText() {
    const el = document.getElementById("live-readout-strip");

    if (hoverKm !== null && window.C2KTerrainEngine && window.C2KTerrainEngine.getPointAtKm) {
      const pt = window.C2KTerrainEngine.getPointAtKm(hoverKm);
      if (pt) {
        const ele = Math.round(pt[2] || 0);
        const grade = (pt[4] || 0).toFixed(1);
        const gradeStr = (pt[4] > 0 ? "+" : "") + grade + "%";
        const ctx = getSurfaceAndPlaceAtKm(hoverKm);
        if (el) {
          el.textContent =
            hoverKm.toFixed(1) + " km · " + ele + " m · grade " + gradeStr + " · " + ctx.placeCtx + " · " + ctx.surface;
        }
        if (isDraggingProfile && window.innerWidth <= 1024) {
          setText("mob-summary-text", hoverKm.toFixed(1) + "k · " + ele + "m (" + gradeStr + ") · " + ctx.placeCtx);
        }
        return;
      }
    }

    if (el && latestHudArgs && latestHudArgs.runner) {
      const r = latestHudArgs.runner;
      const rKm = r.course_km || 0;
      const bib = (r.bib && r.bib !== "C2K") ? r.bib : "43";
      const gradeStr = (r.grade_pct > 0 ? "+" : "") + (r.grade_pct || 0).toFixed(1) + "%";
      const ctx = getSurfaceAndPlaceAtKm(rKm);
      el.textContent =
        "JESSE #" + bib + " · " + rKm.toFixed(1) + " km · " + Math.round(r.ele_m || 0) + " m · grade " + gradeStr + " · " + ctx.placeCtx + " · " + ctx.surface;
    }
  }

  function bindNextStopRows() {
    const rRow = document.getElementById("r-next-toilet-row");
    if (rRow) {
      rRow.addEventListener("click", function () {
        if (activeRunnerNextStop && window.C2KApp && window.C2KApp.openStopDetailModal) {
          window.C2KApp.openStopDetailModal(activeRunnerNextStop.stop || activeRunnerNextStop);
        }
      });
    }
    const cRow = document.getElementById("c-next-toilet-row");
    if (cRow) {
      cRow.addEventListener("click", function () {
        if (activeCrewNextStop && window.C2KApp && window.C2KApp.openStopDetailModal) {
          window.C2KApp.openStopDetailModal(activeCrewNextStop.stop || activeCrewNextStop);
        }
      });
    }
  }

  function resizeElevationCanvas() {
    if (!eleCanvas || !eleCanvas.parentElement) return;
    const rect = eleCanvas.parentElement.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return;
    cachedW = Math.max(240, rect.width || 600);
    cachedH = Math.max(46, rect.height || 138);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    eleCanvas.width = Math.floor(cachedW * dpr);
    eleCanvas.height = Math.floor(cachedH * dpr);
    if (eleCtx) {
      eleCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  }

  function bindElevationEvents() {
    let lastTouchTapTs = 0;
    let lastTouchTapX = 0;

    function getKmFromPointerEvent(e) {
      const rect = eleCanvas.getBoundingClientRect();
      const pads = getProfilePadding(rect.width || cachedW);
      const plotW = Math.max(10, rect.width - pads.padL - pads.padR);
      const x = e.clientX - rect.left - pads.padL;
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
      updateReadoutBarText();
      drawElevationProfile();
    });

    eleCanvas.addEventListener("pointermove", function (e) {
      hoverKm = getKmFromPointerEvent(e);
      const pt = window.C2KTerrainEngine.getPointAtKm(hoverKm);
      if (pt) {
        window.C2KTerrainEngine.showScrubHoverPin(pt[0], pt[1], true);
      }
      updateReadoutBarText();
      drawElevationProfile();
    });

    function stopDrag(e) {
      isDraggingProfile = false;
      if (e && e.pointerId !== undefined && eleCanvas.releasePointerCapture) {
        try { eleCanvas.releasePointerCapture(e.pointerId); } catch (err) {}
      }
      if (e && e.type === "pointerup" && e.pointerType && e.pointerType !== "mouse") {
        const now = performance.now();
        if (now - lastTouchTapTs < 320 && Math.abs(e.clientX - lastTouchTapX) < 24) {
          const km = getKmFromPointerEvent(e);
          const pt = window.C2KTerrainEngine.getPointAtKm(km);
          if (pt) {
            window.C2KTerrainEngine.flyToCoordinate(pt[0], pt[1], 13.4, 62, pt[5]);
          }
          lastTouchTapTs = 0;
        } else {
          lastTouchTapTs = now;
          lastTouchTapX = e.clientX;
        }
        hoverKm = null;
        window.C2KTerrainEngine.showScrubHoverPin(0, 0, false);
        const summary = formatMobileDefaultSummary();
        if (summary) setText("mob-summary-text", summary);
        updateReadoutBarText();
        drawElevationProfile();
      }
    }

    eleCanvas.addEventListener("pointerup", stopDrag);
    eleCanvas.addEventListener("pointercancel", stopDrag);

    eleCanvas.addEventListener("pointerleave", function () {
      if (!isDraggingProfile) {
        hoverKm = null;
        window.C2KTerrainEngine.showScrubHoverPin(0, 0, false);
        updateReadoutBarText();
        drawElevationProfile();
      }
    });

    eleCanvas.addEventListener("dblclick", function (e) {
      const km = getKmFromPointerEvent(e);
      const pt = window.C2KTerrainEngine.getPointAtKm(km);
      if (pt) {
        window.C2KTerrainEngine.flyToCoordinate(pt[0], pt[1], 13.4, 62, pt[5]);
      }
    });
  }

  function formatPaceMinKm(speedKmh) {
    if (!speedKmh || speedKmh < 0.8) return "--:--";
    const minsPerKm = 60.0 / speedKmh;
    const m = Math.floor(minsPerKm);
    const s = Math.round((minsPerKm - m) * 60);
    if (s === 60) {
      return (m + 1) + ":00";
    }
    return m + ":" + (s < 10 ? "0" + s : s);
  }

  function formatCountdownHMS(hoursFloat) {
    const pad = function (n) { return n < 10 ? "0" + n : String(n); };
    const neg = hoursFloat < 0;
    const totalSecs = Math.round(Math.abs(hoursFloat) * 3600);
    const d = Math.floor(totalSecs / 86400);
    const h = Math.floor((totalSecs % 86400) / 3600);
    const m = Math.floor((totalSecs % 3600) / 60);
    const s = totalSecs % 60;
    const prefix = neg ? "-" : "";
    if (d > 0) {
      return prefix + d + "d " + pad(h) + "h " + pad(m) + "m " + pad(s) + "s";
    }
    return prefix + pad(h) + "h " + pad(m) + "m " + pad(s) + "s";
  }

  function formatShortHM(diffHrs) {
    const absM = Math.round(Math.abs(diffHrs) * 60);
    const h = Math.floor(absM / 60);
    const m = absM % 60;
    const sign = diffHrs >= 0 ? "+" : "-";
    return sign + h + "h " + (m < 10 ? "0" : "") + m + "m";
  }

  function formatClockAEDT(elapsedHours) {
    const pad = function (n) { return n < 10 ? "0" + n : String(n); };
    const clampedH = Math.max(0, elapsedHours);
    const days = ["FRI", "SAT", "SUN"];
    const totalLocalHours = 5.5 + clampedH;
    const dayIdx = Math.min(2, Math.floor(totalLocalHours / 24));
    const clockH = Math.floor(totalLocalHours % 24);
    const clockM = Math.floor((totalLocalHours * 60) % 60);
    return days[dayIdx] + " " + pad(clockH) + ":" + pad(clockM);
  }

  function formatRaceClock(elapsedHours, mode) {
    const pad = function (n) { return n < 10 ? "0" + n : String(n); };
    if (mode === "LIVE" && elapsedHours < 0) {
      const remH = Math.abs(elapsedHours);
      const d = Math.floor(remH / 24);
      const h = Math.floor(remH % 24);
      const m = Math.floor((remH * 60) % 60);
      return "T-" + d + "d " + pad(h) + "h " + pad(m) + "m · FRI NOV 20 05:30";
    }
    const clampedH = Math.max(0, elapsedHours);
    const h = Math.floor(clampedH);
    const m = Math.floor((clampedH - h) * 60);
    return "+" + pad(h) + "h " + pad(m) + "m · " + formatClockAEDT(clampedH);
  }

  function getCutoffSweeperKm(elapsedHours) {
    const pts = [[0.0, 0.0]];
    for (let i = 0; i < cutoffGates.length; i++) {
      pts.push([cutoffGates[i].limitHours, cutoffGates[i].km]);
    }
    if (elapsedHours <= 0) return 0;
    const last = pts[pts.length - 1];
    if (elapsedHours >= last[0]) return last[1];
    for (let i = 1; i < pts.length; i++) {
      if (elapsedHours <= pts[i][0]) {
        const t0 = pts[i - 1][0], k0 = pts[i - 1][1];
        const t1 = pts[i][0], k1 = pts[i][1];
        const frac = t1 > t0 ? (elapsedHours - t0) / (t1 - t0) : 0;
        return k0 + (k1 - k0) * frac;
      }
    }
    return last[1];
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
            '<div class="cutoff-meta">' + g.km.toFixed(1) + ' km · Gate: ' + g.clockLabel + ' (' + g.limitHours + 'h)</div>' +
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
          if (window.innerWidth <= 1024 && window.C2KApp && window.C2KApp.closeMobileSheets) {
            window.C2KApp.closeMobileSheets();
          }
          window.C2KTerrainEngine.flyToCoordinate(lon, lat, 13.4, 62, -30);
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
      badgeEl.textContent = "AWAITING LIVE FIX";
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

  function getNextRunnerStop(rKm) {
    const list = (courseData && courseData.toilets_aid) || [];
    if (!list.length) return null;
    if (rKm <= 0.25) {
      const startWarn = list.find(function (s) { return s.id === "boydtown-no-toilet"; });
      const aid1 = list.find(function (s) { return s.id === "aid-station-1"; });
      if (startWarn) {
        return {
          stop: startWarn,
          targetKm: 0,
          label: "NO TOILETS AT START (Aid #1 @ 3.7k)",
          altStop: aid1
        };
      }
    }
    const candidates = [];
    list.forEach(function (s) {
      if (s.runner_access === false || s.kind === "no_toilet") return;
      if (s.course_km > rKm + 0.05) {
        candidates.push({ stop: s, km: s.course_km, isReturn: false });
      }
      if (s.return_course_km && s.return_course_km > rKm + 0.05) {
        candidates.push({ stop: s, km: s.return_course_km, isReturn: true });
      }
    });
    candidates.sort(function (a, b) { return a.km - b.km; });
    if (!candidates.length) {
      const fin = list.find(function (s) { return s.id === "charlotte-pass-cp8"; }) || list[list.length - 1];
      return { stop: fin, targetKm: fin.return_course_km || fin.course_km, label: fin.shortName + " (Finish)" };
    }
    const best = candidates[0];
    const distAhead = Math.max(0, best.km - rKm);
    const suffix = best.isReturn ? " (Return)" : "";
    return {
      stop: best.stop,
      targetKm: best.km,
      label: best.stop.shortName + suffix + " (+ " + distAhead.toFixed(1) + " km)"
    };
  }

  function getNextCrewStop(cKm, rKm) {
    const list = (courseData && courseData.toilets_aid) || [];
    if (!list.length) return null;
    if (rKm < 24.3) {
      const tow = list.find(function (s) { return s.id === "towamba-cp1"; });
      if (tow) {
        return { stop: tow, targetKm: tow.course_km, label: "Towamba (No crew stops 0-24.4k)" };
      }
    }
    if (rKm >= 222.5) {
      const cp8 = list.find(function (s) { return s.id === "charlotte-pass-cp8"; });
      if (cp8) {
        return { stop: cp8, targetKm: cp8.course_km, label: "Charlotte Pass (Final Vehicle Point)" };
      }
    }
    const refKm = Math.max(rKm, cKm - 0.5);
    const candidates = list.filter(function (s) {
      return s.crew_access !== false && s.kind !== "no_toilet" && s.course_km > refKm + 0.05;
    });
    candidates.sort(function (a, b) { return a.course_km - b.course_km; });
    if (!candidates.length) {
      const cp8 = list.find(function (s) { return s.id === "charlotte-pass-cp8"; });
      return cp8 ? { stop: cp8, targetKm: cp8.course_km, label: "Charlotte Pass Toilet" } : null;
    }
    const best = candidates[0];
    if (best.id === "dalgety-cp5") {
      return { stop: best, targetKm: best.course_km, label: "Dalgety Rear Toilets (50-100m behind Hall)" };
    }
    const dist = Math.max(0, best.course_km - cKm);
    return {
      stop: best,
      targetKm: best.course_km,
      label: best.shortName + " (" + best.course_km.toFixed(1) + "k · " + dist.toFixed(1) + "k)"
    };
  }

  function renderToiletsAidList(rKm) {
    const container = document.getElementById("toilets-aid-list");
    if (!container || !courseData || !Array.isArray(courseData.toilets_aid)) return;
    const nextRunner = getNextRunnerStop(rKm);
    const nextId = nextRunner && nextRunner.stop ? nextRunner.stop.id : "";
    const stateKey = nextId + "|" + Math.floor(rKm * 2);
    if (stateKey === lastRenderedToiletKey && container.children.length) return;
    lastRenderedToiletKey = stateKey;

    let html = "";
    courseData.toilets_aid.forEach(function (stop, idx) {
      const passed = stop.return_course_km
        ? (rKm > stop.return_course_km + 0.2)
        : (stop.id === "boydtown-no-toilet" ? rKm > 0.3 : rKm > stop.course_km + 0.2);
      const isNext = stop.id === nextId;
      const cls = [
        "toilet-stop-item",
        isNext ? "is-next" : "",
        stop.warning_level === "danger" ? "is-danger" : (stop.warning_level === "warn" ? "is-warn" : ""),
        passed ? "is-passed" : ""
      ].filter(Boolean).join(" ");

      const badges = [];
      if (stop.kind === "no_toilet") badges.push('<span class="stop-badge danger">NO TOILETS - PENALTY</span>');
      else if (stop.has_toilet && stop.has_aid) badges.push('<span class="stop-badge ok">Toilet + Aid</span>');
      else if (stop.has_toilet) badges.push('<span class="stop-badge ok">Official Toilet</span>');
      else if (stop.has_aid) badges.push('<span class="stop-badge info">Aid Only</span>');

      if (stop.payment_badge) {
        const bCls = stop.payment_badge.indexOf("CASH") !== -1 ? "warn" : "info";
        badges.push('<span class="stop-badge ' + bCls + '">' + stop.payment_badge + '</span>');
      }
      if (stop.crew_access === false) badges.push('<span class="stop-badge info">Foot Only</span>');
      if (stop.runner_access === false) badges.push('<span class="stop-badge warn">Off Cow Bail</span>');
      if (isNext) badges.push('<span class="stop-badge info">NEXT FOR JESSE #43</span>');

      const kmText = stop.return_course_km
        ? stop.course_km.toFixed(1) + "k / " + stop.return_course_km.toFixed(1) + "k"
        : stop.course_km.toFixed(1) + " km";

      html +=
        '<div class="' + cls + '" data-stop-idx="' + idx + '">' +
          '<div class="ts-top">' +
            '<span class="ts-name">' + stop.name + '</span>' +
            '<span class="ts-km">' + kmText + '</span>' +
          '</div>' +
          '<div class="ts-sub">' + (stop.kind === "no_toilet" ? stop.toilet_rule : stop.food_aid) + '</div>' +
          '<div class="ts-badges">' + badges.join("") + '</div>' +
        '</div>';
    });

    container.innerHTML = html;
    container.querySelectorAll(".toilet-stop-item").forEach(function (el) {
      el.addEventListener("click", function () {
        const idx = parseInt(el.getAttribute("data-stop-idx"), 10);
        const stop = courseData.toilets_aid[idx];
        if (stop && window.C2KApp && window.C2KApp.openStopDetailModal) {
          window.C2KApp.openStopDetailModal(stop);
        }
      });
    });
  }

  let lastDomMode = "";

  function updateHud(runner, crew, elapsedHours, mode, timerTickOnly) {
    if (!runner || !crew || !courseData) return;
    latestHudArgs = { runner: runner, crew: crew, elapsedHours: elapsedHours, mode: mode };

    const now = performance.now();
    if (!timerTickOnly) {
      drawElevationProfile();
    }
    if (!timerTickOnly && mode === "SIM" && lastDomMode === "SIM" && now - lastDomUpdateTs < 150 && !isDraggingProfile) {
      return;
    }
    lastDomUpdateTs = now;
    lastDomMode = mode;

    const totalKm = courseData.meta.total_distance_km || 241.25;

    const clockEl = document.getElementById("sim-clock-readout");
    if (clockEl) {
      clockEl.textContent = formatRaceClock(elapsedHours, mode);
    }
    const sliderEl = document.getElementById("sim-time-slider");
    if (!timerTickOnly && sliderEl && !isDraggingProfile && mode === "SIM") {
      const clampedVal = Math.max(0, Math.min(46, elapsedHours)).toFixed(2);
      sliderEl.value = clampedVal;
      sliderEl.style.setProperty("--control-value", clampedVal);
      sliderEl.setAttribute("aria-valuetext", clampedVal + " hours elapsed");
    }

    const rKm = runner.course_km || 0;
    const remKm = Math.max(0, totalKm - rKm);

    if (!timerTickOnly) {
      setText("r-dist-km", rKm.toFixed(1));
      setText("r-rem-km", remKm.toFixed(1));
      setText("r-ele-m", Math.round(runner.ele_m || 0));
      setText("r-grade-pct", (runner.grade_pct > 0 ? "+" : "") + (runner.grade_pct || 0).toFixed(1) + "%");
      setText("r-speed-kmh", (runner.speed_kmh || 0).toFixed(1));
      setText("r-pace", formatPaceMinKm(runner.speed_kmh));
      setText("r-note", runner.note || "");

      const rBat = runner.battery_pct !== undefined ? " · Bat " + runner.battery_pct + "%" : "";
      const rAge = runner.fix_age_text ? " · " + runner.fix_age_text : "";
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
          nextCp.name.replace("Mandatory Checkpoint ", "CP") + " (" + distToCp.toFixed(1) + " km · ~" + etaStr + ")"
        );
      }

      activeRunnerNextStop = getNextRunnerStop(rKm);
      if (activeRunnerNextStop) {
        setText("r-next-toilet", activeRunnerNextStop.label);
      }

      const sepKm = window.C2KTelemetryClient.haversineKm(runner.lat, runner.lon, crew.lat, crew.lon);
      setText("c-course-km", (crew.course_km || 0).toFixed(1));
      setText("c-ele-m", Math.round(crew.ele_m || 0));
      setText("c-sep-km", sepKm.toFixed(2));
      setText("c-speed-kmh", Math.round(crew.speed_kmh || 0));
      setText("c-note", crew.note || "");
      setText("c-fix-age", (crew.source || "Crew") + " · " + (crew.fix_age_text || "Ready"));

      activeCrewNextStop = getNextCrewStop(crew.course_km || 0, rKm);
      if (activeCrewNextStop) {
        setText("c-next-toilet", activeCrewNextStop.label);
      }

      const rBib = (runner.bib && runner.bib !== "C2K") ? runner.bib : "43";
      setText("r-runner-name", (runner.name || "Jesse Simon").toUpperCase());
      setText("r-runner-bib", "BIB #" + rBib + " · C2K");
      setText("strip-simon-summary", "Jesse #" + rBib + " · " + rKm.toFixed(1) + " km · " + Math.round(runner.ele_m || 0) + "m");
      setText("strip-crew-summary", "Crew · " + (crew.course_km || 0).toFixed(1) + " km (Gap " + sepKm.toFixed(1) + "k)");
      if (!(isDraggingProfile && hoverKm !== null)) {
        setText("mob-summary-text", "Jesse #" + rBib + " " + rKm.toFixed(1) + "k (" + Math.round(runner.ele_m || 0) + "m) · Gap " + sepKm.toFixed(1) + "k");
      }

      updateReadoutBarText();
      renderToiletsAidList(rKm);
    }

    updateCutoffGatesInPlace(rKm, elapsedHours, runner.speed_kmh || 6.2, mode);
  }

  function updateCutoffGatesInPlace(currentKm, rawElapsedHours, currentSpeedKmh, mode) {
    const isPreRace = mode === "LIVE" && rawElapsedHours < 0;
    const elapsedHours = Math.max(0, rawElapsedHours);
    const targetBaselineHrs = (window.C2KTelemetryClient && window.C2KTelemetryClient.getTargetFinishHours)
      ? window.C2KTelemetryClient.getTargetFinishHours()
      : 38.5;

    const eCurrent = getEffortAtKm(currentKm);
    const baseHrsPerEffort = targetBaselineHrs / totalEffortUnits;
    let effHrsPerEffort = baseHrsPerEffort;
    if (!isPreRace && elapsedHours > 0.25 && currentKm >= 1.0) {
      const actualHrsPerEffort = elapsedHours / Math.max(0.5, eCurrent);
      const blend = Math.min(1.0, eCurrent / 15.0);
      effHrsPerEffort = baseHrsPerEffort * (1.0 - blend) + actualHrsPerEffort * blend;
    }

    const splits = (window.C2KTelemetryClient && window.C2KTelemetryClient.getGateSplits)
      ? window.C2KTelemetryClient.getGateSplits()
      : {};

    let activeGate = null;
    let activeProjMargin = 0;
    let activeTimeLeft = 0;

    for (let i = 0; i < cutoffGates.length; i++) {
      const g = cutoffGates[i];
      const lockedSplit = splits[g.id];
      const passed = !isPreRace && (currentKm >= g.km - 0.05 || lockedSplit !== undefined);
      const isActive = !passed && activeGate === null;
      if (isActive) activeGate = g;

      const eGate = getEffortAtKm(g.km);
      const projArrivalHrs = isPreRace
        ? eGate * baseHrsPerEffort
        : elapsedHours + Math.max(0, eGate - eCurrent) * effHrsPerEffort;

      let marginHours = g.limitHours - projArrivalHrs;
      let statusText = formatShortHM(marginHours) + " buf";

      if (passed) {
        const actualHrs = lockedSplit ? lockedSplit.elapsedHours : projArrivalHrs;
        marginHours = g.limitHours - actualHrs;
        const prefix = marginHours >= 0 ? "CLEARED " : "LATE ";
        statusText = prefix + formatShortHM(marginHours);
      }

      if (isActive) {
        activeProjMargin = marginHours;
        activeTimeLeft = isPreRace ? g.limitHours : (g.limitHours - elapsedHours);
      }

      const marginClass = marginHours >= 1.0 ? "positive" : marginHours >= 0 ? "tight" : "danger";
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

    const heroEl = document.getElementById("cutoff-hero-card");
    const alertEl = document.getElementById("cutoff-alert-banner");
    const pillSummary = document.getElementById("pill-cutoff-summary");
    if (!heroEl) return;

    if (isPreRace) {
      const g0 = cutoffGates[0];
      const reqSpeed = g0.km / g0.limitHours;
      heroEl.className = "cutoff-hero-card";
      heroEl.innerHTML =
        '<div class="cutoff-hero-top">' +
          '<strong>NEXT: ' + g0.shortName + ' (' + g0.clockLabel + ')</strong>' +
          '<span>RACE STARTS IN</span>' +
        '</div>' +
        '<div class="cutoff-countdown-big">' +
          '<span>T-' + formatCountdownHMS(Math.abs(rawElapsedHours)) + '</span>' +
          '<span class="cutoff-countdown-sub">Window: 12h 00m</span>' +
        '</div>' +
        '<div class="cutoff-req-row">' +
          '<span>Need &le; ' + formatPaceMinKm(reqSpeed) + '/km (' + reqSpeed.toFixed(1) + ' km/h)</span>' +
          '<span class="cutoff-margin positive">Target ' + formatShortHM(g0.limitHours - getEffortAtKm(g0.km) * baseHrsPerEffort) + '</span>' +
        '</div>';
      if (alertEl) alertEl.hidden = true;
      if (pillSummary) {
        pillSummary.className = "pill-mini-badge";
        const absH = Math.abs(rawElapsedHours);
        const days = Math.floor(absH / 24);
        const hrs = Math.floor(absH % 24);
        pillSummary.textContent = "T-" + days + "d " + hrs + "h";
      }
      return;
    }

    if (!activeGate) {
      heroEl.className = "cutoff-hero-card";
      heroEl.innerHTML =
        '<div class="cutoff-hero-top"><strong>ALL 6 CUT-OFF GATES CLEARED!</strong><span>241.25 KM</span></div>' +
        '<div class="cutoff-countdown-big"><span>FINISHED</span><span class="cutoff-countdown-sub">' + formatClockAEDT(elapsedHours) + '</span></div>';
      if (alertEl) alertEl.hidden = true;
      if (pillSummary) {
        pillSummary.className = "pill-mini-badge";
        pillSummary.textContent = "All 6 OK";
      }
      return;
    }

    const remGateKm = Math.max(0, activeGate.km - currentKm);
    const reqSpeed = activeTimeLeft > 0.01 ? (remGateKm / activeTimeLeft) : 99.9;
    const reqPaceText = activeTimeLeft > 0.01
      ? "Need &le; " + formatPaceMinKm(reqSpeed) + "/km (" + reqSpeed.toFixed(1) + " km/h)"
      : "GATE CLOSED";

    const isDanger = activeTimeLeft <= 0 || activeProjMargin < 0;
    const isTight = !isDanger && (activeProjMargin < 1.0 || activeTimeLeft < 1.0);
    const heroCls = isDanger ? "is-danger" : isTight ? "is-tight" : "";
    const bufCls = activeProjMargin >= 1.0 ? "positive" : activeProjMargin >= 0 ? "tight" : "danger";

    if (pillSummary) {
      pillSummary.className = "pill-mini-badge" + (isDanger ? " is-danger" : isTight ? " is-tight" : "");
      pillSummary.textContent = activeGate.shortName.split(" ")[0] + " " + formatShortHM(activeProjMargin);
    }

    heroEl.className = "cutoff-hero-card " + heroCls;
    heroEl.innerHTML =
      '<div class="cutoff-hero-top">' +
        '<strong>NEXT: ' + activeGate.shortName + ' (' + activeGate.clockLabel + ')</strong>' +
        '<span>' + remGateKm.toFixed(1) + ' km left</span>' +
      '</div>' +
      '<div class="cutoff-countdown-big">' +
        '<span>' + (activeTimeLeft >= 0 ? formatCountdownHMS(activeTimeLeft) + ' left' : 'CLOSED ' + formatCountdownHMS(activeTimeLeft)) + '</span>' +
        '<span class="cutoff-countdown-sub">Gate ' + activeGate.limitHours + 'h</span>' +
      '</div>' +
      '<div class="cutoff-req-row">' +
        '<span>' + reqPaceText + '</span>' +
        '<span class="cutoff-margin ' + bufCls + '">' + formatShortHM(activeProjMargin) + ' buf</span>' +
      '</div>';

    if (alertEl) {
      if (isDanger) {
        alertEl.hidden = false;
        alertEl.className = "cutoff-alert-banner is-danger";
        alertEl.textContent = activeTimeLeft <= 0
          ? "CUT-OFF CLOSED: Past " + activeGate.shortName + " (" + activeGate.clockLabel + ") limit."
          : "CUT-OFF ALERT: Projected " + formatShortHM(activeProjMargin) + " behind " + activeGate.shortName + " (" + activeGate.clockLabel + ") - need " + formatPaceMinKm(reqSpeed) + "/km.";
      } else if (isTight) {
        alertEl.hidden = false;
        alertEl.className = "cutoff-alert-banner is-tight";
        const cushion = Math.min(activeProjMargin, activeTimeLeft);
        alertEl.textContent = "TIGHT CUT-OFF: Only " + formatShortHM(cushion).replace("+", "") + " cushion to " + activeGate.shortName + " (" + activeGate.clockLabel + ").";
      } else {
        alertEl.hidden = true;
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
            '<span class="wz-name">' + z.name + ' <span style="opacity:0.65;font-weight:400;">(' + z.ele_m + 'm)</span></span>' +
            '<span class="wz-sub">' + (w.conditions || "Partly Cloudy") + ' · Clouds ' + clouds + '%</span>' +
          '</div>' +
          '<div class="wz-right">' +
            '<div class="wz-temp">' + temp + '°C</div>' +
            '<div class="wz-wind">' + wind + ' km/h (' + dir + '°)</div>' +
          '</div>' +
        '</div>';
    });

    container.innerHTML = html;
    container.querySelectorAll(".weather-zone-item").forEach(function (item) {
      item.addEventListener("click", function () {
        const lon = parseFloat(item.getAttribute("data-lon"));
        const lat = parseFloat(item.getAttribute("data-lat"));
        if (window.innerWidth <= 1024 && window.C2KApp && window.C2KApp.closeMobileSheets) {
          window.C2KApp.closeMobileSheets();
        }
        window.C2KTerrainEngine.flyToCoordinate(lon, lat, 12.4, 62, -35);
      });
    });
  }

  function drawElevationProfile() {
    if (!eleCtx || !eleCanvas || !courseData || !courseData.track) return;
    const w = cachedW;
    const h = cachedH;
    eleCtx.clearRect(0, 0, w, h);

    const pads = getProfilePadding(w);
    const padL = pads.padL;
    const padR = pads.padR;
    const padT = pads.padT;
    const padB = pads.padB;
    const plotW = Math.max(10, w - padL - padR);
    const plotH = Math.max(10, h - padT - padB);

    const totalKm = courseData.meta.total_distance_km || 241.25;
    const maxEle = 2300.0;
    const track = courseData.track;

    const xOfKm = function (km) { return padL + (km / totalKm) * plotW; };
    const yOfEle = function (ele) { return padT + plotH - (Math.max(0, ele) / maxEle) * plotH; };

    // Subtle elevation gridlines
    eleCtx.font = pads.compact ? "600 8.5px 'JetBrains Mono', monospace" : "600 9.5px 'JetBrains Mono', monospace";
    eleCtx.lineWidth = 1;
    [0, 500, 1000, 1500, 2000].forEach(function (elev) {
      const y = yOfEle(elev);
      eleCtx.strokeStyle = elev === 0 ? "rgba(148, 163, 184, 0.18)" : "rgba(148, 163, 184, 0.07)";
      eleCtx.beginPath();
      eleCtx.moveTo(padL, y);
      eleCtx.lineTo(padL + plotW, y);
      eleCtx.stroke();
      if (elev === 0 || elev === 1000 || elev === 2000) {
        eleCtx.fillStyle = "rgba(148, 163, 184, 0.85)";
        const lbl = pads.compact
          ? (elev === 0 ? "0m" : (elev / 1000) + "k")
          : (elev === 0 ? "0 m" : elev.toLocaleString("en-AU"));
        eleCtx.fillText(lbl, pads.compact ? 2 : 4, y + 3);
      }
    });

    // Dark Broadcast Mountain Profile Area Gradient (Summit Gold -> Deep Sea Navy)
    const hypsGrad = eleCtx.createLinearGradient(0, yOfEle(2300), 0, yOfEle(0));
    hypsGrad.addColorStop(0.0, "rgba(251, 191, 36, 0.44)");
    hypsGrad.addColorStop(0.32, "rgba(56, 189, 248, 0.24)");
    hypsGrad.addColorStop(0.68, "rgba(30, 58, 95, 0.34)");
    hypsGrad.addColorStop(1.0, "rgba(15, 23, 42, 0.14)");

    eleCtx.fillStyle = hypsGrad;
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

    // Main route profile curve (Golden Amber #fbbf24)
    eleCtx.strokeStyle = "#fbbf24";
    eleCtx.lineWidth = 1.9;
    eleCtx.beginPath();
    for (let i = 0; i < track.length; i += 3) {
      const x = xOfKm(track[i][3]);
      const y = yOfEle(track[i][2]);
      if (i === 0) eleCtx.moveTo(x, y);
      else eleCtx.lineTo(x, y);
    }
    eleCtx.stroke();

    if (rKm > 0.2) {
      // Completed route stroke (Blaze Orange #ff5a1f)
      eleCtx.strokeStyle = "#ff5a1f";
      eleCtx.lineWidth = 2.6;
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

    // Sealed vs Unsealed surface baseline track
    const baseY = padT + plotH + 4;
    eleCtx.lineWidth = 1.6;
    eleCtx.strokeStyle = "rgba(148, 163, 184, 0.38)";
    eleCtx.beginPath();
    eleCtx.moveTo(xOfKm(0), baseY);
    eleCtx.lineTo(xOfKm(totalKm), baseY);
    eleCtx.stroke();

    eleCtx.fillStyle = "#fef3c7";
    [[51.7, 63.5], [222.6, 241.25]].forEach(function (seg) {
      const sx0 = xOfKm(seg[0]);
      const sx1 = xOfKm(seg[1]);
      for (let px = sx0; px <= sx1; px += 4) {
        eleCtx.beginPath();
        eleCtx.arc(px, baseY, 1.3, 0, Math.PI * 2);
        eleCtx.fill();
      }
    });

    // Bottom KM tick labels
    const kmStep = w < 540 ? 40 : 20;
    eleCtx.fillStyle = "rgba(148, 163, 184, 0.85)";
    eleCtx.font = "500 9.5px 'JetBrains Mono', monospace";
    for (let k = 0; k <= 240; k += kmStep) {
      const tx = xOfKm(k);
      eleCtx.fillText(k === 0 ? "0 km" : String(k), tx - (k === 0 ? 4 : 8), padT + plotH + 16);
    }

    // Checkpoint top medallions + vertical dashed lines
    let lastDrawnX = -99;
    PROFILE_STATIONS.forEach(function (st) {
      const sx = xOfKm(st.km);
      eleCtx.save();
      eleCtx.setLineDash([2, 3]);
      eleCtx.strokeStyle = st.cutoff ? "rgba(251, 191, 36, 0.36)" : "rgba(56, 189, 248, 0.2)";
      eleCtx.lineWidth = 1;
      eleCtx.beginPath();
      eleCtx.moveTo(sx, 11);
      eleCtx.lineTo(sx, padT + plotH);
      eleCtx.stroke();
      eleCtx.restore();

      if (sx - lastDrawnX < 14 && st.glyph === "7") return;
      lastDrawnX = sx;

      eleCtx.fillStyle = "#0f172a";
      eleCtx.beginPath();
      eleCtx.arc(sx, 11, 7.5, 0, Math.PI * 2);
      eleCtx.fill();

      eleCtx.strokeStyle = st.cutoff ? "#fbbf24" : "#94a3b8";
      eleCtx.lineWidth = st.cutoff ? 1.8 : 1.2;
      eleCtx.stroke();

      eleCtx.fillStyle = st.cutoff ? "#fef08a" : "#f8fafc";
      eleCtx.font = "700 9.5px 'Chakra Petch', sans-serif";
      eleCtx.textAlign = "center";
      eleCtx.textBaseline = "middle";
      eleCtx.fillText(st.glyph, sx, 11.5);
    });
    eleCtx.textAlign = "left";
    eleCtx.textBaseline = "alphabetic";

    // Mountain peak callouts
    if (w >= 460) {
      eleCtx.font = "700 10px 'Chakra Petch', sans-serif";
      eleCtx.fillStyle = "rgba(226, 232, 240, 0.85)";
      eleCtx.fillText("BIG JACK", xOfKm(56) - 18, yOfEle(940));
      eleCtx.fillText("BELOKA HILL", xOfKm(164) - 24, yOfEle(1290));
      eleCtx.fillStyle = "#fde68a";
      eleCtx.textAlign = "right";
      eleCtx.fillText("MT KOSCIUSZKO 2,228 M", xOfKm(228.5), yOfEle(2120));
      eleCtx.textAlign = "left";
    }

    // Optional Toilets & Aid ticks on Elevation Profile when 3D Pins ON
    if (window.C2KTerrainEngine && window.C2KTerrainEngine.isToiletsVisible && window.C2KTerrainEngine.isToiletsVisible()) {
      (courseData.toilets_aid || []).forEach(function (stop) {
        const passes = [stop.course_km];
        if (stop.return_course_km) passes.push(stop.return_course_km);
        passes.forEach(function (km) {
          const sx = xOfKm(km);
          const sPt = window.C2KTerrainEngine.getPointAtKm(km);
          const sy = yOfEle(sPt ? sPt[2] : stop.ele_m);
          const col = stop.kind === "no_toilet" ? "#f43f5e" : stop.kind === "aid_only" ? "#38bdf8" : stop.warning_level === "warn" ? "#f59e0b" : "#22c55e";
          eleCtx.strokeStyle = col;
          eleCtx.lineWidth = 1.2;
          eleCtx.beginPath();
          eleCtx.moveTo(sx, sy - 8);
          eleCtx.lineTo(sx, sy);
          eleCtx.stroke();
          eleCtx.fillStyle = col;
          eleCtx.beginPath();
          eleCtx.arc(sx, sy - 8, 2.8, 0, Math.PI * 2);
          eleCtx.fill();
        });
      });
    }

    // Moving 46h Cut-Off Sweeper Wave marker
    const elapsedHrs = window.C2KTelemetryClient ? window.C2KTelemetryClient.getSimElapsedHours() : 0;
    if (elapsedHrs >= 0) {
      const swKm = getCutoffSweeperKm(elapsedHrs);
      const swX = xOfKm(swKm);
      const swPt = window.C2KTerrainEngine ? window.C2KTerrainEngine.getPointAtKm(swKm) : null;
      const swY = yOfEle(swPt ? swPt[2] : 0);

      eleCtx.save();
      eleCtx.strokeStyle = "rgba(244, 63, 94, 0.85)";
      eleCtx.lineWidth = 1.5;
      eleCtx.setLineDash([4, 3]);
      eleCtx.beginPath();
      eleCtx.moveTo(swX, padT);
      eleCtx.lineTo(swX, padT + plotH);
      eleCtx.stroke();
      eleCtx.restore();

      eleCtx.fillStyle = "#f43f5e";
      eleCtx.beginPath();
      eleCtx.arc(swX, swY, 4.2, 0, Math.PI * 2);
      eleCtx.fill();
      eleCtx.strokeStyle = "#ffffff";
      eleCtx.lineWidth = 1.2;
      eleCtx.stroke();

      eleCtx.fillStyle = "#fecdd3";
      eleCtx.font = "700 9px 'JetBrains Mono', monospace";
      const gapKm = rKm - swKm;
      const swTag = "CUT-OFF (" + (gapKm >= 0 ? "+" : "") + gapKm.toFixed(1) + "k)";
      const tagW = eleCtx.measureText(swTag).width;
      const tagX = Math.min(w - tagW - 4, Math.max(padL, swX - tagW / 2));
      eleCtx.fillText(swTag, tagX, padT + 9);
    }

    const crew = window.C2KTelemetryClient ? window.C2KTelemetryClient.getCrewState() : null;
    if (crew) {
      const cx = xOfKm(crew.course_km || 0);
      const cy = yOfEle(crew.ele_m || 0);
      eleCtx.fillStyle = "#00e5ff";
      eleCtx.beginPath();
      eleCtx.arc(cx, cy, 4.2, 0, Math.PI * 2);
      eleCtx.fill();
    }

    if (runner) {
      const rx = xOfKm(rKm);
      const ry = yOfEle(runner.ele_m || 0);
      eleCtx.strokeStyle = "rgba(255, 90, 31, 0.78)";
      eleCtx.lineWidth = 1.5;
      eleCtx.beginPath();
      eleCtx.moveTo(rx, padT);
      eleCtx.lineTo(rx, padT + plotH);
      eleCtx.stroke();

      eleCtx.fillStyle = "#ff5a1f";
      eleCtx.beginPath();
      eleCtx.arc(rx, ry, 5.5, 0, Math.PI * 2);
      eleCtx.fill();
      eleCtx.strokeStyle = "#ffffff";
      eleCtx.lineWidth = 1.8;
      eleCtx.stroke();
    }

    if (hoverKm !== null) {
      const hx = xOfKm(hoverKm);
      const hPt = window.C2KTerrainEngine.getPointAtKm(hoverKm);
      const hEle = hPt ? Math.round(hPt[2]) : 0;
      const hGrade = hPt ? hPt[4].toFixed(1) : "0.0";
      const hy = yOfEle(hEle);

      eleCtx.strokeStyle = "rgba(255, 255, 255, 0.85)";
      eleCtx.lineWidth = 1.2;
      eleCtx.beginPath();
      eleCtx.moveTo(hx, padT);
      eleCtx.lineTo(hx, padT + plotH);
      eleCtx.stroke();

      eleCtx.fillStyle = "#fbbf24";
      eleCtx.beginPath();
      eleCtx.arc(hx, hy, 4.5, 0, Math.PI * 2);
      eleCtx.fill();
      eleCtx.strokeStyle = "#ffffff";
      eleCtx.lineWidth = 1.5;
      eleCtx.stroke();

      eleCtx.font = "700 9.5px 'JetBrains Mono', monospace";
      const tipText = hoverKm.toFixed(1) + " km · " + hEle + "m (" + (hGrade > 0 ? "+" : "") + hGrade + "%)";
      const tw = eleCtx.measureText(tipText).width + 12;
      const tx = Math.min(w - tw - 6, Math.max(padL, hx - tw / 2));
      eleCtx.fillStyle = "rgba(12, 18, 30, 0.94)";
      eleCtx.fillRect(tx, 2, tw, 16);
      eleCtx.strokeStyle = "#ff5a1f";
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
