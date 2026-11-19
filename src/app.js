/**
 * Coast to Kosciuszko (C2K) - Main Application Orchestrator
 */

window.C2KApp = (function () {
  let courseData = null;
  let activeLocMethod = "checkpoint";
  let parsedGpxPoints = [];
  let closeMobileSheetsFn = null;

  function syncSliderCssVars(slider) {
    if (!slider) return;
    slider.style.setProperty("--attr-min", slider.min || 0);
    slider.style.setProperty("--attr-max", slider.max || 100);
    slider.style.setProperty("--control-value", slider.value || 0);
  }

  function attachDialogLightDismiss(dialogEl, onDismissCb) {
    if (!dialogEl || "closedBy" in HTMLDialogElement.prototype) return;
    let downOutside = false;
    dialogEl.addEventListener("pointerdown", function (e) {
      if (e.target !== dialogEl) {
        downOutside = false;
        return;
      }
      const rect = dialogEl.getBoundingClientRect();
      downOutside =
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom;
    });
    dialogEl.addEventListener("pointerup", function (e) {
      if (!downOutside || e.target !== dialogEl) return;
      const rect = dialogEl.getBoundingClientRect();
      const upOutside =
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom;
      downOutside = false;
      if (upOutside) {
        if (onDismissCb) onDismissCb();
        else if (typeof dialogEl.close === "function" && dialogEl.open) dialogEl.close("dismiss");
        else dialogEl.removeAttribute("open");
      }
    });
  }

  function boot() {
    courseData = window.C2K_COURSE_DATA;
    if (!courseData) {
      console.error("[C2K] Missing window.C2K_COURSE_DATA bundle.");
      return;
    }

    window.C2KBroadcastHud.init(courseData);
    window.C2KWeatherClouds3D.init("atmosphere-canvas", courseData.weather_zones || []);
    bindUiControls();
    populateCheckpointSelect();

    let telemetryStarted = false;
    let urlCamApplied = false;
    let requestedUrlCam = "";
    try {
      const q = new URLSearchParams(window.location.search || "");
      const camParam = (q.get("cam") || "").toLowerCase();
      if (camParam === "crew") requestedUrlCam = "follow-crew";
      else if (camParam === "jesse" || camParam === "simon" || camParam === "runner") requestedUrlCam = "follow-simon";
      else if (camParam === "dual") requestedUrlCam = "dual-frame";
    } catch (e) {}

    function startTelemetryFeed() {
      if (telemetryStarted) return;
      telemetryStarted = true;
      window.C2KTelemetryClient.init(courseData, function (runner, crew, elapsedHours, mode) {
        if (window.C2KTerrainEngine && window.C2KTerrainEngine.updateEntities) {
          window.C2KTerrainEngine.updateEntities(runner, crew);
        }
        if (window.C2KTerrainEngine && window.C2KTerrainEngine.updateLiveTrail && window.C2KTelemetryClient.getLiveTrail) {
          window.C2KTerrainEngine.updateLiveTrail(window.C2KTelemetryClient.getLiveTrail());
        }
        window.C2KBroadcastHud.updateHud(runner, crew, elapsedHours, mode);

        if (!urlCamApplied && requestedUrlCam && window.C2KTerrainEngine && window.C2KTerrainEngine.setCameraMode) {
          const hasLiveCloud = mode !== "LIVE" || !!(window.C2KTelemetryClient && window.C2KTelemetryClient.getLastCloudState && window.C2KTelemetryClient.getLastCloudState());
          if (hasLiveCloud) {
            urlCamApplied = true;
            window.C2KTerrainEngine.setCameraMode(requestedUrlCam);
          }
        }
      });
    }

    try {
      window.C2KTerrainEngine.init("map-container", courseData, startTelemetryFeed);
    } catch (err) {
      console.error("[C2K] 3D map init warning - continuing in HUD telemetry mode:", err);
      startTelemetryFeed();
    }
  }

  function parseGpxXmlClient(xmlText) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlText, "application/xml");
    const parseErr = doc.querySelector("parsererror");
    if (parseErr) {
      throw new Error("Invalid GPX XML file.");
    }
    const trkpts = doc.getElementsByTagNameNS("*", "trkpt");
    const fallbackPts = trkpts.length ? trkpts : doc.getElementsByTagName("trkpt");
    const points = [];
    for (let i = 0; i < fallbackPts.length; i++) {
      const node = fallbackPts[i];
      const lat = parseFloat(node.getAttribute("lat"));
      const lon = parseFloat(node.getAttribute("lon"));
      if (isNaN(lat) || isNaN(lon)) continue;
      const eleNode = node.getElementsByTagName("ele")[0] || node.getElementsByTagNameNS("*", "ele")[0];
      const timeNode = node.getElementsByTagName("time")[0] || node.getElementsByTagNameNS("*", "time")[0];
      const spdNode = node.getElementsByTagNameNS("*", "speed")[0] || node.getElementsByTagName("speed")[0];
      const eleVal = eleNode && eleNode.textContent ? parseFloat(eleNode.textContent.trim()) : undefined;
      const spdVal = spdNode && spdNode.textContent ? parseFloat(spdNode.textContent.trim()) : undefined;
      const timeStr = timeNode && timeNode.textContent ? timeNode.textContent.trim() : undefined;
      points.push({
        lat: Number(lat.toFixed(6)),
        lon: Number(lon.toFixed(6)),
        ele: eleVal !== undefined && !isNaN(eleVal) ? Number(eleVal.toFixed(1)) : undefined,
        time: timeStr,
        spd: spdVal !== undefined && !isNaN(spdVal) ? Number(spdVal.toFixed(3)) : null
      });
    }
    for (let j = 0; j < points.length; j++) {
      const curr = points[j];
      if (curr.spd === null && j > 0 && window.C2KTelemetryClient && window.C2KTelemetryClient.haversineKm) {
        const prev = points[j - 1];
        const tCurr = curr.time ? Date.parse(curr.time) : NaN;
        const tPrev = prev.time ? Date.parse(prev.time) : NaN;
        if (!isNaN(tCurr) && !isNaN(tPrev)) {
          const dtSec = (tCurr - tPrev) / 1000.0;
          if (dtSec >= 3.0 && dtSec <= 900.0) {
            const distM = window.C2KTelemetryClient.haversineKm(prev.lat, prev.lon, curr.lat, curr.lon) * 1000.0;
            curr.spd = Number(Math.min(45.0, distM / dtSec).toFixed(3));
          }
        }
      }
      if (curr.spd === null) {
        curr.spd = 0;
      }
    }
    return points;
  }

  function bindUiControls() {
    // Collapsible Side Broadcast Docks + Keyboard 'H' Clean Map Toggle
    let leftCollapsed = false;
    let rightCollapsed = false;
    const leftDockEl = document.getElementById("left-telemetry-dock");
    const rightDockEl = document.getElementById("right-broadcast-dock");
    const leftExpandWrap = document.getElementById("dock-expand-left-wrap");
    const rightExpandWrap = document.getElementById("dock-expand-right-wrap");
    const btnCollapseLeft = document.getElementById("btn-collapse-left-dock");
    const btnExpandLeft = document.getElementById("btn-expand-left-dock");
    const btnCollapseRight = document.getElementById("btn-collapse-right-dock");
    const btnExpandRight = document.getElementById("btn-expand-right-dock");
    const btnToggleAllHud = document.getElementById("btn-toggle-all-hud");

    function applyDockStates() {
      const isDesktop = window.innerWidth > 1024;
      document.body.classList.toggle("left-dock-collapsed", leftCollapsed);
      document.body.classList.toggle("right-dock-collapsed", rightCollapsed);

      if (leftExpandWrap) leftExpandWrap.hidden = !leftCollapsed;
      if (rightExpandWrap) rightExpandWrap.hidden = !rightCollapsed;

      if (leftDockEl) leftDockEl.inert = isDesktop && leftCollapsed;
      if (rightDockEl) rightDockEl.inert = isDesktop && rightCollapsed;

      if (btnCollapseLeft) btnCollapseLeft.setAttribute("aria-expanded", leftCollapsed ? "false" : "true");
      if (btnExpandLeft) btnExpandLeft.setAttribute("aria-expanded", leftCollapsed ? "false" : "true");
      if (btnCollapseRight) btnCollapseRight.setAttribute("aria-expanded", rightCollapsed ? "false" : "true");
      if (btnExpandRight) btnExpandRight.setAttribute("aria-expanded", rightCollapsed ? "false" : "true");

      if (btnToggleAllHud) {
        const bothHidden = leftCollapsed && rightCollapsed;
        btnToggleAllHud.textContent = bothHidden ? "Show Docks" : "Hide Docks";
        btnToggleAllHud.setAttribute("aria-pressed", bothHidden ? "true" : "false");
        btnToggleAllHud.classList.toggle("active", bothHidden);
      }
    }

    if (btnCollapseLeft) {
      btnCollapseLeft.addEventListener("click", function () {
        leftCollapsed = true;
        applyDockStates();
        if (btnExpandLeft) btnExpandLeft.focus();
      });
    }
    if (btnExpandLeft) {
      btnExpandLeft.addEventListener("click", function () {
        leftCollapsed = false;
        applyDockStates();
      });
    }
    if (btnCollapseRight) {
      btnCollapseRight.addEventListener("click", function () {
        rightCollapsed = true;
        applyDockStates();
        if (btnExpandRight) btnExpandRight.focus();
      });
    }
    if (btnExpandRight) {
      btnExpandRight.addEventListener("click", function () {
        rightCollapsed = false;
        applyDockStates();
      });
    }
    if (btnToggleAllHud) {
      btnToggleAllHud.addEventListener("click", function () {
        const nextHidden = !(leftCollapsed && rightCollapsed);
        leftCollapsed = nextHidden;
        rightCollapsed = nextHidden;
        applyDockStates();
      });
    }

    window.addEventListener("resize", applyDockStates);
    window.addEventListener("keydown", function (e) {
      if (e.key === "h" || e.key === "H") {
        const tag = (e.target && e.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        const checkinOpen = document.getElementById("crew-checkin-modal")?.open;
        const stopOpen = document.getElementById("stop-detail-modal")?.open;
        if (checkinOpen || stopOpen) return;
        const nextHidden = !(leftCollapsed && rightCollapsed);
        leftCollapsed = nextHidden;
        rightCollapsed = nextHidden;
        applyDockStates();
      }
    });

    const hybridBadgeBtn = document.getElementById("hybrid-engine-badge");
    if (hybridBadgeBtn) {
      hybridBadgeBtn.addEventListener("click", function () {
        if (window.C2KTerrainEngine && window.C2KTerrainEngine.toggleHybridEngine) {
          window.C2KTerrainEngine.toggleHybridEngine();
        }
      });
    }

    // Dynamic Mobile Chrome Height Observer (prevents overlap at any font/pointer scale)
    const topBarEl = document.querySelector(".top-broadcast-bar");
    const mobCrewBarEl = document.getElementById("mobile-crew-bar");
    const bottomDockEl = document.getElementById("bottom-broadcast-dock");
    const mobRightTitleEl = document.getElementById("mobile-right-sheet-title");
    const btnMobToggleProfile = document.getElementById("btn-mob-toggle-profile");

    function syncMobileChromeMetrics() {
      const rootStyle = document.documentElement.style;
      if (topBarEl) {
        const h = Math.round(topBarEl.getBoundingClientRect().height);
        if (h > 0) rootStyle.setProperty("--mob-top-bar-h", h + "px");
      }
      if (mobCrewBarEl) {
        const h = Math.round(mobCrewBarEl.getBoundingClientRect().height);
        if (h > 0) rootStyle.setProperty("--mob-crew-bar-h", h + "px");
      }
      if (bottomDockEl) {
        const h = Math.round(bottomDockEl.getBoundingClientRect().height);
        if (h > 0) rootStyle.setProperty("--mob-bottom-dock-h", h + "px");
      }
      if (rightDockEl && document.body.getAttribute("data-mobile-sheet") === "cams") {
        const h = Math.round(rightDockEl.getBoundingClientRect().height);
        if (h > 0) rootStyle.setProperty("--mob-cams-dock-h", h + "px");
      }
    }

    if (typeof ResizeObserver === "function") {
      const ro = new ResizeObserver(function () {
        syncMobileChromeMetrics();
      });
      [topBarEl, mobCrewBarEl, bottomDockEl, rightDockEl].forEach(function (el) {
        if (el) ro.observe(el);
      });
    }
    window.addEventListener("resize", syncMobileChromeMetrics);
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", syncMobileChromeMetrics);
    }

    function setMobileSheet(nextSheet) {
      const sheet = nextSheet || "map";
      document.body.setAttribute("data-mobile-sheet", sheet);
      document.querySelectorAll("button[data-mobile-sheet]").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-mobile-sheet") === sheet);
      });
      if (mobRightTitleEl) {
        if (sheet === "cams") mobRightTitleEl.textContent = "CAMERAS & MAP LAYERS";
        else if (sheet === "weather") mobRightTitleEl.textContent = "5-ZONE LIVE WEATHER";
        else if (sheet === "toilets") mobRightTitleEl.textContent = "OFFICIAL TOILETS & AID";
      }
      requestAnimationFrame(function () {
        syncMobileChromeMetrics();
        if (sheet === "map" && !document.body.classList.contains("mob-profile-collapsed")) {
          if (window.C2KBroadcastHud && window.C2KBroadcastHud.resizeElevationCanvas) {
            window.C2KBroadcastHud.resizeElevationCanvas();
            window.C2KBroadcastHud.drawElevationProfile();
          }
        }
      });
    }

    // Mobile Sheet Navigation
    setMobileSheet("map");
    document.querySelectorAll("button[data-mobile-sheet]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const requested = btn.getAttribute("data-mobile-sheet") || "map";
        const current = document.body.getAttribute("data-mobile-sheet") || "map";
        const target = requested !== "map" && requested === current ? "map" : requested;
        setMobileSheet(target);
      });
    });

    function closeAllDrawers() {
      setMobileSheet("map");
    }
    closeMobileSheetsFn = closeAllDrawers;

    document.querySelectorAll("[data-close-mobile-sheet]").forEach(function (btn) {
      btn.addEventListener("click", closeAllDrawers);
    });

    // Collapsible Mobile Elevation Profile Toggle
    function setMobileProfileCollapsed(collapsed) {
      document.body.classList.toggle("mob-profile-collapsed", !!collapsed);
      if (btnMobToggleProfile) {
        btnMobToggleProfile.classList.toggle("active-cyan", !collapsed);
        btnMobToggleProfile.setAttribute("aria-expanded", collapsed ? "false" : "true");
      }
      requestAnimationFrame(function () {
        syncMobileChromeMetrics();
        if (!collapsed && window.C2KBroadcastHud && window.C2KBroadcastHud.resizeElevationCanvas) {
          window.C2KBroadcastHud.resizeElevationCanvas();
          window.C2KBroadcastHud.drawElevationProfile();
        }
      });
    }

    if (window.innerWidth <= 960 && window.innerHeight <= 520) {
      setMobileProfileCollapsed(true);
    } else {
      setMobileProfileCollapsed(false);
    }

    if (btnMobToggleProfile) {
      btnMobToggleProfile.addEventListener("click", function () {
        const nextCollapsed = !document.body.classList.contains("mob-profile-collapsed");
        if (!nextCollapsed && document.body.getAttribute("data-mobile-sheet") !== "map") {
          setMobileSheet("map");
        }
        setMobileProfileCollapsed(nextCollapsed);
      });
    }

    applyDockStates();
    syncMobileChromeMetrics();

    // Basemap Style Switcher (3D Satellite / Relief Map / Esri)
    document.querySelectorAll("[data-imagery]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const mode = btn.getAttribute("data-imagery");
        document.querySelectorAll("[data-imagery]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        window.C2KTerrainEngine.setImageryLayer(mode);
      });
    });

    // Relief Vertical Exaggeration Slider
    const reliefSlider = document.getElementById("relief-slider");
    const reliefValLabel = document.getElementById("relief-val-label");
    if (reliefSlider) {
      syncSliderCssVars(reliefSlider);
      reliefSlider.addEventListener("input", function () {
        const val = parseFloat(reliefSlider.value) || 2.2;
        syncSliderCssVars(reliefSlider);
        window.C2KTerrainEngine.setTerrainExaggeration(val);
        if (reliefValLabel) {
          reliefValLabel.textContent = "x" + val.toFixed(1);
        }
        reliefSlider.setAttribute("aria-valuetext", val.toFixed(1) + "x vertical exaggeration");
      });
    }

    // Compass Reset, Zoom In/Out & Mouse/Touch Orbit/Pan Switch
    const btnCompass = document.getElementById("btn-compass-reset");
    if (btnCompass) {
      btnCompass.addEventListener("click", function () {
        window.C2KTerrainEngine.resetNorth();
      });
    }

    const btnZoomIn = document.getElementById("btn-zoom-in");
    if (btnZoomIn) {
      btnZoomIn.addEventListener("click", function () {
        window.C2KTerrainEngine.zoomIn();
      });
    }

    const btnZoomOut = document.getElementById("btn-zoom-out");
    if (btnZoomOut) {
      btnZoomOut.addEventListener("click", function () {
        window.C2KTerrainEngine.zoomOut();
      });
    }

    const btnDragMode = document.getElementById("btn-drag-mode");
    const gestureHint = document.getElementById("gesture-hint-text");
    if (btnDragMode) {
      btnDragMode.addEventListener("click", function () {
        const nextOrbit = !window.C2KTerrainEngine.isOrbitDragMode();
        window.C2KTerrainEngine.setOrbitDragMode(nextOrbit);
        btnDragMode.classList.toggle("is-orbit", nextOrbit);
        btnDragMode.setAttribute("aria-pressed", nextOrbit ? "true" : "false");
        btnDragMode.textContent = nextOrbit ? "Orbit" : "Pan";
        if (gestureHint) {
          gestureHint.textContent = nextOrbit
            ? "Drag to orbit 3D · 2-finger pinch/pan or right-drag to pan · Scroll to zoom"
            : "Drag to pan · 2-finger twist/pinch or right-drag to orbit 3D · Scroll to zoom";
        }
      });
    }

    // Atmospheric & Layer Toggles inside Weather Drawer
    const btnClouds = document.getElementById("toggle-3d-clouds");
    if (btnClouds) {
      btnClouds.addEventListener("click", function () {
        const active = !btnClouds.classList.contains("active-cyan");
        btnClouds.classList.toggle("active-cyan", active);
        window.C2KWeatherClouds3D.setCloudsEnabled(active);
      });
    }

    const btnRadar = document.getElementById("toggle-bom-radar");
    if (btnRadar) {
      btnRadar.addEventListener("click", function () {
        const active = !btnRadar.classList.contains("active-cyan");
        btnRadar.classList.toggle("active-cyan", active);
        window.C2KWeatherClouds3D.setRadarEnabled(active);
      });
    }

    const btnMilestones = document.getElementById("toggle-milestones");
    if (btnMilestones) {
      btnMilestones.addEventListener("click", function () {
        const active = !btnMilestones.classList.contains("active");
        btnMilestones.classList.toggle("active", active);
        window.C2KTerrainEngine.setMilestonesVisible(active);
      });
    }

    function syncToiletsLayer(nextActive) {
      const btnTop = document.getElementById("toggle-toilets");
      const btnPanel = document.getElementById("btn-panel-toggle-toilets");
      if (btnTop) btnTop.classList.toggle("active-cyan", nextActive);
      if (btnPanel) btnPanel.classList.toggle("active", nextActive);
      if (window.C2KTerrainEngine && window.C2KTerrainEngine.setToiletsVisible) {
        window.C2KTerrainEngine.setToiletsVisible(nextActive);
      }
      if (window.C2KBroadcastHud && window.C2KBroadcastHud.drawElevationProfile) {
        window.C2KBroadcastHud.drawElevationProfile();
      }
    }

    const btnToilets = document.getElementById("toggle-toilets");
    if (btnToilets) {
      btnToilets.addEventListener("click", function () {
        const next = !(window.C2KTerrainEngine && window.C2KTerrainEngine.isToiletsVisible && window.C2KTerrainEngine.isToiletsVisible());
        syncToiletsLayer(next);
      });
    }

    const btnPanelToilets = document.getElementById("btn-panel-toggle-toilets");
    if (btnPanelToilets) {
      btnPanelToilets.addEventListener("click", function () {
        const next = !(window.C2KTerrainEngine && window.C2KTerrainEngine.isToiletsVisible && window.C2KTerrainEngine.isToiletsVisible());
        syncToiletsLayer(next);
      });
    }

    // Camera Director Buttons
    document.querySelectorAll("[data-cam-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const mode = btn.getAttribute("data-cam-mode");
        if (window.innerWidth <= 1024) {
          closeAllDrawers();
        }
        if (mode === "flyover" && window.C2KTerrainEngine.getCameraMode() === "flyover") {
          window.C2KTerrainEngine.setCameraMode("free");
          return;
        }
        window.C2KTerrainEngine.setCameraMode(mode);
      });
    });

    // Quick Landmark Fly-To Buttons
    document.querySelectorAll("[data-fly-km]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const km = parseFloat(btn.getAttribute("data-fly-km"));
        const pt = window.C2KTerrainEngine.getPointAtKm(km);
        if (window.innerWidth <= 1024) {
          closeAllDrawers();
        }
        if (pt) {
          window.C2KTerrainEngine.flyToCoordinate(pt[0], pt[1], 13.7, 66, pt[5]);
        }
      });
    });

    // Telemetry Mode Switcher (SIM vs LIVE)
    document.querySelectorAll("[data-telemetry-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const m = btn.getAttribute("data-telemetry-mode");
        window.C2KTelemetryClient.setMode(m);
      });
    });

    // Simulator Play / Pause & Speed Controls
    const btnPlay = document.getElementById("btn-sim-play");
    if (btnPlay) {
      btnPlay.addEventListener("click", function () {
        const playing = window.C2KTelemetryClient.toggleSimPlayback();
        btnPlay.textContent = playing ? "Pause" : "Play 46h Sim";
        btnPlay.classList.toggle("active", playing);
      });
    }

    document.querySelectorAll("[data-sim-speed]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const spd = parseFloat(btn.getAttribute("data-sim-speed"));
        document.querySelectorAll("[data-sim-speed]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        window.C2KTelemetryClient.setSimSpeed(spd);
      });
    });

    const simSlider = document.getElementById("sim-time-slider");
    if (simSlider) {
      syncSliderCssVars(simSlider);
      simSlider.addEventListener("input", function () {
        syncSliderCssVars(simSlider);
        window.C2KTelemetryClient.setSimElapsedHours(parseFloat(simSlider.value));
      });
    }

    // Refresh Live Weather button
    const btnRefreshWx = document.getElementById("btn-refresh-weather");
    if (btnRefreshWx) {
      btnRefreshWx.addEventListener("click", function () {
        btnRefreshWx.textContent = "Syncing...";
        window.C2KWeatherClouds3D.refreshLiveWeather().finally(function () {
          btnRefreshWx.textContent = "Refresh WX";
        });
      });
    }

    // Native <dialog closedby="any"> Crew Check-In Dialog
    const modal = document.getElementById("crew-checkin-modal");
    const btnOpenModal = document.getElementById("btn-open-checkin");
    const btnCloseModal = document.getElementById("btn-close-checkin");
    const feedbackEl = document.getElementById("checkin-feedback");
    const trackerLinkEl = document.getElementById("link-official-tracker");

    function setFeedback(msg, isError) {
      if (!feedbackEl) return;
      if (!msg) {
        feedbackEl.hidden = true;
        feedbackEl.textContent = "";
        feedbackEl.className = "checkin-feedback";
        return;
      }
      feedbackEl.hidden = false;
      feedbackEl.textContent = msg;
      feedbackEl.className = "checkin-feedback " + (isError ? "is-error" : "is-success");
    }

    function setActiveLocMethod(method) {
      activeLocMethod = method || "checkpoint";
      document.querySelectorAll("[data-loc-method]").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-loc-method") === activeLocMethod);
      });
      ["checkpoint", "gps", "gpx"].forEach(function (name) {
        const panel = document.getElementById("loc-panel-" + name);
        if (panel) {
          panel.hidden = name !== activeLocMethod;
        }
      });
      setFeedback("", false);
    }

    document.querySelectorAll("[data-loc-method]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setActiveLocMethod(btn.getAttribute("data-loc-method"));
      });
    });

    const btnJesseSnap = document.getElementById("btn-jesse-here-snap");
    const jesseSnapSubEl = document.getElementById("jesse-snap-sub");
    const DEFAULT_SNAP_SUB = "Snaps Jesse + Crew Car to your exact phone GPS & resets ETA";
    const CREW_PIN_STORAGE_KEY = "c2k_crew_pin_v1";

    function loadSavedCrewPin() {
      try {
        return localStorage.getItem(CREW_PIN_STORAGE_KEY) || "";
      } catch (_e) {
        return "";
      }
    }

    function saveCrewPin(pin) {
      if (!pin) return;
      try {
        localStorage.setItem(CREW_PIN_STORAGE_KEY, pin);
      } catch (_e) {
        // Ignore storage quota or private-mode errors
      }
    }

    function setJesseSnapUi(subText, isError, isBusy) {
      if (!btnJesseSnap) return;
      btnJesseSnap.disabled = !!isBusy;
      btnJesseSnap.classList.toggle("is-error", !!isError);
      if (jesseSnapSubEl) {
        jesseSnapSubEl.textContent = subText || DEFAULT_SNAP_SUB;
      }
    }

    function openCheckinDialog() {
      if (!modal) return;
      if (trackerLinkEl && window.C2KTelemetryClient && window.C2KTelemetryClient.getExternalTrackerUrl) {
        trackerLinkEl.href = window.C2KTelemetryClient.getExternalTrackerUrl();
      }
      const pinInput = document.getElementById("checkin-pin");
      if (pinInput && !pinInput.value.trim()) {
        const savedPin = loadSavedCrewPin();
        if (savedPin) pinInput.value = savedPin;
      }
      setJesseSnapUi(DEFAULT_SNAP_SUB, false, false);
      setFeedback("", false);
      if (typeof modal.showModal === "function") {
        if (!modal.open) modal.showModal();
      } else {
        modal.setAttribute("open", "");
      }
    }

    if (btnJesseSnap) {
      btnJesseSnap.addEventListener("click", function () {
        const pinInput = document.getElementById("checkin-pin");
        const pin = pinInput ? pinInput.value.trim() : "";
        if (!pin) {
          const msg = "Enter Crew Security PIN below once (remembered on this phone), then tap again.";
          setJesseSnapUi(msg, true, false);
          setFeedback(msg, true);
          if (pinInput) {
            pinInput.focus();
            if (typeof pinInput.scrollIntoView === "function") {
              pinInput.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          }
          return;
        }
        if (!navigator.geolocation) {
          const msg = "Browser Geolocation is not available on this device.";
          setJesseSnapUi(msg, true, false);
          setFeedback(msg, true);
          return;
        }

        setFeedback("", false);
        setJesseSnapUi("Acquiring high-accuracy phone GPS...", false, true);

        navigator.geolocation.getCurrentPosition(
          async function (pos) {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            const ele = typeof pos.coords.altitude === "number" && isFinite(pos.coords.altitude)
              ? pos.coords.altitude
              : null;
            const acc = typeof pos.coords.accuracy === "number" && isFinite(pos.coords.accuracy)
              ? Math.round(pos.coords.accuracy)
              : null;

            const latEl = document.getElementById("checkin-lat");
            const lonEl = document.getElementById("checkin-lon");
            if (latEl) latEl.value = lat.toFixed(6);
            if (lonEl) lonEl.value = lon.toFixed(6);

            const accTag = acc !== null ? " (+/-" + acc + "m)" : "";
            setJesseSnapUi("GPS locked" + accTag + " · Broadcasting Jesse #43 + Crew...", false, true);

            const raceStatusEl = document.getElementById("checkin-race-status");
            const noteEl = document.getElementById("checkin-note");
            const raceStatus = raceStatusEl ? raceStatusEl.value : "LIVE_RACE";
            const customNote = noteEl ? noteEl.value.trim() : "";
            const snapNote = customNote || ("Jesse #43 Rendezvous GPS Snap" + accTag);

            try {
              const payload = {
                pin: pin,
                raceStatus: raceStatus,
                externalTrackerUrl: window.C2KTelemetryClient.getExternalTrackerUrl(),
                note: snapNote,
                runner: {
                  name: "Jesse Simon",
                  bib: "43",
                  lat: lat,
                  lon: lon,
                  ele: ele,
                  course_km: null,
                  source: "Crew 1-Tap GPS Snap",
                  note: snapNote
                },
                crew: {
                  lat: lat,
                  lon: lon,
                  ele: ele,
                  course_km: null,
                  source: "Crew 1-Tap GPS Snap",
                  note: snapNote
                }
              };

              const res = await window.C2KTelemetryClient.submitCrewCheckin(payload);
              if (res && res.error) {
                setJesseSnapUi("Snap error: " + res.error, true, false);
                setFeedback("Check-in error: " + res.error, true);
              } else {
                saveCrewPin(pin);
                setJesseSnapUi(DEFAULT_SNAP_SUB, false, false);
                closeCheckinDialog("submitted");
                window.C2KTerrainEngine.flyToCoordinate(lon, lat, 14.0, 66, -30);
              }
            } catch (e) {
              setJesseSnapUi("Network error: " + e.message, true, false);
              setFeedback("Network error submitting GPS snap: " + e.message, true);
            }
          },
          function (err) {
            const msg = "GPS Error: " + (err && err.message ? err.message : "Could not acquire location");
            setJesseSnapUi(msg, true, false);
            setFeedback(msg, true);
          },
          { enableHighAccuracy: true, timeout: 12000, maximumAge: 5000 }
        );
      });
    }

    function closeCheckinDialog(reason) {
      if (!modal) return;
      if (typeof modal.close === "function") {
        if (modal.open) modal.close(reason || "cancel");
      } else {
        modal.removeAttribute("open");
      }
    }

    if (btnOpenModal) {
      btnOpenModal.addEventListener("click", openCheckinDialog);
    }
    if (btnCloseModal) {
      btnCloseModal.addEventListener("click", function () {
        closeCheckinDialog("cancel");
      });
    }
    if (modal) {
      modal.addEventListener("close", function () {
        const rv = modal.returnValue;
        modal.returnValue = "";
        if (rv === "cancel" || rv === "dismiss") {
          setFeedback("", false);
        }
      });

      attachDialogLightDismiss(modal, function () {
        closeCheckinDialog("dismiss");
      });
    }

    const btnUseGps = document.getElementById("btn-use-phone-gps");
    if (btnUseGps) {
      btnUseGps.addEventListener("click", function () {
        if (!navigator.geolocation) {
          setFeedback("Browser Geolocation is not available on this device.", true);
          return;
        }
        btnUseGps.textContent = "Acquiring Satellite Fix...";
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            document.getElementById("checkin-lat").value = pos.coords.latitude.toFixed(6);
            document.getElementById("checkin-lon").value = pos.coords.longitude.toFixed(6);
            btnUseGps.textContent = "Locked Current Phone GPS";
            setFeedback("Locked phone coordinates (" + pos.coords.latitude.toFixed(5) + ", " + pos.coords.longitude.toFixed(5) + ").", false);
          },
          function (err) {
            btnUseGps.textContent = "GPS Error";
            setFeedback("GPS Error: " + err.message, true);
          },
          { enableHighAccuracy: true, timeout: 10000 }
        );
      });
    }

    const btnPickMap = document.getElementById("btn-pick-map-pin");
    if (btnPickMap) {
      btnPickMap.addEventListener("click", function () {
        closeCheckinDialog("pick-map");
        closeAllDrawers();
        if (window.C2KTerrainEngine && window.C2KTerrainEngine.enableMapPinPick) {
          window.C2KTerrainEngine.enableMapPinPick(function (picked) {
            setActiveLocMethod("gps");
            if (picked) {
              document.getElementById("checkin-lat").value = Number(picked.lat).toFixed(6);
              document.getElementById("checkin-lon").value = Number(picked.lon).toFixed(6);
            }
            openCheckinDialog();
            if (picked) {
              setFeedback("Picked map spot (" + Number(picked.lat).toFixed(5) + ", " + Number(picked.lon).toFixed(5) + ").", false);
            }
          });
        }
      });
    }

    const gpxInput = document.getElementById("checkin-gpx-file");
    const gpxSummary = document.getElementById("gpx-parse-summary");
    if (gpxInput) {
      gpxInput.addEventListener("change", async function () {
        parsedGpxPoints = [];
        const file = gpxInput.files && gpxInput.files[0];
        if (!file) {
          if (gpxSummary) gpxSummary.textContent = "No .gpx file selected.";
          return;
        }
        try {
          const text = await file.text();
          parsedGpxPoints = parseGpxXmlClient(text);
          if (!parsedGpxPoints.length) {
            if (gpxSummary) gpxSummary.textContent = "No <trkpt> coordinates found in " + file.name + ".";
            return;
          }
          const last = parsedGpxPoints[parsedGpxPoints.length - 1];
          if (gpxSummary) {
            gpxSummary.textContent =
              "Ready: " + file.name + " (" + parsedGpxPoints.length + " pts) | Latest fix: " +
              last.lat.toFixed(5) + ", " + last.lon.toFixed(5) +
              (last.time ? " @ " + last.time : "");
          }
        } catch (err) {
          if (gpxSummary) gpxSummary.textContent = "GPX parse failed: " + err.message;
        }
      });
    }

    const btnSubmitCheckin = document.getElementById("btn-submit-checkin");
    if (btnSubmitCheckin) {
      btnSubmitCheckin.addEventListener("click", async function () {
        const pin = document.getElementById("checkin-pin").value.trim();
        const roleSel = document.getElementById("checkin-role").value;
        const raceStatus = document.getElementById("checkin-race-status").value;
        const note = document.getElementById("checkin-note").value.trim();

        if (!pin) {
          setFeedback("Enter Crew Security PIN first.", true);
          return;
        }

        setFeedback("", false);

        if (activeLocMethod === "gpx") {
          if (!parsedGpxPoints.length) {
            setFeedback("Select a valid .gpx file containing <trkpt> points first.", true);
            return;
          }
          const slice = parsedGpxPoints.slice(-30);
          const lastPt = slice[slice.length - 1];
          btnSubmitCheckin.textContent = "Uploading GPX Track...";
          try {
            const roles = roleSel === "both" ? ["runner", "crew"] : [roleSel];
            let lastRes = null;
            for (let i = 0; i < roles.length; i++) {
              lastRes = await window.C2KTelemetryClient.submitGpxIngest({
                pin: pin,
                role: roles[i],
                points: slice,
                source: "Crew GPX File Upload",
                note: note || "Uploaded GPX track fix",
                forceLive: raceStatus === "LIVE_RACE"
              });
              if (lastRes && lastRes.error) break;
            }
            if (lastRes && lastRes.error) {
              setFeedback("GPX ingest error: " + lastRes.error, true);
            } else {
              saveCrewPin(pin);
              closeCheckinDialog("submitted");
              window.C2KTerrainEngine.flyToCoordinate(lastPt.lon, lastPt.lat, 13.8, 66, -30);
            }
          } catch (e) {
            setFeedback("Network error uploading GPX: " + e.message, true);
          } finally {
            btnSubmitCheckin.textContent = "Broadcast Live Pin to 3D Map";
          }
          return;
        }

        let lat = NaN;
        let lon = NaN;
        let ele = null;
        let courseKm = null;

        if (activeLocMethod === "checkpoint") {
          const exactRaw = document.getElementById("checkin-exact-km").value.trim();
          let targetKm = parseFloat(document.getElementById("checkin-cp-select").value);
          if (exactRaw !== "") {
            const parsedExact = parseFloat(exactRaw);
            if (isNaN(parsedExact) || parsedExact < 0 || parsedExact > 241.25) {
              setFeedback("Exact course km must be between 0 and 241.25.", true);
              return;
            }
            targetKm = parsedExact;
          }
          const pt = window.C2KTerrainEngine.getPointAtKm(targetKm);
          if (!pt) {
            setFeedback("Could not resolve course coordinate for that checkpoint/km.", true);
            return;
          }
          lon = pt[0];
          lat = pt[1];
          ele = pt[2];
          courseKm = pt[3];
        } else {
          lat = parseFloat(document.getElementById("checkin-lat").value);
          lon = parseFloat(document.getElementById("checkin-lon").value);
          if (isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
            setFeedback("Enter valid Latitude and Longitude or use Phone GPS / Pick on Map.", true);
            return;
          }
        }

        btnSubmitCheckin.textContent = "Broadcasting to 24/7 Cloud Relay...";
        try {
          const payload = {
            pin: pin,
            raceStatus: raceStatus,
            externalTrackerUrl: window.C2KTelemetryClient.getExternalTrackerUrl(),
            note: note || "Crew Mobile Check-In"
          };
          const pinNote = note || (courseKm !== null ? "Pinned at " + courseKm.toFixed(1) + " km" : "Crew Mobile Check-In");
          if (roleSel === "both" || roleSel === "runner") {
            payload.runner = {
              name: "Jesse Simon",
              bib: "43",
              lat: lat,
              lon: lon,
              ele: ele,
              course_km: courseKm,
              source: activeLocMethod === "checkpoint" ? "Crew KM Quick-Pin" : "Crew GPS Check-In",
              note: pinNote
            };
          }
          if (roleSel === "both" || roleSel === "crew") {
            payload.crew = {
              lat: lat,
              lon: lon,
              ele: ele,
              course_km: courseKm,
              source: activeLocMethod === "checkpoint" ? "Crew KM Quick-Pin" : "Crew GPS Check-In",
              note: pinNote
            };
          }

          const res = await window.C2KTelemetryClient.submitCrewCheckin(payload);
          if (res && res.error) {
            setFeedback("Check-in error: " + res.error, true);
          } else {
            saveCrewPin(pin);
            closeCheckinDialog("submitted");
            window.C2KTerrainEngine.flyToCoordinate(lon, lat, 14.0, 66, -30);
          }
        } catch (e) {
          setFeedback("Network error submitting check-in: " + e.message, true);
        } finally {
          btnSubmitCheckin.textContent = "Broadcast Live Pin to 3D Map";
        }
      });
    }

    const stopModal = document.getElementById("stop-detail-modal");
    const btnCloseStop = document.getElementById("btn-close-stop-detail");
    if (btnCloseStop && stopModal) {
      btnCloseStop.addEventListener("click", function () {
        if (typeof stopModal.close === "function") {
          if (stopModal.open) stopModal.close();
        } else {
          stopModal.removeAttribute("open");
        }
      });
    }
    if (stopModal) {
      attachDialogLightDismiss(stopModal);
    }
  }

  let selectedStopForFly = null;

  function openStopDetailModal(stop) {
    if (!stop) return;
    selectedStopForFly = stop;
    const modal = document.getElementById("stop-detail-modal");
    if (!modal) return;

    const titleEl = document.getElementById("stop-detail-title");
    const badgesEl = document.getElementById("stop-detail-badges");
    const kmEl = document.getElementById("stop-detail-km");
    const simonDistEl = document.getElementById("stop-detail-simon-dist");
    const crewDistEl = document.getElementById("stop-detail-crew-dist");
    const toiletEl = document.getElementById("stop-detail-toilet");
    const aidEl = document.getElementById("stop-detail-aid");
    const crewEl = document.getElementById("stop-detail-crew");
    const offBox = document.getElementById("stop-detail-offroute-box");
    const offEl = document.getElementById("stop-detail-offroute");
    const gmapsEl = document.getElementById("btn-stop-gmaps");
    const flyBtn = document.getElementById("btn-stop-fly");

    if (titleEl) titleEl.textContent = stop.name || "Official Stop Details";

    if (badgesEl) {
      const b = [];
      if (stop.kind === "no_toilet") b.push('<span class="stop-badge danger">NO TOILETS - PENALTIES APPLY</span>');
      else if (stop.has_toilet) b.push('<span class="stop-badge ok">Official C2K Toilet</span>');
      if (stop.has_aid) b.push('<span class="stop-badge info">Aid / Refreshments</span>');
      if (stop.payment_badge) {
        const cls = stop.payment_badge.indexOf("CASH") !== -1 ? "warn" : "info";
        b.push('<span class="stop-badge ' + cls + '">' + stop.payment_badge + '</span>');
      }
      if (stop.source) b.push('<span class="stop-badge info">' + stop.source + '</span>');
      badgesEl.innerHTML = b.join("");
    }

    if (kmEl) {
      kmEl.textContent = stop.return_course_km
        ? stop.course_km.toFixed(1) + " / " + stop.return_course_km.toFixed(1) + "k"
        : stop.course_km.toFixed(1) + " km";
    }

    const r = window.C2KTelemetryClient ? window.C2KTelemetryClient.getRunnerState() : null;
    const c = window.C2KTelemetryClient ? window.C2KTelemetryClient.getCrewState() : null;
    if (simonDistEl) {
      if (r) {
        const targetKm = (stop.return_course_km && r.course_km > stop.course_km + 0.3) ? stop.return_course_km : stop.course_km;
        const delta = targetKm - (r.course_km || 0);
        simonDistEl.textContent = (delta >= 0 ? "+" : "") + delta.toFixed(1) + " km";
      } else {
        simonDistEl.textContent = "--";
      }
    }
    if (crewDistEl) {
      if (c && window.C2KTelemetryClient && window.C2KTelemetryClient.haversineKm) {
        const directKm = window.C2KTelemetryClient.haversineKm(c.lat, c.lon, stop.lat, stop.lon);
        crewDistEl.textContent = directKm.toFixed(1) + " km air";
      } else {
        crewDistEl.textContent = "--";
      }
    }

    if (toiletEl) toiletEl.textContent = stop.toilet_rule || "--";
    if (aidEl) aidEl.textContent = stop.food_aid || "None";
    if (crewEl) crewEl.textContent = stop.crew_note || "--";

    if (offBox && offEl) {
      if (stop.off_route_note) {
        offBox.hidden = false;
        offEl.textContent = stop.off_route_note;
      } else {
        offBox.hidden = true;
        offEl.textContent = "";
      }
    }

    if (gmapsEl) {
      gmapsEl.href = "https://www.google.com/maps/dir/?api=1&destination=" + stop.lat + "," + stop.lon + "&travelmode=driving";
    }

    if (flyBtn) {
      flyBtn.onclick = function () {
        if (!selectedStopForFly) return;
        if (typeof modal.close === "function") {
          if (modal.open) modal.close();
        } else {
          modal.removeAttribute("open");
        }
        if (window.innerWidth <= 1024 && closeMobileSheetsFn) {
          closeMobileSheetsFn();
        }
        if (window.C2KTerrainEngine && window.C2KTerrainEngine.flyToCoordinate) {
          window.C2KTerrainEngine.flyToCoordinate(selectedStopForFly.lon, selectedStopForFly.lat, 14.4, 62, -25);
        }
      };
    }

    if (typeof modal.showModal === "function") {
      if (!modal.open) modal.showModal();
    } else {
      modal.setAttribute("open", "");
    }
  }

  function populateCheckpointSelect() {
    const sel = document.getElementById("checkin-cp-select");
    if (!sel || !courseData) return;

    let html = '<option value="0">Start - Boydtown Beach (0.0 km)</option>';
    (courseData.pois || []).forEach(function (p) {
      if (["checkpoint", "summit", "finish", "crew_uturn", "crew_rendezvous"].indexOf(p.category) !== -1) {
        html += '<option value="' + p.course_km + '">' + p.name + ' (' + p.course_km.toFixed(1) + ' km · ' + p.ele_m + 'm)</option>';
      }
    });
    for (let k = 10; k <= 240; k += 10) {
      html += '<option value="' + k + '">Course Milestone - ' + k + '.0 km</option>';
    }
    sel.innerHTML = html;
  }

  document.addEventListener("DOMContentLoaded", boot);

  return {
    getCurrentRunnerState: function () {
      return window.C2KTelemetryClient ? window.C2KTelemetryClient.getRunnerState() : null;
    },
    getCurrentCrewState: function () {
      return window.C2KTelemetryClient ? window.C2KTelemetryClient.getCrewState() : null;
    },
    openStopDetailModal: openStopDetailModal,
    closeMobileSheets: function () {
      if (closeMobileSheetsFn) closeMobileSheetsFn();
    }
  };
})();
