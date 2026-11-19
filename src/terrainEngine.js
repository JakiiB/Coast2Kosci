/**
 * Coast to Kosciuszko (C2K) - Auto-Hybrid 3D Engine Coordinator
 * Architecture:
 *  - Stage A (Macro 3D Corridor): window.C2KHybridThreeStage renders pre-baked AWS Terrarium
 *    3D mesh + progressive 2K/4K/6K satellite & relief megatextures for <0.4s boot,
 *    silky 60 FPS whole-course orbiting, scrubbing, and 241 km flyover tours.
 *  - Stage B (Micro Street Satellite): MapLibre GL v4 + 3D terrain tiles stream sharp
 *    Google/Esri imagery & contours when zooming tight into a checkpoint, carpark, or runner.
 *  - Bidirectional Camera Sync + Hysteresis Crossfade: Enters STREET SAT at zoom >= 12.20,
 *    returns to 3D CORRIDOR at zoom < 11.75 with matched [lon, lat, zoom, pitch, bearing].
 */

window.C2KTerrainEngine = (function () {
  const STREET_ZOOM_EXIT = 11.75;
  const CROSSFADE_PAUSE_MS = 380;

  let map = null;
  let mapStyleLoaded = false;
  let courseData = null;
  let terrainExaggeration = 2.2;
  let cameraMode = "overview"; // overview | follow-simon | follow-crew | flyover | free
  let activeEngine = "three"; // "three" | "maplibre"
  let activeImageryMode = "google"; // "google" | "relief" | "esri"

  let isProgrammaticZoomIn = false;
  let zoomInResetTimer = null;
  let pauseThreeTimer = null;

  let smoothCamLon = null;
  let smoothCamLat = null;
  let lastFrameTime = performance.now();

  let orbitDragMode = true;
  let dragAction = null;
  let isTouchDown = false;
  let lastClientX = 0;
  let lastClientY = 0;
  let lastMoveTime = 0;
  let dragMovedDist = 0;
  let suppressNextContextMenu = false;
  let velBrg = 0;
  let velPitch = 0;
  let velPanX = 0;
  let velPanY = 0;

  let runnerMarker = null;
  let runnerEl = null;
  let runnerLastFixMarker = null;
  let crewMarker = null;
  let crewEl = null;
  let scrubHoverMarker = null;
  let poiMarkers = [];
  let toiletMarkers = [];
  let milestonesVisible = true;
  let toiletsVisible = false;
  let radarTileUrl = null;
  let radarVisible = false;
  let lastCompletedUpdateKm = -999;
  let lastCompletedUpdateTime = 0;
  let lastRunnerState = null;
  let lastCrewState = null;
  let mapPinPickCallback = null;
  let readyFired = false;

  const COURSE_MAX_BOUNDS = [
    [143.00, -40.50],
    [154.50, -32.50]
  ];

  // Cow Bail crew road detour waypoints (Rocky Hall -> Wyndham -> Mt Darragh Rd -> Cathcart)
  const CREW_DETOUR_COORDS = [
    [149.47101, -36.90518],
    [149.50321, -36.92718],
    [149.52750, -36.92610],
    [149.47200, -36.88500],
    [149.43500, -36.85900],
    [149.39124, -36.84325]
  ];

  function computeMacroBearing(lon1, lat1, lon2, lat2) {
    const dLon = ((lon2 - lon1) * Math.PI) / 180.0;
    const phi1 = (lat1 * Math.PI) / 180.0;
    const phi2 = (lat2 * Math.PI) / 180.0;
    const y = Math.sin(dLon) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
    return ((Math.atan2(y, x) * 180.0) / Math.PI + 360.0) % 360.0;
  }

  function updateHybridBadge() {
    const badge = document.getElementById("hybrid-engine-badge");
    if (!badge) return;
    const isStreet = activeEngine === "maplibre";
    badge.classList.toggle("is-street", isStreet);
    badge.textContent = isStreet ? "STREET SAT" : "3D CORRIDOR";
    badge.title = isStreet
      ? "MapLibre 3D Street Satellite (auto-crossfaded for tight zoom) - click to switch back"
      : "Three.js 3D Corridor Mesh (60 FPS macro terrain) - zoom past 12.2 for Google Street Sat";
  }

  function updateCompassNeedle() {
    if (!map || activeEngine !== "maplibre") return;
    const svg = document.getElementById("compass-needle-svg");
    if (svg) {
      svg.style.transform = "rotate(" + (-map.getBearing()).toFixed(1) + "deg)";
    }
  }

  function updateZoomDeclutter() {
    if (!map) return;
    const c = map.getContainer();
    if (c) {
      c.classList.toggle("is-overview-zoom", map.getZoom() < 10.3);
    }
  }

  function releaseAutoCamera() {
    if (cameraMode !== "free") {
      setCameraMode("free");
    }
  }

  function buildStyleSpec() {
    return {
      version: 8,
      name: "C2K Auto-Hybrid MapLibre Stage",
      sources: {
        "terrain-dem": {
          type: "raster-dem",
          tiles: [
            "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
          ],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 12,
          encoding: "terrarium"
        },
        "hillshade-dem": {
          type: "raster-dem",
          tiles: [
            "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
          ],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 12,
          encoding: "terrarium"
        },
        "relief-topo": {
          type: "raster",
          tiles: [
            "https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
          ],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 18,
          attribution: "Esri World Topo, AWS Terrain"
        },
        "esri-sat": {
          type: "raster",
          tiles: [
            "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          ],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 18,
          attribution: "Esri World Imagery"
        },
        "google-sat": {
          type: "raster",
          tiles: [
            "https://mt0.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            "https://mt2.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            "https://mt3.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
          ],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 20,
          attribution: "Google Satellite, AWS Terrain"
        }
      },
      terrain: {
        source: "terrain-dem",
        exaggeration: terrainExaggeration
      },
      sky: {
        "sky-color": "#06090f",
        "sky-horizon-blend": 0.65,
        "horizon-color": "#16263d",
        "horizon-fog-blend": 0.82,
        "fog-color": "#0e1726",
        "fog-ground-blend": 0.22
      },
      layers: [
        {
          id: "bg-void",
          type: "background",
          paint: { "background-color": "#06090f" }
        },
        {
          id: "layer-relief",
          type: "raster",
          source: "relief-topo",
          layout: { visibility: "none" },
          paint: {
            "raster-contrast": 0.08,
            "raster-saturation": -0.05,
            "raster-brightness-max": 0.92,
            "raster-fade-duration": 80
          }
        },
        {
          id: "layer-esri",
          type: "raster",
          source: "esri-sat",
          layout: { visibility: "none" },
          paint: {
            "raster-contrast": 0.05,
            "raster-saturation": 0.04,
            "raster-fade-duration": 80
          }
        },
        {
          id: "layer-google",
          type: "raster",
          source: "google-sat",
          layout: { visibility: "visible" },
          paint: {
            "raster-contrast": 0.05,
            "raster-saturation": 0.04,
            "raster-fade-duration": 80
          }
        },
        {
          id: "layer-hillshade",
          type: "hillshade",
          source: "hillshade-dem",
          layout: { visibility: "none" },
          paint: {
            "hillshade-illumination-direction": 315,
            "hillshade-exaggeration": 0.52,
            "hillshade-shadow-color": "#09101d",
            "hillshade-highlight-color": "#fff8eb",
            "hillshade-accent-color": "#334155"
          }
        }
      ]
    };
  }

  function initMouseOrbitController() {
    if (!map) return;
    const canvas = map.getCanvas();
    if (!canvas) return;

    function onWindowPointerMove(e) {
      if (!dragAction) return;
      const now = performance.now();
      const dt = Math.max(0.004, Math.min(0.05, (now - lastMoveTime) / 1000));
      const dx = e.clientX - lastClientX;
      const dy = e.clientY - lastClientY;
      lastClientX = e.clientX;
      lastClientY = e.clientY;
      lastMoveTime = now;
      dragMovedDist += Math.hypot(dx, dy);

      if (dragAction === "orbit") {
        const dBrg = dx * 0.30;
        const dPitch = -dy * 0.25;
        map.jumpTo({
          bearing: map.getBearing() + dBrg,
          pitch: Math.max(0, Math.min(78, map.getPitch() + dPitch))
        });
        velBrg = velBrg * 0.45 + (dBrg / dt) * 0.55;
        velPitch = velPitch * 0.45 + (dPitch / dt) * 0.55;
        updateCompassNeedle();
      } else if (dragAction === "pan") {
        map.panBy([-dx, -dy], { animate: false });
        velPanX = velPanX * 0.45 + (dx / dt) * 0.55;
        velPanY = velPanY * 0.45 + (dy / dt) * 0.55;
      }
    }

    function endDrag(wasRightClick) {
      if (wasRightClick && dragMovedDist > 3) {
        suppressNextContextMenu = true;
        setTimeout(function () { suppressNextContextMenu = false; }, 120);
      }
      dragAction = null;
      window.removeEventListener("pointermove", onWindowPointerMove);
      window.removeEventListener("pointerup", onWindowPointerUp);
      window.removeEventListener("pointercancel", onWindowPointerUp);
    }

    function onWindowPointerUp(e) {
      endDrag(e && e.button === 2);
    }

    canvas.addEventListener(
      "pointerdown",
      function (e) {
        if (e.pointerType !== "mouse") {
          isTouchDown = true;
          releaseAutoCamera();
          return;
        }
        isTouchDown = false;
        if (mapPinPickCallback) return;

        let nextAction = null;
        if (orbitDragMode) {
          if (e.button === 2 || (e.button === 0 && e.shiftKey)) nextAction = "pan";
          else if (e.button === 0) nextAction = "orbit";
        } else {
          if (e.button === 2 || (e.button === 0 && e.ctrlKey)) nextAction = "orbit";
          else if (e.button === 0) {
            releaseAutoCamera();
            return;
          }
        }
        if (!nextAction) return;

        e.stopPropagation();
        releaseAutoCamera();
        map.stop();
        velBrg = 0;
        velPitch = 0;
        velPanX = 0;
        velPanY = 0;
        dragAction = nextAction;
        lastClientX = e.clientX;
        lastClientY = e.clientY;
        lastMoveTime = performance.now();
        dragMovedDist = 0;

        window.addEventListener("pointermove", onWindowPointerMove);
        window.addEventListener("pointerup", onWindowPointerUp);
        window.addEventListener("pointercancel", onWindowPointerUp);
      },
      { capture: true }
    );

    canvas.addEventListener(
      "mousedown",
      function (e) {
        if (isTouchDown || mapPinPickCallback) return;
        if (dragAction) e.stopPropagation();
      },
      { capture: true }
    );

    canvas.addEventListener(
      "contextmenu",
      function (e) {
        if (suppressNextContextMenu || (dragAction === "pan" && dragMovedDist > 3)) {
          e.preventDefault();
          e.stopPropagation();
        }
      },
      { capture: true }
    );
  }

  function extractUnsealedMultiLine(track) {
    const lines = [];
    let current = [];
    for (let i = 0; i < track.length; i++) {
      const pt = track[i];
      const km = pt[3];
      const isUnsealed = (km >= 51.7 && km <= 63.5) || km >= 222.6;
      if (isUnsealed) {
        current.push([pt[0], pt[1]]);
      } else if (current.length > 0) {
        if (current.length >= 2) lines.push(current);
        current = [];
      }
    }
    if (current.length >= 2) lines.push(current);
    return lines;
  }

  function setupCourseAndWebGLLayers() {
    if (!courseData || !courseData.track) return;

    const fullCoords = courseData.track.map(function (pt) { return [pt[0], pt[1]]; });
    const unsealedCoords = extractUnsealedMultiLine(courseData.track);

    map.addSource("c2k-route-full", {
      type: "geojson",
      data: { type: "Feature", geometry: { type: "LineString", coordinates: fullCoords } }
    });

    map.addSource("c2k-route-unsealed", {
      type: "geojson",
      data: { type: "Feature", geometry: { type: "MultiLineString", coordinates: unsealedCoords } }
    });

    map.addSource("c2k-crew-detour", {
      type: "geojson",
      data: { type: "Feature", geometry: { type: "LineString", coordinates: CREW_DETOUR_COORDS } }
    });

    map.addSource("c2k-route-completed", {
      type: "geojson",
      data: { type: "Feature", geometry: { type: "LineString", coordinates: [fullCoords[0], fullCoords[0]] } }
    });

    // Dark outer casing (#040711)
    map.addLayer({
      id: "c2k-route-casing",
      type: "line",
      source: "c2k-route-full",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#040711",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 5, 13, 9, 16, 13],
        "line-opacity": 0.92
      }
    });

    // Crew Cow Bail detour road ribbon (#00e5ff dashed)
    map.addLayer({
      id: "c2k-crew-detour-casing",
      type: "line",
      source: "c2k-crew-detour",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#040711",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4, 13, 6.5, 16, 9],
        "line-opacity": 0.85
      }
    });

    map.addLayer({
      id: "c2k-crew-detour-line",
      type: "line",
      source: "c2k-crew-detour",
      layout: { "line-join": "round", "line-cap": "butt" },
      paint: {
        "line-color": "#00e5ff",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.0, 13, 3.2, 16, 4.5],
        "line-dasharray": [2.0, 1.8],
        "line-opacity": 0.9
      }
    });

    // Remaining route line (golden amber #fbbf24)
    map.addLayer({
      id: "c2k-route-remaining",
      type: "line",
      source: "c2k-route-full",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#fbbf24",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.6, 13, 4.6, 16, 6.8],
        "line-opacity": 0.96
      }
    });

    // Unsealed trail dashed accent
    map.addLayer({
      id: "c2k-route-unsealed",
      type: "line",
      source: "c2k-route-unsealed",
      layout: { "line-join": "round", "line-cap": "butt" },
      paint: {
        "line-color": "#fef3c7",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.0, 13, 3.2, 16, 4.4],
        "line-dasharray": [1.5, 2.0],
        "line-opacity": 0.94
      }
    });

    // Completed route line behind Simon (blaze orange #ff5a1f)
    map.addLayer({
      id: "c2k-route-done",
      type: "line",
      source: "c2k-route-completed",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#ff5a1f",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 3.6, 13, 5.8, 16, 8.6],
        "line-opacity": 1.0
      }
    });

    const msFeatures = (courseData.milestones || []).map(function (ms) {
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [ms.lon, ms.lat] },
        properties: { isSpecial: ms.type === "special" ? 1 : 0, km: ms.km }
      };
    });

    map.addSource("c2k-milestones", {
      type: "geojson",
      data: { type: "FeatureCollection", features: msFeatures }
    });

    map.addLayer({
      id: "c2k-milestones-circles",
      type: "circle",
      source: "c2k-milestones",
      paint: {
        "circle-radius": ["case", ["==", ["get", "isSpecial"], 1], 5.5, 3.5],
        "circle-color": ["case", ["==", ["get", "isSpecial"], 1], "#fde047", "#0f172a"],
        "circle-stroke-color": ["case", ["==", ["get", "isSpecial"], 1], "#ff5a1f", "#f8fafc"],
        "circle-stroke-width": 1.6
      }
    });
  }

  function setupCleanBeacons() {
    if (!courseData) return;

    const cutoffNums = { 3: true, 4: true, 5: true, 6: true, 8: true };
    const seenCoords = [];

    (courseData.pois || []).forEach(function (poi) {
      const keepCats = ["start", "summit", "checkpoint", "crew_uturn"];
      if (keepCats.indexOf(poi.category) === -1) return;

      const tooClose = seenCoords.some(function (c) {
        return Math.abs(c[0] - poi.lon) < 0.015 && Math.abs(c[1] - poi.lat) < 0.015;
      });
      if (tooClose && poi.category !== "summit") return;
      seenCoords.push([poi.lon, poi.lat]);

      const el = document.createElement("div");
      el.className = "poi-marker-3d";

      let badgeCls = "poi-badge";
      let title = poi.name;
      if (poi.category === "start") {
        badgeCls += " cat-start";
        title = "START · BOYDTOWN";
      } else if (poi.category === "summit") {
        badgeCls += " cat-summit";
        title = "▲ MT KOSCIUSZKO (2,228m)";
      } else if (poi.category === "crew_uturn") {
        badgeCls += " cat-crew_uturn";
        title = "COW BAIL U-TURN";
      } else if (poi.checkpoint_num) {
        badgeCls += cutoffNums[poi.checkpoint_num] ? " cat-cutoff" : " cat-checkpoint";
        title = poi.name
          .replace("Mandatory Checkpoint #", "CP")
          .replace(" - ", " · ")
          .replace("Gunningrah Rd & Snowy River Way", "SNOWY RIVER WAY")
          .replace("Perisher Valley", "PERISHER")
          .toUpperCase();
      }

      el.innerHTML =
        '<div class="' + badgeCls + '">' +
          '<span>' + title + '</span>' +
          '<span style="opacity:0.75;font-family:var(--font-mono);font-size:9px;">' + poi.course_km.toFixed(1) + 'K</span>' +
        '</div>' +
        '<div class="poi-stem"></div>' +
        '<div class="poi-dot"></div>';

      el.addEventListener("click", function (e) {
        e.stopPropagation();
        flyToCoordinate(poi.lon, poi.lat, 13.6, 62, -25);
      });

      const marker = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([poi.lon, poi.lat])
        .addTo(map);
      poiMarkers.push(marker);
    });

    (courseData.toilets_aid || []).forEach(function (stop) {
      const el = document.createElement("div");
      el.className = "poi-marker-3d toilet-marker-3d";
      el.style.display = toiletsVisible ? "flex" : "none";

      let badgeCls = "cat-toilet";
      let icon = "WC";
      if (stop.kind === "no_toilet") {
        badgeCls = "cat-no-toilet";
        icon = "NO WC";
      } else if (stop.id === "dalgety-cp5") {
        badgeCls = "cat-split-toilet";
        icon = "SPLIT WC";
      } else if (stop.kind === "aid_only") {
        badgeCls = "cat-aid-only";
        icon = "AID";
      }

      el.innerHTML =
        '<div class="poi-badge ' + badgeCls + '">' +
          '<span>' + icon + ' · ' + stop.shortName + '</span>' +
          '<span style="opacity:0.8;font-family:var(--font-mono);font-size:9px;">' + stop.course_km.toFixed(1) + 'K</span>' +
        '</div>' +
        '<div class="poi-stem"></div>' +
        '<div class="poi-dot"></div>';

      el.addEventListener("click", function (e) {
        e.stopPropagation();
        if (window.C2KApp && window.C2KApp.openStopDetailModal) {
          window.C2KApp.openStopDetailModal(stop);
        } else {
          flyToCoordinate(stop.lon, stop.lat, 13.8, 60, -25);
        }
      });

      const tMarker = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([stop.lon, stop.lat])
        .addTo(map);
      toiletMarkers.push(tMarker);
    });

    // Crew Car Live Beacon
    crewEl = document.createElement("div");
    crewEl.className = "marker-3d-crew";
    crewEl.innerHTML =
      '<div class="marker-crew-card"><span>CREW</span><span id="marker-crew-sub" style="font-family:var(--font-mono);font-size:10px;opacity:0.9;">0.0k</span></div>' +
      '<div class="marker-crew-stem"></div>' +
      '<div class="marker-crew-dot"></div>';
    crewEl.addEventListener("click", function (e) {
      e.stopPropagation();
      setCameraMode("follow-crew");
    });
    crewMarker = new maplibregl.Marker({ element: crewEl, anchor: "bottom" })
      .setLngLat([149.87195, -37.09225])
      .addTo(map);

    // Simon Last Fix anchor pin
    const lastFixEl = document.createElement("div");
    lastFixEl.className = "marker-3d-lastfix";
    lastFixEl.style.display = "none";
    lastFixEl.innerHTML =
      '<div class="marker-lastfix-chip">LAST FIX · <span id="marker-lastfix-sub"></span></div>' +
      '<div class="poi-stem"></div>' +
      '<div class="poi-dot"></div>';
    runnerLastFixMarker = new maplibregl.Marker({ element: lastFixEl, anchor: "bottom" })
      .setLngLat([149.87226, -37.09205])
      .addTo(map);

    // Simon Live Beacon
    runnerEl = document.createElement("div");
    runnerEl.className = "marker-3d-runner";
    runnerEl.innerHTML =
      '<div class="marker-runner-card"><span id="marker-runner-title">SIMON</span><span id="marker-runner-sub" style="font-family:var(--font-mono);font-size:10px;opacity:0.95;">0.0k · 4m</span></div>' +
      '<div class="marker-runner-stem"></div>' +
      '<div class="marker-runner-dot"></div>';
    runnerEl.addEventListener("click", function (e) {
      e.stopPropagation();
      setCameraMode("follow-simon");
    });
    runnerMarker = new maplibregl.Marker({ element: runnerEl, anchor: "bottom" })
      .setLngLat([149.87226, -37.09205])
      .addTo(map);

    const hoverEl = document.createElement("div");
    hoverEl.style.cssText =
      "width:12px;height:12px;border-radius:50%;background:#ffffff;border:2.5px solid #ff5a1f;box-shadow:0 0 12px rgba(255,90,31,0.9);pointer-events:none;display:none;";
    scrubHoverMarker = new maplibregl.Marker({ element: hoverEl, anchor: "center" })
      .setLngLat([149.87226, -37.09205])
      .addTo(map);
  }

  function switchToMapLibre(geoState, flyOpts) {
    if (pauseThreeTimer) {
      clearTimeout(pauseThreeTimer);
      pauseThreeTimer = null;
    }
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.stopFlyover();
    }

    activeEngine = "maplibre";
    updateHybridBadge();

    if (map && mapStyleLoaded) {
      const gs = geoState || (window.C2KHybridThreeStage ? window.C2KHybridThreeStage.getCameraGeoState() : null);
      if (gs) {
        map.stop();
        map.jumpTo({
          center: [gs.lon, gs.lat],
          zoom: Math.max(12.28, gs.zoom || 12.6),
          pitch: gs.pitch !== undefined ? gs.pitch : 58,
          bearing: gs.bearing !== undefined ? gs.bearing : -24
        });
      }
      if (lastRunnerState || lastCrewState) {
        updateEntities(lastRunnerState, lastCrewState);
        if (lastRunnerState) updateCompletedRibbonThrottled(lastRunnerState.course_km || 0, true);
      }
      if (flyOpts) {
        isProgrammaticZoomIn = true;
        if (zoomInResetTimer) clearTimeout(zoomInResetTimer);
        const clearFlag = function () {
          isProgrammaticZoomIn = false;
          if (zoomInResetTimer) { clearTimeout(zoomInResetTimer); zoomInResetTimer = null; }
        };
        map.once("moveend", clearFlag);
        zoomInResetTimer = setTimeout(clearFlag, (flyOpts.duration || 1100) + 250);
        map.flyTo(flyOpts);
      }
    }

    const stageEl = document.getElementById("map-stage");
    if (stageEl) stageEl.classList.add("is-street-mode");

    pauseThreeTimer = setTimeout(function () {
      if (activeEngine === "maplibre" && window.C2KHybridThreeStage) {
        window.C2KHybridThreeStage.setActive(false);
      }
    }, CROSSFADE_PAUSE_MS);
  }

  function switchToThree(geoState, nextThreeAction) {
    if (pauseThreeTimer) {
      clearTimeout(pauseThreeTimer);
      pauseThreeTimer = null;
    }
    isProgrammaticZoomIn = false;
    if (zoomInResetTimer) {
      clearTimeout(zoomInResetTimer);
      zoomInResetTimer = null;
    }

    activeEngine = "three";
    updateHybridBadge();
    if (map) map.stop();

    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.setActive(true);
      if (geoState) {
        window.C2KHybridThreeStage.setCameraFromGeoState(geoState, 0);
      }
      if (lastRunnerState || lastCrewState) {
        window.C2KHybridThreeStage.updateEntities(lastRunnerState, lastCrewState);
      }
    }

    const stageEl = document.getElementById("map-stage");
    if (stageEl) stageEl.classList.remove("is-street-mode");

    if (typeof nextThreeAction === "function") {
      nextThreeAction();
    }
  }

  function init(containerId, data, onReady) {
    courseData = data;
    cameraMode = "overview";
    activeEngine = "three";
    updateHybridBadge();

    function fireReadyOnce() {
      if (window.C2KHybridThreeStage && window.C2KHybridThreeStage.isReady()) {
        window.C2KHybridThreeStage.setTerrainExaggeration(terrainExaggeration);
        window.C2KHybridThreeStage.setImageryLayer(activeImageryMode);
        window.C2KHybridThreeStage.setMilestonesVisible(milestonesVisible);
        window.C2KHybridThreeStage.setToiletsVisible(toiletsVisible);
        if (radarTileUrl && radarVisible) {
          window.C2KHybridThreeStage.updateRadarTileLayer(radarTileUrl, radarVisible);
        }
      }
      if (!readyFired && onReady) {
        readyFired = true;
        onReady(getMapProxy());
      }
    }

    // Stage A: Instant Three.js pre-baked corridor mesh
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.init({
        courseData: courseData,
        onReady: fireReadyOnce,
        onUserInteract: function () {
          releaseAutoCamera();
        },
        onSelectCamera: function (lon, lat, zoom, pitch, bearing) {
          flyToCoordinate(lon, lat, zoom, pitch, bearing);
        },
        onRequestStreetZoom: function (geoState) {
          if (activeEngine !== "three") return;
          if (cameraMode === "flyover") return;
          switchToMapLibre(geoState, null);
        }
      });
    }

    // Stage B: Quiet MapLibre GL street satellite engine underneath
    const isMobileStage = window.innerWidth <= 1024;
    map = new maplibregl.Map({
      container: containerId,
      style: buildStyleSpec(),
      center: [149.10, -36.82],
      zoom: 8.28,
      minZoom: 7.5,
      maxZoom: 19.0,
      maxBounds: COURSE_MAX_BOUNDS,
      pitch: 48,
      bearing: -24,
      maxPitch: 78,
      antialias: !isMobileStage,
      fadeDuration: 120,
      maxTileCacheSize: isMobileStage ? 240 : 1200,
      maxTileCacheZoomLevels: isMobileStage ? 4 : 6,
      cancelPendingTileRequestsWhileZooming: true,
      attributionControl: false,
      hash: false
    });

    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("style.load", function () {
      mapStyleLoaded = true;
      setupCourseAndWebGLLayers();
      setupCleanBeacons();
      updateZoomDeclutter();
      updateCompassNeedle();
      setImageryLayer(activeImageryMode);
      setMilestonesVisible(milestonesVisible);
      setToiletsVisible(toiletsVisible);
      if (radarTileUrl && radarVisible) {
        updateRadarTileLayer(radarTileUrl, radarVisible);
      }
      if (lastRunnerState || lastCrewState) {
        updateEntities(lastRunnerState, lastCrewState);
        if (lastRunnerState) updateCompletedRibbonThrottled(lastRunnerState.course_km || 0, true);
      }
      fireReadyOnce();
    });

    map.on("zoom", function () {
      updateZoomDeclutter();
      if (activeEngine === "maplibre" && !isProgrammaticZoomIn && map.getZoom() < STREET_ZOOM_EXIT) {
        const c = map.getCenter();
        switchToThree({
          lon: c.lng,
          lat: c.lat,
          zoom: map.getZoom(),
          pitch: map.getPitch(),
          bearing: map.getBearing()
        });
      }
    });

    map.on("rotate", updateCompassNeedle);

    ["dragstart", "rotatestart", "pitchstart", "wheel"].forEach(function (evName) {
      map.on(evName, function (e) {
        if (e && e.originalEvent) {
          velBrg = 0;
          velPitch = 0;
          velPanX = 0;
          velPanY = 0;
          if (activeEngine === "maplibre") releaseAutoCamera();
        }
      });
    });

    map.on("click", function (e) {
      if (mapPinPickCallback && e && e.lngLat) {
        const cb = mapPinPickCallback;
        mapPinPickCallback = null;
        map.getCanvas().style.cursor = "";
        if (window.C2KHybridThreeStage) window.C2KHybridThreeStage.enableMapPinPick(null);
        cb({ lat: e.lngLat.lat, lon: e.lngLat.lng });
      }
    });

    initMouseOrbitController();
    requestAnimationFrame(tickCameraDirector);
    return getMapProxy();
  }

  function updateCompletedRibbonThrottled(courseKm, force) {
    if (!map || !mapStyleLoaded || !map.getSource("c2k-route-completed") || !courseData) return;
    const now = performance.now();
    if (!force && Math.abs(courseKm - lastCompletedUpdateKm) < 2.0 && now - lastCompletedUpdateTime < 2000) {
      return;
    }
    lastCompletedUpdateKm = courseKm;
    lastCompletedUpdateTime = now;

    const track = courseData.track;
    const coords = [];
    for (let i = 0; i < track.length; i++) {
      coords.push([track[i][0], track[i][1]]);
      if (track[i][3] >= courseKm) break;
    }
    if (coords.length < 2) {
      coords.push(coords[0] || [149.87226, -37.09205]);
    }
    map.getSource("c2k-route-completed").setData({
      type: "Feature",
      geometry: { type: "LineString", coordinates: coords }
    });
  }

  function updateEntities(runnerState, crewState) {
    if (runnerState) lastRunnerState = runnerState;
    if (crewState) lastCrewState = crewState;

    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.updateEntities(runnerState, crewState);
    }

    if (!map || !mapStyleLoaded) return;

    if (runnerState && runnerMarker) {
      runnerMarker.setLngLat([runnerState.lon, runnerState.lat]);
      const isHyp = runnerState.epistemic === "HYPOTHESIS_PACE_ESTIMATE";
      if (runnerEl) runnerEl.classList.toggle("is-hypothesis", isHyp);
      const titleEl = document.getElementById("marker-runner-title");
      if (titleEl) titleEl.textContent = isHyp ? "SIMON (EST.)" : "SIMON";
      const sub = document.getElementById("marker-runner-sub");
      if (sub) {
        sub.textContent = (runnerState.course_km || 0).toFixed(1) + "k · " + Math.round(runnerState.ele_m || 0) + "m";
      }
      if (runnerLastFixMarker) {
        const lfEl = runnerLastFixMarker.getElement();
        if (isHyp && runnerState.confirmed_lon !== undefined && runnerState.confirmed_lat !== undefined) {
          runnerLastFixMarker.setLngLat([runnerState.confirmed_lon, runnerState.confirmed_lat]);
          lfEl.style.display = "flex";
          const lfSub = document.getElementById("marker-lastfix-sub");
          if (lfSub) {
            lfSub.textContent = runnerState.fix_age_text || ((runnerState.confirmed_km || 0).toFixed(1) + "k");
          }
        } else {
          lfEl.style.display = "none";
        }
      }
      if (activeEngine === "maplibre") {
        updateCompletedRibbonThrottled(runnerState.course_km || 0, false);
      }
    }

    if (crewState && crewMarker) {
      crewMarker.setLngLat([crewState.lon, crewState.lat]);
      const csub = document.getElementById("marker-crew-sub");
      if (csub) {
        csub.textContent =
          (crewState.course_km || 0).toFixed(1) + "k" +
          (crewState.speed_kmh > 1 ? " · " + Math.round(crewState.speed_kmh) + "k/h" : "");
      }
    }
  }

  function setImageryLayer(mode) {
    activeImageryMode = mode === "relief" ? "relief" : mode === "esri" ? "esri" : "google";
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.setImageryLayer(activeImageryMode);
    }
    if (!map || !mapStyleLoaded) return;
    if (map.getLayer("layer-google")) {
      map.setLayoutProperty("layer-google", "visibility", activeImageryMode === "google" ? "visible" : "none");
    }
    if (map.getLayer("layer-relief")) {
      map.setLayoutProperty("layer-relief", "visibility", activeImageryMode === "relief" ? "visible" : "none");
    }
    if (map.getLayer("layer-esri")) {
      map.setLayoutProperty("layer-esri", "visibility", activeImageryMode === "esri" ? "visible" : "none");
    }
    if (map.getLayer("layer-hillshade")) {
      map.setLayoutProperty("layer-hillshade", "visibility", activeImageryMode === "relief" ? "visible" : "none");
      map.setPaintProperty("layer-hillshade", "hillshade-exaggeration", activeImageryMode === "relief" ? 0.52 : 0.0);
    }
  }

  function setTerrainExaggeration(val) {
    terrainExaggeration = Math.max(1.0, Math.min(3.5, parseFloat(val) || 2.2));
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.setTerrainExaggeration(terrainExaggeration);
    }
    if (map && mapStyleLoaded) {
      map.setTerrain({ source: "terrain-dem", exaggeration: terrainExaggeration });
    }
  }

  function setMilestonesVisible(vis) {
    milestonesVisible = !!vis;
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.setMilestonesVisible(milestonesVisible);
    }
    if (map && mapStyleLoaded && map.getLayer("c2k-milestones-circles")) {
      map.setLayoutProperty("c2k-milestones-circles", "visibility", milestonesVisible ? "visible" : "none");
    }
    poiMarkers.forEach(function (m) {
      m.getElement().style.display = milestonesVisible ? "flex" : "none";
    });
  }

  function setToiletsVisible(vis) {
    toiletsVisible = !!vis;
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.setToiletsVisible(toiletsVisible);
    }
    toiletMarkers.forEach(function (m) {
      m.getElement().style.display = toiletsVisible ? "flex" : "none";
    });
  }

  function isToiletsVisible() {
    return toiletsVisible;
  }

  function updateRadarTileLayer(tileUrlTemplate, visible) {
    radarTileUrl = tileUrlTemplate;
    radarVisible = visible !== undefined ? visible : radarVisible;

    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.updateRadarTileLayer(radarTileUrl, radarVisible);
    }
    if (!map || !mapStyleLoaded) return;

    if (map.getLayer("layer-bom-radar")) map.removeLayer("layer-bom-radar");
    if (map.getSource("source-bom-radar")) map.removeSource("source-bom-radar");

    if (radarTileUrl && radarVisible) {
      map.addSource("source-bom-radar", {
        type: "raster",
        tiles: [radarTileUrl],
        tileSize: 256,
        maxzoom: 7,
        attribution: "Australian BoM / RainViewer Live Radar"
      });
      map.addLayer(
        {
          id: "layer-bom-radar",
          type: "raster",
          source: "source-bom-radar",
          paint: { "raster-opacity": 0.48, "raster-fade-duration": 0 }
        },
        "c2k-route-casing"
      );
    }
  }

  let lastSkyMode = "day";
  function updateSkyForSolarAltitude(solarAltDeg) {
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.updateSkyForSolarAltitude(solarAltDeg);
    }
    if (!map || !mapStyleLoaded) return;
    const targetMode = solarAltDeg < -4 ? "night" : solarAltDeg < 12 ? "golden" : "day";
    if (targetMode === lastSkyMode) return;
    lastSkyMode = targetMode;

    if (targetMode === "night") {
      map.setSky({
        "sky-color": "#04070e",
        "sky-horizon-blend": 0.55,
        "horizon-color": "#09111f",
        "horizon-fog-blend": 0.78,
        "fog-color": "#060b16",
        "fog-ground-blend": 0.25
      });
    } else if (targetMode === "golden") {
      map.setSky({
        "sky-color": "#111828",
        "sky-horizon-blend": 0.62,
        "horizon-color": "#8a4b2a",
        "horizon-fog-blend": 0.76,
        "fog-color": "#281c24",
        "fog-ground-blend": 0.22
      });
    } else {
      map.setSky({
        "sky-color": "#06090f",
        "sky-horizon-blend": 0.65,
        "horizon-color": "#16263d",
        "horizon-fog-blend": 0.82,
        "fog-color": "#0e1726",
        "fog-ground-blend": 0.22
      });
    }
  }

  function flyToCoordinate(lon, lat, zoom, pitch, bearing) {
    setCameraMode("free");
    const targetZoom = zoom !== undefined ? zoom : 13.4;
    const targetPitch = pitch !== undefined ? pitch : 62;
    const targetBearing = bearing !== undefined ? bearing : -25;

    if (targetZoom >= 12.2) {
      const geo = activeEngine === "three" && window.C2KHybridThreeStage
        ? window.C2KHybridThreeStage.getCameraGeoState()
        : null;
      switchToMapLibre(geo, {
        center: [lon, lat],
        zoom: targetZoom,
        pitch: targetPitch,
        bearing: targetBearing,
        duration: 1200,
        essential: true
      });
    } else {
      const geo = activeEngine === "maplibre" && map
        ? {
            lon: map.getCenter().lng,
            lat: map.getCenter().lat,
            zoom: map.getZoom(),
            pitch: map.getPitch(),
            bearing: map.getBearing()
          }
        : null;
      switchToThree(geo, function () {
        if (window.C2KHybridThreeStage) {
          window.C2KHybridThreeStage.flyToCoordinate(lon, lat, targetZoom, targetPitch, targetBearing);
        }
      });
    }
  }

  function syncCameraButtons() {
    document.querySelectorAll("[data-cam-mode]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-cam-mode") === cameraMode);
    });
    const flyBtn = document.getElementById("btn-fly-course");
    if (flyBtn) {
      const labelSpan = flyBtn.querySelector("span");
      if (labelSpan) {
        labelSpan.textContent = cameraMode === "flyover" ? "Pause Heli Tour" : "241K Heli Tour";
      } else {
        flyBtn.textContent = cameraMode === "flyover" ? "Pause Heli Tour" : "241K Heli Tour";
      }
    }
  }

  function setCameraMode(mode) {
    cameraMode = mode;
    syncCameraButtons();

    if (!window.C2KApp) return;

    if (mode === "overview") {
      const geo = activeEngine === "maplibre" && map
        ? { lon: map.getCenter().lng, lat: map.getCenter().lat, zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() }
        : null;
      switchToThree(geo, function () {
        if (window.C2KHybridThreeStage) window.C2KHybridThreeStage.resetOverview(false);
      });
    } else if (mode === "flyover") {
      const geo = activeEngine === "maplibre" && map
        ? { lon: map.getCenter().lng, lat: map.getCenter().lat, zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() }
        : null;
      switchToThree(geo, function () {
        if (window.C2KHybridThreeStage) window.C2KHybridThreeStage.startFlyover();
      });
    } else if (mode === "follow-simon") {
      const r = window.C2KApp.getCurrentRunnerState();
      if (r) {
        smoothCamLon = r.lon;
        smoothCamLat = r.lat;
        const ahead = getPointAtKm((r.course_km || 0) + 18.0) || [r.lon, r.lat];
        const macroBrg = computeMacroBearing(r.lon, r.lat, ahead[0], ahead[1]);
        switchToMapLibre(null, {
          center: [r.lon, r.lat],
          zoom: Math.max(13.6, map ? map.getZoom() : 13.6),
          pitch: 58,
          bearing: macroBrg,
          duration: 1050,
          essential: true
        });
      }
    } else if (mode === "follow-crew") {
      const c = window.C2KApp.getCurrentCrewState();
      if (c) {
        smoothCamLon = c.lon;
        smoothCamLat = c.lat;
        switchToMapLibre(null, {
          center: [c.lon, c.lat],
          zoom: Math.max(13.4, map ? map.getZoom() : 13.4),
          pitch: 58,
          bearing: -24,
          duration: 1050,
          essential: true
        });
      }
    } else if (mode === "dual-frame") {
      const r = window.C2KApp.getCurrentRunnerState();
      const c = window.C2KApp.getCurrentCrewState();
      if (r && c && window.C2KTelemetryClient) {
        const sepKm = window.C2KTelemetryClient.haversineKm(r.lat, r.lon, c.lat, c.lon);
        cameraMode = "free";
        syncCameraButtons();
        if (sepKm > 16.0) {
          const geo = activeEngine === "maplibre" && map
            ? { lon: map.getCenter().lng, lat: map.getCenter().lat, zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() }
            : null;
          switchToThree(geo, function () {
            if (window.C2KHybridThreeStage) window.C2KHybridThreeStage.fitDualBounds(r, c);
          });
        } else {
          switchToMapLibre(null, null);
          if (map) {
            const bounds = new maplibregl.LngLatBounds();
            bounds.extend([r.lon, r.lat]);
            bounds.extend([c.lon, c.lat]);
            isProgrammaticZoomIn = true;
            map.once("moveend", function () { isProgrammaticZoomIn = false; });
            const isNarrow = window.innerWidth <= 1024;
            const fitPad = isNarrow
              ? {
                  top: 76,
                  bottom: document.body.classList.contains("mob-profile-collapsed") ? 104 : 228,
                  left: 34,
                  right: 34
                }
              : {
                  top: 90,
                  bottom: 220,
                  left: document.body.classList.contains("left-dock-collapsed") ? 60 : 360,
                  right: document.body.classList.contains("right-dock-collapsed") ? 60 : 340
                };
            map.fitBounds(bounds, {
              padding: fitPad,
              pitch: 58,
              maxZoom: 14.0,
              duration: 1100
            });
          }
        }
      }
    } else {
      if (window.C2KHybridThreeStage) {
        window.C2KHybridThreeStage.stopFlyover();
      }
    }
  }

  function zoomIn() {
    releaseAutoCamera();
    if (activeEngine === "three" && window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.zoomByFactor(0.76);
    } else if (map) {
      map.zoomIn({ duration: 280 });
    }
  }

  function zoomOut() {
    releaseAutoCamera();
    if (activeEngine === "three" && window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.zoomByFactor(1.32);
    } else if (map) {
      map.zoomOut({ duration: 280 });
    }
  }

  function resetNorth() {
    releaseAutoCamera();
    if (activeEngine === "three" && window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.resetNorth();
    } else if (map) {
      map.easeTo({ bearing: 0, duration: 420, essential: true });
    }
  }

  function setOrbitDragMode(val) {
    orbitDragMode = !!val;
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.setOrbitDragMode(orbitDragMode);
    }
    return orbitDragMode;
  }

  function isOrbitDragMode() {
    return orbitDragMode;
  }

  function getCameraMode() {
    return cameraMode;
  }

  function toggleHybridEngine() {
    releaseAutoCamera();
    if (activeEngine === "three") {
      const geo = window.C2KHybridThreeStage ? window.C2KHybridThreeStage.getCameraGeoState() : { lon: 149.3912, lat: -36.8432, pitch: 58, bearing: -24 };
      switchToMapLibre(geo, {
        center: [geo.lon, geo.lat],
        zoom: Math.max(12.8, geo.zoom || 12.8),
        pitch: Math.min(72, Math.max(40, geo.pitch || 58)),
        bearing: geo.bearing || -24,
        duration: 750,
        essential: true
      });
    } else if (map) {
      const c = map.getCenter();
      switchToThree({
        lon: c.lng,
        lat: c.lat,
        zoom: Math.min(11.3, map.getZoom()),
        pitch: map.getPitch(),
        bearing: map.getBearing()
      });
    }
    return activeEngine;
  }

  function getPointAtKm(km) {
    if (!courseData || !courseData.track || !courseData.track.length) return null;
    const track = courseData.track;
    if (km <= 0) return track[0];
    if (km >= track[track.length - 1][3]) return track[track.length - 1];
    let lo = 0;
    let hi = track.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (track[mid][3] < km) lo = mid + 1;
      else hi = mid;
    }
    const p1 = track[Math.max(0, lo - 1)];
    const p2 = track[lo];
    const span = p2[3] - p1[3];
    const t = span > 0.0001 ? (km - p1[3]) / span : 0;
    return [
      p1[0] + (p2[0] - p1[0]) * t,
      p1[1] + (p2[1] - p1[1]) * t,
      p1[2] + (p2[2] - p1[2]) * t,
      km,
      p1[4] + (p2[4] - p1[4]) * t,
      p2[5]
    ];
  }

  function tickCameraDirector(now) {
    const dt = Math.min(0.05, (now - lastFrameTime) / 1000);
    lastFrameTime = now;

    if (!document.hidden && activeEngine === "maplibre" && map && window.C2KApp && !map.isMoving() && !dragAction) {
      if (cameraMode === "follow-simon") {
        const r = window.C2KApp.getCurrentRunnerState();
        if (r) {
          if (smoothCamLon === null || smoothCamLat === null) {
            smoothCamLon = r.lon;
            smoothCamLat = r.lat;
            map.setCenter([smoothCamLon, smoothCamLat]);
          } else if (Math.hypot(r.lon - smoothCamLon, r.lat - smoothCamLat) > 0.000015) {
            const blend = Math.min(1.0, dt * 8.0);
            smoothCamLon += (r.lon - smoothCamLon) * blend;
            smoothCamLat += (r.lat - smoothCamLat) * blend;
            map.setCenter([smoothCamLon, smoothCamLat]);
          }
        }
      } else if (cameraMode === "follow-crew") {
        const c = window.C2KApp.getCurrentCrewState();
        if (c) {
          if (smoothCamLon === null || smoothCamLat === null) {
            smoothCamLon = c.lon;
            smoothCamLat = c.lat;
            map.setCenter([smoothCamLon, smoothCamLat]);
          } else if (Math.hypot(c.lon - smoothCamLon, c.lat - smoothCamLat) > 0.000015) {
            const blend = Math.min(1.0, dt * 8.0);
            smoothCamLon += (c.lon - smoothCamLon) * blend;
            smoothCamLat += (c.lat - smoothCamLat) * blend;
            map.setCenter([smoothCamLon, smoothCamLat]);
          }
        }
      } else if (cameraMode === "free") {
        const decay = Math.exp(-8.5 * dt);
        if (Math.abs(velBrg) > 0.25 || Math.abs(velPitch) > 0.25) {
          map.jumpTo({
            bearing: map.getBearing() + velBrg * dt,
            pitch: Math.max(0, Math.min(78, map.getPitch() + velPitch * dt))
          });
          velBrg *= decay;
          velPitch *= decay;
          updateCompassNeedle();
        } else {
          velBrg = 0;
          velPitch = 0;
        }

        if (Math.hypot(velPanX, velPanY) > 4) {
          map.panBy([-velPanX * dt, -velPanY * dt], { animate: false });
          velPanX *= decay;
          velPanY *= decay;
        } else {
          velPanX = 0;
          velPanY = 0;
        }
      }
    }

    requestAnimationFrame(tickCameraDirector);
  }

  function showScrubHoverPin(lon, lat, visible) {
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.showScrubHoverPin(lon, lat, visible && activeEngine === "three");
    }
    if (scrubHoverMarker) {
      scrubHoverMarker.getElement().style.display = visible && activeEngine === "maplibre" ? "block" : "none";
      if (visible && lon !== undefined && lat !== undefined) {
        scrubHoverMarker.setLngLat([lon, lat]);
      }
    }
  }

  function enableMapPinPick(callback) {
    mapPinPickCallback = typeof callback === "function" ? callback : null;
    if (window.C2KHybridThreeStage) {
      window.C2KHybridThreeStage.enableMapPinPick(mapPinPickCallback);
    }
    if (map) {
      map.getCanvas().style.cursor = mapPinPickCallback ? "crosshair" : "";
    }
  }

  function getMapProxy() {
    if (activeEngine === "three" && window.C2KHybridThreeStage) {
      return {
        getZoom: function () { return window.C2KHybridThreeStage.getCameraGeoState().zoom; },
        getPitch: function () { return window.C2KHybridThreeStage.getCameraGeoState().pitch; },
        getBearing: function () { return window.C2KHybridThreeStage.getCameraGeoState().bearing; },
        project: function (lngLat) {
          return window.C2KHybridThreeStage.projectLonLat(lngLat[0], lngLat[1], 450);
        }
      };
    }
    return map;
  }

  return {
    init: init,
    getMap: getMapProxy,
    getActiveEngine: function () { return activeEngine; },
    toggleHybridEngine: toggleHybridEngine,
    updateEntities: updateEntities,
    setImageryLayer: setImageryLayer,
    setTerrainExaggeration: setTerrainExaggeration,
    setMilestonesVisible: setMilestonesVisible,
    setToiletsVisible: setToiletsVisible,
    isToiletsVisible: isToiletsVisible,
    updateRadarTileLayer: updateRadarTileLayer,
    updateSkyForSolarAltitude: updateSkyForSolarAltitude,
    flyToCoordinate: flyToCoordinate,
    setCameraMode: setCameraMode,
    getCameraMode: getCameraMode,
    zoomIn: zoomIn,
    zoomOut: zoomOut,
    resetNorth: resetNorth,
    setOrbitDragMode: setOrbitDragMode,
    isOrbitDragMode: isOrbitDragMode,
    getPointAtKm: getPointAtKm,
    showScrubHoverPin: showScrubHoverPin,
    enableMapPinPick: enableMapPinPick
  };
})();
