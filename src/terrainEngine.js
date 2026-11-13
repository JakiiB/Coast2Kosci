/**
 * Coast to Kosciuszko (C2K) - Locked 60 FPS 3D Terrain, Zero-Pop Mesh & Camera Director Engine
 * Key Architectural Optimizations:
 *  1. Zero-Pop 3D DEM Mesh: Caps DEM tessellation at maxzoom 11 so MapLibre never tears down
 *     and rebuilds 3D terrain geometry while flying or zooming at Zoom 12 - 18.
 *  2. Dual Imagery Pipeline: Google Earth 3D Satellite primary + Esri World Imagery instant fallback.
 *  3. Locked minZoom (8.3) and tight corridor bounds for the Boydtown Beach -> Mt Kosciuszko spine.
 *  4. Clean POI stems, hypothesis last-confirmed anchor pin, and 10K GPU circle ticks.
 */

window.C2KTerrainEngine = (function () {
  let map = null;
  let courseData = null;
  let terrainExaggeration = 1.4;
  let cameraMode = "follow-simon"; // follow-simon | follow-crew | dual-frame | flyover | overview | free
  let flyoverProgressKm = 0;
  let flyoverSmoothBearing = -35;
  let smoothCamLon = null;
  let smoothCamLat = null;
  let lastFrameTime = performance.now();

  let runnerMarker = null;
  let runnerEl = null;
  let runnerLastFixMarker = null;
  let crewMarker = null;
  let crewEl = null;
  let scrubHoverMarker = null;
  let poiMarkers = [];
  let milestonesVisible = true;
  let radarTileUrl = null;
  let radarVisible = false;
  let lastCompletedUpdateKm = -999;
  let lastCompletedUpdateTime = 0;
  let mapPinPickCallback = null;

  // Generous pan bounds for tilted 3D frustum (prevents horizon-ray zoom lock while keeping camera over SE NSW)
  const COURSE_MAX_BOUNDS = [
    [143.00, -40.50],
    [154.50, -32.50]
  ];

  function angleLerp(current, target, t) {
    let diff = ((target - current + 540) % 360) - 180;
    return (current + diff * t + 360) % 360;
  }

  function computeMacroBearing(lon1, lat1, lon2, lat2) {
    const dLon = ((lon2 - lon1) * Math.PI) / 180.0;
    const phi1 = (lat1 * Math.PI) / 180.0;
    const phi2 = (lat2 * Math.PI) / 180.0;
    const y = Math.sin(dLon) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
    return ((Math.atan2(y, x) * 180.0) / Math.PI + 360.0) % 360.0;
  }

  function setPreloaderProgress(pct, stageText, countText) {
    const barFill = document.getElementById("preloader-bar-fill");
    const pctEl = document.getElementById("preloader-pct");
    const stageEl = document.getElementById("preloader-stage");
    const countsEl = document.getElementById("preloader-counts");
    if (barFill) barFill.style.width = pct + "%";
    if (pctEl) pctEl.textContent = pct + "%";
    if (stageEl && stageText) stageEl.textContent = stageText;
    if (countsEl && countText) countsEl.textContent = countText;
  }

  function dismissPreloader() {
    const overlay = document.getElementById("c2k-preloader");
    if (!overlay || overlay.classList.contains("hidden-preloader")) return;
    setPreloaderProgress(100, "3D Terrain & Broadcast Telemetry Ready", "Corridor synced");
    overlay.classList.add("hidden-preloader");
  }

  function buildCorridorFogMaskGeoJSON() {
    const lonA = 148.32, latA = -36.44; // Mt Kosciuszko / Main Range end
    const lonB = 149.85, latB = -37.08; // Boydtown Beach / Twofold Bay end
    const cosLat = Math.cos((-36.76 * Math.PI) / 180.0);

    const ux = (lonB - lonA) * cosLat;
    const uy = latB - latA;
    const len = Math.hypot(ux, uy) || 1.0;
    const tx = ux / len;
    const ty = uy / len;
    const nx = -ty;
    const ny = tx;

    function makeStadiumRing(radiusDeg) {
      const pts = [];
      const steps = 40;
      for (let i = 0; i <= steps; i++) {
        const ang = -Math.PI / 2 + (Math.PI * i) / steps;
        const c = Math.cos(ang), s = Math.sin(ang);
        const dx = radiusDeg * (c * tx + s * nx);
        const dy = radiusDeg * (c * ty + s * ny);
        pts.push([lonB + dx / cosLat, latB + dy]);
      }
      for (let i = 0; i <= steps; i++) {
        const ang = Math.PI / 2 + (Math.PI * i) / steps;
        const c = Math.cos(ang), s = Math.sin(ang);
        const dx = radiusDeg * (c * tx + s * nx);
        const dy = radiusDeg * (c * ty + s * ny);
        pts.push([lonA + dx / cosLat, latA + dy]);
      }
      pts.push(pts[0]);
      return pts;
    }

    const outerWorld = [
      [136.0, -45.0],
      [162.0, -45.0],
      [162.0, -28.0],
      [136.0, -28.0],
      [136.0, -45.0]
    ];

    // Single outer polygon + narrow edge-softening ring safely within MapLibre tile buffer
    return {
      outerMask: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: { opacity: 1.0 },
            geometry: {
              type: "Polygon",
              coordinates: [outerWorld, makeStadiumRing(0.44)]
            }
          }
        ]
      },
      featherLines: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: { op: 0.85 },
            geometry: {
              type: "LineString",
              coordinates: makeStadiumRing(0.435)
            }
          }
        ]
      }
    };
  }

  function buildStyleSpec() {
    const CORRIDOR_SOURCE_BOUNDS = [147.35, -37.80, 150.80, -35.70];

    return {
      version: 8,
      name: "C2K Google & Esri 3D Broadcast Terrain",
      sources: {
        "terrain-dem": {
          type: "raster-dem",
          tiles: [
            "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
          ],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 11,
          bounds: CORRIDOR_SOURCE_BOUNDS,
          encoding: "terrarium"
        },
        "esri-sat": {
          type: "raster",
          tiles: [
            "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          ],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 18,
          bounds: CORRIDOR_SOURCE_BOUNDS,
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
          bounds: CORRIDOR_SOURCE_BOUNDS,
          attribution: "Google Earth 3D Satellite"
        }
      },
      terrain: {
        source: "terrain-dem",
        exaggeration: terrainExaggeration
      },
      sky: {
        "sky-color": "#09101d",
        "sky-horizon-blend": 0.72,
        "horizon-color": "#132238",
        "horizon-fog-blend": 0.92,
        "fog-color": "#09101d",
        "fog-ground-blend": 0.32
      },
      layers: [
        {
          id: "bg-void",
          type: "background",
          paint: { "background-color": "#09101d" }
        },
        {
          id: "layer-esri",
          type: "raster",
          source: "esri-sat",
          layout: { visibility: "none" },
          paint: {
            "raster-contrast": 0.05,
            "raster-saturation": 0.04,
            "raster-fade-duration": 0
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
            "raster-fade-duration": 0
          }
        }
      ]
    };
  }

  function updateZoomDeclutter() {
    if (!map) return;
    const c = map.getContainer();
    if (c) {
      c.classList.toggle("is-overview-zoom", map.getZoom() < 10.3);
    }
  }

  function init(containerId, data, onReady) {
    courseData = data;
    setPreloaderProgress(35, "Initializing 3D DEM mesh & satellite corridor...", "Streaming terrain");
    setTimeout(dismissPreloader, 3800); // Safety ceiling for slow cellular networks

    const initSimonPt = getPointAtKm(45.0) || [149.56151, -36.95977];
    const aheadSimonPt = getPointAtKm(60.0) || [149.43437, -36.89133];
    const initBearing = computeMacroBearing(initSimonPt[0], initSimonPt[1], aheadSimonPt[0], aheadSimonPt[1]);
    smoothCamLon = initSimonPt[0];
    smoothCamLat = initSimonPt[1];
    flyoverSmoothBearing = initBearing;
    cameraMode = "follow-simon";

    map = new maplibregl.Map({
      container: containerId,
      style: buildStyleSpec(),
      center: [initSimonPt[0], initSimonPt[1]],
      zoom: 13.7,
      minZoom: 8.3,
      maxZoom: 19.0,
      maxBounds: COURSE_MAX_BOUNDS,
      pitch: 58,
      bearing: initBearing,
      maxPitch: 66,
      antialias: false,
      fadeDuration: 0,
      maxTileCacheSize: 1200,
      maxTileCacheZoomLevels: 6,
      cancelPendingTileRequestsWhileZooming: true,
      hash: false
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.once("idle", dismissPreloader);

    map.on("style.load", function () {
      setPreloaderProgress(75, "Building 241.3 km spine & beacons...", "Mounting 3D route");
      setupCourseAndWebGLLayers();
      setupCleanBeacons();
      updateZoomDeclutter();
      if (onReady) onReady(map);
    });

    map.on("zoom", updateZoomDeclutter);

    // Optional click-to-pick coordinate handler for Crew Check-In dialog
    map.on("click", function (e) {
      if (mapPinPickCallback && e && e.lngLat) {
        const cb = mapPinPickCallback;
        mapPinPickCallback = null;
        map.getCanvas().style.cursor = "";
        cb({ lat: e.lngLat.lat, lon: e.lngLat.lng });
      }
    });

    // Only exit Follow mode when user left-click drags to pan the map
    map.on("dragstart", function (e) {
      if (cameraMode !== "free" && e && e.originalEvent && e.originalEvent.button === 0) {
        setCameraMode("free");
      }
    });

    requestAnimationFrame(tickCameraDirector);
    return map;
  }

  function setupCourseAndWebGLLayers() {
    if (!courseData || !courseData.track) return;

    const fogData = buildCorridorFogMaskGeoJSON();
    map.addSource("c2k-corridor-fog-mask", {
      type: "geojson",
      data: fogData.outerMask
    });
    map.addSource("c2k-corridor-fog-feather", {
      type: "geojson",
      data: fogData.featherLines
    });

    map.addLayer({
      id: "c2k-corridor-fog-mask-layer",
      type: "fill",
      source: "c2k-corridor-fog-mask",
      paint: {
        "fill-color": "#09101d",
        "fill-opacity": 1.0
      }
    });

    map.addLayer({
      id: "c2k-corridor-fog-feather-layer",
      type: "line",
      source: "c2k-corridor-fog-feather",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#09101d",
        "line-opacity": ["get", "op"],
        "line-width": 28,
        "line-blur": 22
      }
    });

    const fullCoords = courseData.track.map(function (pt) {
      return [pt[0], pt[1]];
    });

    map.addSource("c2k-route-full", {
      type: "geojson",
      data: {
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: fullCoords
        }
      }
    });

    map.addSource("c2k-route-completed", {
      type: "geojson",
      data: {
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [fullCoords[0], fullCoords[0]]
        }
      }
    });

    // Dark casing for crisp visibility over snow & bushland
    map.addLayer({
      id: "c2k-route-casing",
      type: "line",
      source: "c2k-route-full",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#040711",
        "line-width": ["interpolate", ["linear"], ["zoom"], 9, 5, 13, 8, 16, 12],
        "line-opacity": 0.9
      }
    });

    // Remaining route line (golden amber)
    map.addLayer({
      id: "c2k-route-remaining",
      type: "line",
      source: "c2k-route-full",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#fbbf24",
        "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2.6, 13, 4.4, 16, 6.8],
        "line-opacity": 0.94
      }
    });

    // Completed route line behind Simon (blaze orange)
    map.addLayer({
      id: "c2k-route-done",
      type: "line",
      source: "c2k-route-completed",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#ff5a1f",
        "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3.6, 13, 5.8, 16, 8.8],
        "line-opacity": 1.0
      }
    });

    // Pure GPU Circle Layer for 10km & Special Milestones (zero external font requests, zero DOM cost)
    const msFeatures = (courseData.milestones || []).map(function (ms) {
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [ms.lon, ms.lat] },
        properties: {
          isSpecial: ms.type === "special" ? 1 : 0,
          km: ms.km
        }
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

    // 1. Only 12 Non-Overlapping Major Race Gate Badges (Start, CP1-CP8, Cow Bail U-Turn, Summit 2,228m)
    // Deduplicate Charlotte Pass (CP8, Cut-Off #3, and Finish are at the exact same spot!)
    const seenCoords = [];
    (courseData.pois || []).forEach(function (poi) {
      const keepCats = ["start", "summit", "checkpoint", "crew_uturn"];
      if (keepCats.indexOf(poi.category) === -1) return;

      // Prevent stacked badges at identical coordinates
      const tooClose = seenCoords.some(function (c) {
        return Math.abs(c[0] - poi.lon) < 0.015 && Math.abs(c[1] - poi.lat) < 0.015;
      });
      if (tooClose && poi.category !== "summit") return;
      seenCoords.push([poi.lon, poi.lat]);

      const el = document.createElement("div");
      el.className = "poi-marker-3d";

      let shortTitle = poi.name
        .replace("Mandatory Checkpoint #1 - Towamba", "CP1 • TOWAMBA")
        .replace("Mandatory Checkpoint #2 - Rocky Hall", "CP2 • ROCKY HALL")
        .replace("Mandatory Checkpoint #3 - Cathcart", "CP3 • CATHCART")
        .replace("Mandatory Checkpoint #4 - Gunningrah Rd & Snowy River Way", "CP4 • GUNNINGRAH")
        .replace("Mandatory Checkpoint #5 - Dalgety", "CP5 • DALGETY (25H GATE)")
        .replace("Mandatory Checkpoint #6 - Jindabyne", "CP6 • JINDABYNE (32.5H GATE)")
        .replace("Mandatory Checkpoint #7 - Perisher Valley", "CP7 • PERISHER")
        .replace("Mandatory Checkpoint #8 - Charlotte Pass", "CP8 & FINISH • CHARLOTTE PASS")
        .replace("Start at Boydtown Beach", "START • BOYDTOWN (0m)")
        .replace("Summit of Mt Kosciuszko", "▲ MT KOSCIUSZKO (2,228m)")
        .replace("Cow Bail Trail", "⚠ COW BAIL (CREW U-TURN)");

      el.innerHTML =
        '<div class="poi-badge cat-' + poi.category + '">' +
          '<span>' + shortTitle + '</span>' +
          '<span style="opacity:0.75;font-family:var(--font-mono);font-size:9px;">' + poi.course_km.toFixed(1) + 'K</span>' +
        '</div>' +
        '<div class="poi-stem"></div>' +
        '<div class="poi-dot"></div>';

      el.addEventListener("click", function (e) {
        e.stopPropagation();
        flyToCoordinate(poi.lon, poi.lat, 13.4, 64, -25);
      });

      const marker = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([poi.lon, poi.lat])
        .addTo(map);
      poiMarkers.push(marker);
    });

    // 2. Crew Car Live 3D Beacon
    crewEl = document.createElement("div");
    crewEl.className = "marker-3d-crew";
    crewEl.innerHTML =
      '<div class="marker-crew-card">' +
        '<span>🚙 CREW CAR</span>' +
        '<span id="marker-crew-sub" style="font-family:var(--font-mono);font-size:10px;color:#a5f3fc;">0.0 KM</span>' +
      '</div>' +
      '<div class="marker-crew-stem"></div>' +
      '<div class="marker-crew-dot"></div>';
    crewEl.addEventListener("click", function (e) {
      e.stopPropagation();
      setCameraMode("follow-crew");
    });
    crewMarker = new maplibregl.Marker({ element: crewEl, anchor: "bottom" })
      .setLngLat([149.87195, -37.09225])
      .addTo(map);

    // 3. Simon Last Confirmed Fix Anchor Pin (visible only during Hypothesis Pace Estimate)
    const lastFixEl = document.createElement("div");
    lastFixEl.className = "marker-3d-lastfix";
    lastFixEl.style.display = "none";
    lastFixEl.innerHTML =
      '<div class="marker-lastfix-card">' +
        '<span>⚓ LAST FIX</span>' +
        '<span id="marker-lastfix-sub" style="font-family:var(--font-mono);font-size:9.5px;opacity:0.85;"></span>' +
      '</div>' +
      '<div class="marker-lastfix-stem"></div>' +
      '<div class="marker-lastfix-dot"></div>';
    runnerLastFixMarker = new maplibregl.Marker({ element: lastFixEl, anchor: "bottom" })
      .setLngLat([149.87226, -37.09205])
      .addTo(map);

    // 4. Simon (Runner) Live 3D Beacon
    runnerEl = document.createElement("div");
    runnerEl.className = "marker-3d-runner";
    runnerEl.innerHTML =
      '<div class="marker-runner-card">' +
        '<span id="marker-runner-title">🏃 SIMON</span>' +
        '<span id="marker-runner-sub" style="font-family:var(--font-mono);font-size:10.5px;background:rgba(0,0,0,0.3);padding:1px 5px;border-radius:3px;">0.0 KM • 4m</span>' +
      '</div>' +
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
      "width:12px;height:12px;border-radius:50%;background:#ffffff;border:2px solid #ff5a1f;box-shadow:0 0 12px #ffffff;pointer-events:none;display:none;";
    scrubHoverMarker = new maplibregl.Marker({ element: hoverEl, anchor: "center" })
      .setLngLat([149.87226, -37.09205])
      .addTo(map);
  }

  function updateCompletedRibbonThrottled(courseKm, force) {
    if (!map || !map.getSource("c2k-route-completed") || !courseData) return;
    if (cameraMode === "flyover" && !force) return;
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
      geometry: {
        type: "LineString",
        coordinates: coords
      }
    });
  }

  function updateEntities(runnerState, crewState) {
    if (!map) return;

    if (runnerState && runnerMarker) {
      runnerMarker.setLngLat([runnerState.lon, runnerState.lat]);
      const isHyp = runnerState.epistemic === "HYPOTHESIS_PACE_ESTIMATE";
      if (runnerEl) {
        runnerEl.classList.toggle("is-hypothesis", isHyp);
      }
      const titleEl = document.getElementById("marker-runner-title");
      if (titleEl) {
        titleEl.textContent = isHyp ? "🏃 SIMON (EST.)" : "🏃 SIMON";
      }
      const sub = document.getElementById("marker-runner-sub");
      if (sub) {
        sub.textContent =
          (runnerState.course_km || 0).toFixed(1) + "K • " + Math.round(runnerState.ele_m || 0) + "m";
      }
      if (runnerLastFixMarker) {
        const lfEl = runnerLastFixMarker.getElement();
        if (isHyp && runnerState.confirmed_lon !== undefined && runnerState.confirmed_lat !== undefined) {
          runnerLastFixMarker.setLngLat([runnerState.confirmed_lon, runnerState.confirmed_lat]);
          lfEl.style.display = "flex";
          const lfSub = document.getElementById("marker-lastfix-sub");
          if (lfSub) {
            lfSub.textContent = runnerState.fix_age_text || ((runnerState.confirmed_km || 0).toFixed(1) + "K");
          }
        } else {
          lfEl.style.display = "none";
        }
      }
      updateCompletedRibbonThrottled(runnerState.course_km || 0, false);
    }

    if (crewState && crewMarker) {
      crewMarker.setLngLat([crewState.lon, crewState.lat]);
      const csub = document.getElementById("marker-crew-sub");
      if (csub) {
        csub.textContent =
          (crewState.speed_kmh > 1 ? Math.round(crewState.speed_kmh) + " km/h" : Math.round(crewState.ele_m || 0) + "m");
      }
    }
  }

  function setImageryLayer(mode) {
    if (!map) return;
    if (map.getLayer("layer-google")) {
      map.setLayoutProperty("layer-google", "visibility", mode === "google" ? "visible" : "none");
    }
    if (map.getLayer("layer-esri")) {
      map.setLayoutProperty("layer-esri", "visibility", mode === "esri" ? "visible" : "none");
    }
  }

  function setTerrainExaggeration(val) {
    terrainExaggeration = parseFloat(val) || 1.4;
    if (map) {
      map.setTerrain({ source: "terrain-dem", exaggeration: terrainExaggeration });
    }
  }

  function setMilestonesVisible(vis) {
    milestonesVisible = !!vis;
    if (map && map.getLayer("c2k-milestones-circles")) {
      map.setLayoutProperty("c2k-milestones-circles", "visibility", milestonesVisible ? "visible" : "none");
    }
    poiMarkers.forEach(function (m) {
      m.getElement().style.display = milestonesVisible ? "flex" : "none";
    });
  }

  function updateRadarTileLayer(tileUrlTemplate, visible) {
    radarTileUrl = tileUrlTemplate;
    radarVisible = visible !== undefined ? visible : radarVisible;
    if (!map || !map.isStyleLoaded()) return;

    if (map.getLayer("layer-bom-radar")) {
      map.removeLayer("layer-bom-radar");
    }
    if (map.getSource("source-bom-radar")) {
      map.removeSource("source-bom-radar");
    }

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
          paint: {
            "raster-opacity": 0.45,
            "raster-fade-duration": 0
          }
        },
        "c2k-route-casing"
      );
    }
  }

  let lastSkyMode = "day";
  function updateSkyForSolarAltitude(solarAltDeg) {
    if (!map || !map.isStyleLoaded()) return;
    const targetMode = solarAltDeg < -4 ? "night" : solarAltDeg < 12 ? "golden" : "day";
    if (targetMode === lastSkyMode) return;
    lastSkyMode = targetMode;

    if (targetMode === "night") {
      map.setSky({
        "sky-color": "#02040a",
        "sky-horizon-blend": 0.5,
        "horizon-color": "#091326",
        "horizon-fog-blend": 0.7,
        "fog-color": "#050914",
        "fog-ground-blend": 0.4
      });
    } else if (targetMode === "golden") {
      map.setSky({
        "sky-color": "#1a1c3b",
        "sky-horizon-blend": 0.55,
        "horizon-color": "#f97316",
        "horizon-fog-blend": 0.65,
        "fog-color": "#431407",
        "fog-ground-blend": 0.35
      });
    } else {
      map.setSky({
        "sky-color": "#0d254c",
        "sky-horizon-blend": 0.45,
        "horizon-color": "#38bdf8",
        "horizon-fog-blend": 0.6,
        "fog-color": "#1e293b",
        "fog-ground-blend": 0.3
      });
    }
  }

  function flyToCoordinate(lon, lat, zoom, pitch, bearing) {
    if (!map) return;
    setCameraMode("free");
    map.flyTo({
      center: [lon, lat],
      zoom: Math.max(9.5, zoom || 13.0),
      pitch: pitch !== undefined ? pitch : 64,
      bearing: bearing !== undefined ? bearing : map.getBearing(),
      duration: 1600,
      essential: true
    });
  }

  function setCameraMode(mode) {
    cameraMode = mode;
    document.querySelectorAll("[data-cam-mode]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-cam-mode") === mode);
    });

    if (!map || !window.C2KApp) return;

    if (mode === "follow-simon") {
      const r = window.C2KApp.getCurrentRunnerState();
      if (r) {
        smoothCamLon = r.lon;
        smoothCamLat = r.lat;
        const ahead = getPointAtKm((r.course_km || 0) + 18.0) || [r.lon, r.lat];
        const macroBrg = computeMacroBearing(r.lon, r.lat, ahead[0], ahead[1]);
        map.flyTo({
          center: [r.lon, r.lat],
          zoom: Math.max(map.getZoom(), 13.7),
          pitch: 58,
          bearing: macroBrg,
          duration: 950,
          essential: true
        });
      }
    } else if (mode === "follow-crew") {
      const c = window.C2KApp.getCurrentCrewState();
      if (c) {
        smoothCamLon = c.lon;
        smoothCamLat = c.lat;
        map.flyTo({
          center: [c.lon, c.lat],
          zoom: Math.max(map.getZoom(), 13.5),
          pitch: 58,
          duration: 950,
          essential: true
        });
      }
    } else if (mode === "overview") {
      cameraMode = "free";
      map.flyTo({
        center: [149.18, -36.86],
        zoom: 8.55,
        pitch: 44,
        bearing: -32,
        duration: 1400,
        essential: true
      });
    } else if (mode === "flyover") {
      const r = window.C2KApp.getCurrentRunnerState();
      flyoverProgressKm = r && r.course_km > 1 && r.course_km < 220 ? r.course_km : 0;
      const pt = getPointAtKm(flyoverProgressKm) || [149.871, -37.092];
      const ahead = getPointAtKm(flyoverProgressKm + 18.0) || pt;
      flyoverSmoothBearing = computeMacroBearing(pt[0], pt[1], ahead[0], ahead[1]);
    } else if (mode === "dual-frame") {
      const r = window.C2KApp.getCurrentRunnerState();
      const c = window.C2KApp.getCurrentCrewState();
      if (r && c) {
        const bounds = new maplibregl.LngLatBounds();
        bounds.extend([r.lon, r.lat]);
        bounds.extend([c.lon, c.lat]);
        map.fitBounds(bounds, {
          padding: { top: 130, bottom: 220, left: 370, right: 340 },
          pitch: 58,
          maxZoom: 13.6,
          duration: 1300
        });
      }
    }
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

    if (map && window.C2KApp && !map.isMoving()) {
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
      } else if (cameraMode === "flyover") {
        flyoverProgressKm += dt * 1.5;
        if (flyoverProgressKm > 241.25) flyoverProgressKm = 0;
        const pt = getPointAtKm(flyoverProgressKm);
        // 18 km macro look-ahead vector eliminates all road-bend & switchback rotation twitch!
        const ahead = getPointAtKm(Math.min(241.25, flyoverProgressKm + 18.0)) || pt;
        if (pt && ahead) {
          const macroTargetBearing = computeMacroBearing(pt[0], pt[1], ahead[0], ahead[1]);
          flyoverSmoothBearing = angleLerp(flyoverSmoothBearing, macroTargetBearing, dt * 0.35);
          map.jumpTo({
            center: [pt[0], pt[1]],
            zoom: 12.6,
            pitch: 60,
            bearing: flyoverSmoothBearing
          });
        }
      }
    } else if (map && window.C2KApp && cameraMode === "flyover") {
      flyoverProgressKm += dt * 1.5;
      if (flyoverProgressKm > 241.25) flyoverProgressKm = 0;
      const pt = getPointAtKm(flyoverProgressKm);
      const ahead = getPointAtKm(Math.min(241.25, flyoverProgressKm + 18.0)) || pt;
      if (pt && ahead) {
        const macroTargetBearing = computeMacroBearing(pt[0], pt[1], ahead[0], ahead[1]);
        flyoverSmoothBearing = angleLerp(flyoverSmoothBearing, macroTargetBearing, dt * 0.35);
        map.jumpTo({
          center: [pt[0], pt[1]],
          zoom: 12.6,
          pitch: 60,
          bearing: flyoverSmoothBearing
        });
      }
    }

    requestAnimationFrame(tickCameraDirector);
  }

  function showScrubHoverPin(lon, lat, visible) {
    if (!scrubHoverMarker) return;
    scrubHoverMarker.getElement().style.display = visible ? "block" : "none";
    if (visible && lon !== undefined && lat !== undefined) {
      scrubHoverMarker.setLngLat([lon, lat]);
    }
  }

  function enableMapPinPick(callback) {
    mapPinPickCallback = typeof callback === "function" ? callback : null;
    if (map) {
      map.getCanvas().style.cursor = mapPinPickCallback ? "crosshair" : "";
    }
  }

  return {
    init: init,
    getMap: function () { return map; },
    updateEntities: updateEntities,
    setImageryLayer: setImageryLayer,
    setTerrainExaggeration: setTerrainExaggeration,
    setMilestonesVisible: setMilestonesVisible,
    updateRadarTileLayer: updateRadarTileLayer,
    updateSkyForSolarAltitude: updateSkyForSolarAltitude,
    flyToCoordinate: flyToCoordinate,
    setCameraMode: setCameraMode,
    getPointAtKm: getPointAtKm,
    showScrubHoverPin: showScrubHoverPin,
    enableMapPinPick: enableMapPinPick
  };
})();
