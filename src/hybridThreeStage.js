/**
 * Coast to Kosciuszko (C2K) - Auto-Hybrid Three.js Corridor Engine (Macro 3D Stage)
 * Architecture:
 *  - Instant boot from pre-baked AWS Terrarium corridor DEM (assets/corridor/height.png) +
 *    progressive satellite textures (sat-2k -> sat-4k -> sat-6k) & relief map (relief-4k).
 *  - Original C2K Live Broadcast aesthetic: deep space-navy sky & fog (#06090f),
 *    blaze orange (#ff5a1f) completed track, golden amber (#fbbf24) remaining track,
 *    crew cyan (#00e5ff) Cow Bail detour, and dark frosted 3D Broadcast beacons.
 *  - Bidirectional camera sync with MapLibre v4 [lon, lat, zoom, pitch, bearing] for
 *    seamless hysteresis crossfades at zoom >= 12.20 into sharp street satellite.
 */

window.C2KHybridThreeStage = (function () {
  const DEFAULTS = {
    lon_min: 148.08,
    lon_max: 150.08,
    lat_min: -37.23,
    lat_max: -36.23,
    merc_y_min: 0.6081051413454825,
    merc_y_max: 0.6115711199648586,
    world_width: 160.0,
    world_depth: 100.0,
    meters_per_unit: 1115.25,
    ele_offset_m: -100.0,
    ele_scale_m: 2600.0
  };

  const SEGS_X = 360;
  const SEGS_Z = 225;
  const SLAB_BASE_Y = -3.4;
  const STREET_ZOOM_ENTER = 12.20;

  // Crew detour waypoints around Cow Bail Trail (Rocky Hall -> Wyndham -> Mt Darragh Rd -> Cathcart)
  const CREW_DETOUR_WAYPOINTS = [
    [149.47101, -36.90518, 295],
    [149.50321, -36.92718, 255],
    [149.52750, -36.92610, 240],
    [149.47200, -36.88500, 490],
    [149.43500, -36.85900, 740],
    [149.39124, -36.84325, 765]
  ];

  let meta = Object.assign({}, DEFAULTS);
  let courseData = null;
  let stageWrapEl = null;
  let canvasEl = null;
  let overlayEl = null;
  let hoverDotEl = null;

  let renderer = null;
  let scene = null;
  let camera = null;
  let controls = null;
  let rafId = null;
  let isActive = true;
  let assetsReady = false;

  let reliefScaleGroup = null;
  let terrainGeo = null;
  let terrainMat = null;
  let terrainMesh = null;
  let skirtGeo = null;
  let skirtMat = null;
  let perimeterTopIndices = [];
  let baseGridHeights = null;
  let surroundMat = null;

  let radarMesh = null;
  let radarTexture = null;
  let radarCanvas = null;
  let lastRadarTemplate = "";

  let heightPixels = null;
  let heightW = 1024;
  let heightH = 640;

  let exaggeration = 2.2;
  let activeImageryMode = "google"; // "google" | "relief" | "esri"
  let activeSatTexture = null;
  let reliefTexture = null;
  let lineMaterials = [];

  let doneLine = null;
  let lastDoneKm = -1;
  let lastKnownRunnerKm = 0;
  let lastRunnerState = null;
  let lastCrewState = null;

  let poiMarkers = [];
  let milestoneMarkers = [];
  let toiletMarkers = [];
  let allProjectedMarkers = [];
  let runnerMarkerObj = null;
  let lastFixMarkerObj = null;
  let crewMarkerObj = null;
  let milestonesVisible = true;
  let toiletsVisible = false;

  let flying = false;
  let flyProgressKm = 0;
  let tweenState = null;
  let lastHandoffTs = 0;

  let onUserInteractCb = null;
  let onRequestStreetZoomCb = null;
  let onReadyCb = null;
  let onSelectCameraCb = null;
  let mapPinPickCallback = null;
  let pointerDownXY = null;
  let orbitDragMode = true;

  function mercYNorm(latDeg) {
    const s = Math.sin((latDeg * Math.PI) / 180.0);
    return 0.5 - Math.log((1.0 + s) / (1.0 - s)) / (4.0 * Math.PI);
  }

  function lonLatToUV(lon, lat) {
    const u = (lon - meta.lon_min) / (meta.lon_max - meta.lon_min);
    const v = (mercYNorm(lat) - meta.merc_y_min) / (meta.merc_y_max - meta.merc_y_min);
    return [u, v];
  }

  function worldXZToLonLat(x, z) {
    const u = x / meta.world_width + 0.5;
    const v = z / meta.world_depth + 0.5;
    const lon = meta.lon_min + u * (meta.lon_max - meta.lon_min);
    const my = meta.merc_y_min + v * (meta.merc_y_max - meta.merc_y_min);
    const sinLat = Math.max(-0.999999, Math.min(0.999999, Math.tanh((0.5 - my) * 2.0 * Math.PI)));
    const lat = (Math.asin(sinLat) * 180.0) / Math.PI;
    return { lon: lon, lat: lat };
  }

  function sampleHeightMetersAtUV(u, v) {
    if (!heightPixels) return 0;
    const fx = Math.max(0, Math.min(1, u)) * (heightW - 1);
    const fy = Math.max(0, Math.min(1, v)) * (heightH - 1);
    const x0 = Math.floor(fx);
    const y0 = Math.floor(fy);
    const x1 = Math.min(heightW - 1, x0 + 1);
    const y1 = Math.min(heightH - 1, y0 + 1);
    const tx = fx - x0;
    const ty = fy - y0;

    function readM(px, py) {
      const idx = (py * heightW + px) * 4;
      const val16 = (heightPixels[idx] << 8) | heightPixels[idx + 1];
      return meta.ele_offset_m + (val16 / 65535.0) * meta.ele_scale_m;
    }

    const h00 = readM(x0, y0);
    const h10 = readM(x1, y0);
    const h01 = readM(x0, y1);
    const h11 = readM(x1, y1);
    const top = h00 + (h10 - h00) * tx;
    const bot = h01 + (h11 - h01) * tx;
    return top + (bot - top) * ty;
  }

  function sampleMeshMaxYAtUV(u, v) {
    if (!baseGridHeights) return 0;
    const fx = Math.max(0, Math.min(1, u)) * SEGS_X;
    const fy = Math.max(0, Math.min(1, v)) * SEGS_Z;
    const x0 = Math.floor(fx);
    const y0 = Math.floor(fy);
    const x1 = Math.min(SEGS_X, x0 + 1);
    const y1 = Math.min(SEGS_Z, y0 + 1);
    const stride = SEGS_X + 1;
    return Math.max(
      baseGridHeights[y0 * stride + x0],
      baseGridHeights[y0 * stride + x1],
      baseGridHeights[y1 * stride + x0],
      baseGridHeights[y1 * stride + x1]
    );
  }

  function lonLatToWorldUnscaled(lon, lat, fallbackEleM) {
    const uv = lonLatToUV(lon, lat);
    const x = (uv[0] - 0.5) * meta.world_width;
    const z = (uv[1] - 0.5) * meta.world_depth;
    let ele = fallbackEleM !== undefined ? fallbackEleM : 0;
    if (heightPixels) {
      ele = Math.max(ele, sampleHeightMetersAtUV(uv[0], uv[1]));
    }
    const y = Math.max(Math.max(0, ele) / meta.meters_per_unit, sampleMeshMaxYAtUV(uv[0], uv[1]));
    return [x, y, z];
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

  function getStageRect() {
    if (!stageWrapEl) return { width: 1280, height: 700 };
    const r = stageWrapEl.getBoundingClientRect();
    return {
      width: Math.max(300, r.width || 1280),
      height: Math.max(240, r.height || 700)
    };
  }

  function zoomToCameraDist(zoom, stageH) {
    const fovRad = ((camera ? camera.fov : 38) * Math.PI) / 180.0;
    const mPerPx = 62734.0 / Math.pow(2, zoom);
    const dist = (mPerPx * Math.max(400, stageH || getStageRect().height)) / (2.0 * Math.tan(fovRad * 0.5) * meta.meters_per_unit);
    return Math.max(controls ? controls.minDistance : 6.0, Math.min(controls ? controls.maxDistance : 280.0, dist));
  }

  function getCameraGeoState() {
    if (!camera || !controls) {
      return { lon: 149.02, lat: -36.79, zoom: 8.35, pitch: 48, bearing: -24, dist: 162 };
    }
    const offset = camera.position.clone().sub(controls.target);
    const dist = Math.max(0.01, offset.length());
    const dx = controls.target.x - camera.position.x;
    const dz = controls.target.z - camera.position.z;
    const horizDist = Math.hypot(dx, dz);
    const bearing = ((Math.atan2(dx, -dz) * 180.0) / Math.PI + 360.0) % 360.0;
    const normBrg = bearing > 180 ? bearing - 360 : bearing;
    const pitch = Math.min(76, Math.max(0, (Math.atan2(horizDist, Math.max(0.001, camera.position.y - controls.target.y)) * 180.0) / Math.PI));

    const rect = getStageRect();
    const fovRad = (camera.fov * Math.PI) / 180.0;
    const mPerPx = (dist * 2.0 * Math.tan(fovRad * 0.5) * meta.meters_per_unit) / Math.max(400, rect.height);
    const zoom = Math.log2(62734.0 / Math.max(0.05, mPerPx));
    const centerGeo = worldXZToLonLat(controls.target.x, controls.target.z);

    return {
      lon: centerGeo.lon,
      lat: centerGeo.lat,
      zoom: zoom,
      pitch: pitch,
      bearing: normBrg,
      dist: dist
    };
  }

  function setCameraFromGeoState(state, animateMs) {
    if (!camera || !controls || !state) return;
    const uv = lonLatToUV(state.lon, state.lat);
    const tx = (uv[0] - 0.5) * meta.world_width;
    const tz = (uv[1] - 0.5) * meta.world_depth;
    const ty = sampleMeshMaxYAtUV(uv[0], uv[1]) * exaggeration;

    const brgRad = ((state.bearing || 0) * Math.PI) / 180.0;
    const polarRad = (Math.max(4, Math.min(76, state.pitch !== undefined ? state.pitch : 50)) * Math.PI) / 180.0;
    const rect = getStageRect();
    const dist = zoomToCameraDist(state.zoom !== undefined ? state.zoom : 9.0, rect.height);

    const toTarget = new THREE.Vector3(tx, ty, tz);
    const toPos = new THREE.Vector3(
      tx - Math.sin(brgRad) * Math.sin(polarRad) * dist,
      ty + Math.cos(polarRad) * dist,
      tz + Math.cos(brgRad) * Math.sin(polarRad) * dist
    );

    if (animateMs && animateMs > 0) {
      tweenCamera(toPos, toTarget, animateMs);
    } else {
      tweenState = null;
      setFlying(false);
      camera.position.copy(toPos);
      controls.target.copy(toTarget);
      controls.update();
    }
  }

  function init(opts) {
    courseData = opts.courseData;
    onUserInteractCb = opts.onUserInteract || null;
    onRequestStreetZoomCb = opts.onRequestStreetZoom || null;
    onReadyCb = opts.onReady || null;
    onSelectCameraCb = opts.onSelectCamera || null;

    stageWrapEl = document.getElementById("three-corridor-stage");
    canvasEl = document.getElementById("three-corridor-canvas");
    overlayEl = document.getElementById("three-beacon-overlay");
    if (!stageWrapEl || !canvasEl || !overlayEl || !window.THREE) return;

    hoverDotEl = document.createElement("div");
    hoverDotEl.className = "three-scrub-dot";
    hoverDotEl.style.display = "none";
    overlayEl.appendChild(hoverDotEl);

    setupThreeScene();
    bindPinPicker();
    loadAssetsAndBuildTerrain();
    startLoop();
  }

  function setupThreeScene() {
    const rect = getStageRect();
    renderer = new THREE.WebGLRenderer({
      canvas: canvasEl,
      antialias: true,
      alpha: false,
      powerPreference: "high-performance"
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(rect.width, rect.height, false);
    renderer.outputEncoding = THREE.sRGBEncoding;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x06090f);
    scene.fog = new THREE.FogExp2(0x070e1b, 0.0022);

    camera = new THREE.PerspectiveCamera(38, rect.width / rect.height, 0.4, 980);
    camera.position.set(42, 134, 188);

    controls = new THREE.OrbitControls(camera, canvasEl);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.74;
    controls.zoomSpeed = 0.96;
    controls.panSpeed = 0.88;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.minDistance = 6.0;
    controls.maxDistance = 320.0;
    controls.target.set(2.0, -1.0, 12.0);
    controls.update();

    controls.addEventListener("start", function () {
      document.body.style.userSelect = "none";
      tweenState = null;
      if (flying) setFlying(false);
      if (onUserInteractCb) onUserInteractCb();
    });
    controls.addEventListener("end", function () {
      document.body.style.userSelect = "";
    });

    const hemi = new THREE.HemisphereLight(0xeef4ff, 0x162238, 0.95);
    scene.add(hemi);

    const sun = new THREE.DirectionalLight(0xfff1dc, 0.42);
    sun.position.set(-90, 140, -60);
    scene.add(sun);

    const surroundGeo = new THREE.PlaneGeometry(900, 900);
    surroundGeo.rotateX(-Math.PI / 2);
    surroundMat = new THREE.MeshBasicMaterial({ color: 0x050912 });
    const surroundPlane = new THREE.Mesh(surroundGeo, surroundMat);
    surroundPlane.position.y = -3.45;
    scene.add(surroundPlane);

    reliefScaleGroup = new THREE.Group();
    reliefScaleGroup.scale.y = exaggeration;
    scene.add(reliefScaleGroup);

    window.addEventListener("resize", handleResize);
  }

  function handleResize() {
    if (!stageWrapEl || !renderer || !camera) return;
    const rect = getStageRect();
    camera.aspect = rect.width / rect.height;
    camera.updateProjectionMatrix();
    renderer.setSize(rect.width, rect.height, false);
    for (let i = 0; i < lineMaterials.length; i++) {
      lineMaterials[i].resolution.set(rect.width, rect.height);
    }
  }

  function bindPinPicker() {
    if (!canvasEl) return;
    canvasEl.addEventListener("pointerdown", function (e) {
      pointerDownXY = { x: e.clientX, y: e.clientY };
    });
    canvasEl.addEventListener("pointerup", function (e) {
      if (!mapPinPickCallback || !terrainMesh || !camera || !pointerDownXY) return;
      if (Math.hypot(e.clientX - pointerDownXY.x, e.clientY - pointerDownXY.y) > 6) return;
      const rect = stageWrapEl.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      const ray = new THREE.Raycaster();
      ray.setFromCamera(ndc, camera);
      const hits = ray.intersectObject(terrainMesh, false);
      if (hits && hits.length > 0) {
        const pt = hits[0].point;
        const geo = worldXZToLonLat(pt.x, pt.z);
        const cb = mapPinPickCallback;
        mapPinPickCallback = null;
        canvasEl.style.cursor = "";
        cb({ lat: geo.lat, lon: geo.lon });
      }
    });
  }

  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error("Failed loading " + src)); };
      img.src = src;
    });
  }

  function configureTexture(tex) {
    tex.encoding = THREE.sRGBEncoding;
    tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    tex.needsUpdate = true;
    return tex;
  }

  async function loadAssetsAndBuildTerrain() {
    try {
      const metaResp = await fetch("assets/corridor/meta.json");
      if (metaResp.ok) {
        meta = Object.assign({}, DEFAULTS, await metaResp.json());
      }
    } catch (e) {}

    try {
      const pair = await Promise.all([
        loadImage("assets/corridor/height.png"),
        loadImage("assets/corridor/sat-2k.jpg")
      ]);
      const hImg = pair[0];
      const sat2kImg = pair[1];

      const off = document.createElement("canvas");
      heightW = hImg.naturalWidth || 1024;
      heightH = hImg.naturalHeight || 640;
      off.width = heightW;
      off.height = heightH;
      const octx = off.getContext("2d");
      octx.drawImage(hImg, 0, 0);
      heightPixels = octx.getImageData(0, 0, heightW, heightH).data;

      activeSatTexture = configureTexture(new THREE.Texture(sat2kImg));
      buildSlabMeshes(activeSatTexture);
      buildCoursePolylines();
      buildBeacons();
      resetOverview(true);
      assetsReady = true;

      if (lastRunnerState || lastCrewState) {
        updateEntities(lastRunnerState, lastCrewState);
      } else {
        updateCompletedLine(lastKnownRunnerKm);
      }
      if (onReadyCb) onReadyCb();

      // Background progressive upgrades (4k -> 6k + preloaded relief-4k)
      loadImage("assets/corridor/sat-4k.jpg").then(function (img4) {
        const tex4 = configureTexture(new THREE.Texture(img4));
        if (activeSatTexture) activeSatTexture.dispose();
        activeSatTexture = tex4;
        if (activeImageryMode !== "relief" && terrainMat) {
          terrainMat.map = tex4;
          terrainMat.needsUpdate = true;
        }
        loadImage("assets/corridor/sat-6k.jpg").then(function (img6) {
          const tex6 = configureTexture(new THREE.Texture(img6));
          if (activeSatTexture) activeSatTexture.dispose();
          activeSatTexture = tex6;
          if (activeImageryMode !== "relief" && terrainMat) {
            terrainMat.map = tex6;
            terrainMat.needsUpdate = true;
          }
        }).catch(function () {});
      }).catch(function () {});

      loadImage("assets/corridor/relief-4k.jpg").then(function (rImg) {
        reliefTexture = configureTexture(new THREE.Texture(rImg));
        if (activeImageryMode === "relief" && terrainMat) {
          terrainMat.map = reliefTexture;
          terrainMat.needsUpdate = true;
        }
      }).catch(function () {});
    } catch (err) {
      console.error("[HybridThreeStage] Failed initializing 3D assets:", err);
      if (onReadyCb) onReadyCb();
    }
  }

  function buildSlabMeshes(initialTexture) {
    terrainGeo = new THREE.PlaneGeometry(meta.world_width, meta.world_depth, SEGS_X, SEGS_Z);
    terrainGeo.rotateX(-Math.PI / 2);

    const posAttr = terrainGeo.attributes.position;
    baseGridHeights = new Float32Array(posAttr.count);
    for (let iy = 0; iy <= SEGS_Z; iy++) {
      const v = iy / SEGS_Z;
      for (let ix = 0; ix <= SEGS_X; ix++) {
        const u = ix / SEGS_X;
        const idx = iy * (SEGS_X + 1) + ix;
        const eleM = Math.max(0, sampleHeightMetersAtUV(u, v));
        const yUnit = eleM / meta.meters_per_unit;
        baseGridHeights[idx] = yUnit;
        posAttr.setY(idx, yUnit);
      }
    }
    posAttr.needsUpdate = true;
    terrainGeo.computeVertexNormals();

    terrainMat = new THREE.MeshStandardMaterial({
      map: initialTexture,
      roughness: 0.94,
      metalness: 0.02,
      polygonOffset: true,
      polygonOffsetFactor: 4,
      polygonOffsetUnits: 4
    });
    terrainMesh = new THREE.Mesh(terrainGeo, terrainMat);
    reliefScaleGroup.add(terrainMesh);

    const ringIndices = [];
    for (let ix = 0; ix <= SEGS_X; ix++) ringIndices.push(ix);
    for (let iy = 1; iy <= SEGS_Z; iy++) ringIndices.push(iy * (SEGS_X + 1) + SEGS_X);
    for (let ix = SEGS_X - 1; ix >= 0; ix--) ringIndices.push(SEGS_Z * (SEGS_X + 1) + ix);
    for (let iy = SEGS_Z - 1; iy >= 0; iy--) ringIndices.push(iy * (SEGS_X + 1));
    perimeterTopIndices = ringIndices;

    const wallPositions = [];
    const wallIndices = [];
    for (let i = 0; i < ringIndices.length; i++) {
      const gi = ringIndices[i];
      const gx = posAttr.getX(gi);
      const gy = baseGridHeights[gi] * exaggeration;
      const gz = posAttr.getZ(gi);
      wallPositions.push(gx, gy, gz);
      wallPositions.push(gx, SLAB_BASE_Y, gz);
    }
    for (let i = 0; i < ringIndices.length - 1; i++) {
      const topA = i * 2;
      const botA = i * 2 + 1;
      const topB = (i + 1) * 2;
      const botB = (i + 1) * 2 + 1;
      wallIndices.push(topA, botA, topB);
      wallIndices.push(topB, botA, botB);
    }

    const halfW = meta.world_width * 0.5;
    const halfD = meta.world_depth * 0.5;
    const capStart = wallPositions.length / 3;
    wallPositions.push(
      -halfW, SLAB_BASE_Y, -halfD,
      halfW, SLAB_BASE_Y, -halfD,
      halfW, SLAB_BASE_Y, halfD,
      -halfW, SLAB_BASE_Y, halfD
    );
    wallIndices.push(capStart, capStart + 1, capStart + 2);
    wallIndices.push(capStart, capStart + 2, capStart + 3);

    skirtGeo = new THREE.BufferGeometry();
    skirtGeo.setAttribute("position", new THREE.Float32BufferAttribute(wallPositions, 3));
    skirtGeo.setIndex(wallIndices);
    skirtGeo.computeVertexNormals();

    skirtMat = new THREE.MeshStandardMaterial({
      color: 0x0f172a,
      roughness: 0.96,
      metalness: 0.05,
      side: THREE.DoubleSide
    });
    const skirtMesh = new THREE.Mesh(skirtGeo, skirtMat);
    scene.add(skirtMesh);
  }

  function updateSkirtExaggeration() {
    if (!skirtGeo || !baseGridHeights || !perimeterTopIndices.length) return;
    const sAttr = skirtGeo.attributes.position;
    for (let i = 0; i < perimeterTopIndices.length; i++) {
      sAttr.setY(i * 2, baseGridHeights[perimeterTopIndices[i]] * exaggeration);
    }
    sAttr.needsUpdate = true;
    skirtGeo.computeVertexNormals();
  }

  function makeLine2(flatPositions, colorHex, linewidth, dashed, renderOrder) {
    if (!flatPositions || flatPositions.length < 6) return null;
    const rect = getStageRect();
    const geom = new THREE.LineGeometry();
    geom.setPositions(flatPositions);

    const matOpts = {
      color: colorHex,
      linewidth: linewidth,
      resolution: new THREE.Vector2(rect.width, rect.height),
      dashed: !!dashed,
      depthTest: true,
      depthWrite: false
    };
    if (dashed) {
      matOpts.dashScale = 3.2;
      matOpts.dashSize = 0.55;
      matOpts.gapSize = 0.45;
    }

    const mat = new THREE.LineMaterial(matOpts);
    lineMaterials.push(mat);

    const line = new THREE.Line2(geom, mat);
    line.renderOrder = renderOrder || 10;
    line.computeLineDistances();
    return line;
  }

  function buildCoursePolylines() {
    if (!courseData || !courseData.track || !reliefScaleGroup) return;
    const track = courseData.track;

    const casingFlat = [];
    const rimFlat = [];
    const mainFlat = [];
    const unsealedSegs = [];
    let currentUnsealed = [];

    for (let i = 0; i < track.length; i++) {
      const pt = track[i];
      const wPt = lonLatToWorldUnscaled(pt[0], pt[1], pt[2]);
      const yLift = wPt[1] + 0.16;
      casingFlat.push(wPt[0], yLift, wPt[2]);
      rimFlat.push(wPt[0], yLift, wPt[2]);
      mainFlat.push(wPt[0], yLift, wPt[2]);

      const km = pt[3];
      const isUnsealed = (km >= 51.7 && km <= 63.5) || km >= 222.6;
      if (isUnsealed) {
        currentUnsealed.push(wPt[0], yLift, wPt[2]);
      } else if (currentUnsealed.length > 0) {
        if (currentUnsealed.length >= 6) unsealedSegs.push(currentUnsealed);
        currentUnsealed = [];
      }
    }
    if (currentUnsealed.length >= 6) unsealedSegs.push(currentUnsealed);

    const casing = makeLine2(casingFlat, 0x040711, 6.4, false, 10);
    if (casing) reliefScaleGroup.add(casing);

    const detourFlat = [];
    for (let i = 0; i < CREW_DETOUR_WAYPOINTS.length; i++) {
      const wp = CREW_DETOUR_WAYPOINTS[i];
      const wPt = lonLatToWorldUnscaled(wp[0], wp[1], wp[2]);
      detourFlat.push(wPt[0], wPt[1] + 0.16, wPt[2]);
    }
    const detourCasing = makeLine2(detourFlat, 0x040711, 4.4, false, 11);
    if (detourCasing) reliefScaleGroup.add(detourCasing);
    const detourLine = makeLine2(detourFlat, 0x00e5ff, 2.4, true, 12);
    if (detourLine) reliefScaleGroup.add(detourLine);

    const rim = makeLine2(rimFlat, 0x1e293b, 4.4, false, 13);
    if (rim) reliefScaleGroup.add(rim);

    const mainRoute = makeLine2(mainFlat, 0xfbbf24, 3.1, false, 14);
    if (mainRoute) reliefScaleGroup.add(mainRoute);

    unsealedSegs.forEach(function (seg) {
      const uLine = makeLine2(seg, 0xfef3c7, 2.6, true, 15);
      if (uLine) reliefScaleGroup.add(uLine);
    });
  }

  function updateCompletedLine(courseKm) {
    if (!courseData || !courseData.track || !reliefScaleGroup || !assetsReady) return;
    if (Math.abs(courseKm - lastDoneKm) < 0.25 && doneLine) return;
    lastDoneKm = courseKm;

    const track = courseData.track;
    const flat = [];
    for (let i = 0; i < track.length; i++) {
      const pt = track[i];
      const wPt = lonLatToWorldUnscaled(pt[0], pt[1], pt[2]);
      flat.push(wPt[0], wPt[1] + 0.16, wPt[2]);
      if (pt[3] >= courseKm) break;
    }
    if (flat.length < 6) {
      const p0 = lonLatToWorldUnscaled(track[0][0], track[0][1], track[0][2]);
      flat.push(p0[0] + 0.001, p0[1] + 0.16, p0[2]);
    }

    if (!doneLine) {
      doneLine = makeLine2(flat, 0xff5a1f, 4.0, false, 16);
      if (doneLine) reliefScaleGroup.add(doneLine);
    } else {
      const oldGeom = doneLine.geometry;
      const newGeom = new THREE.LineGeometry();
      newGeom.setPositions(flat);
      doneLine.geometry = newGeom;
      doneLine.computeLineDistances();
      if (oldGeom) oldGeom.dispose();
    }
  }

  function createOverlayElement(html, className, lon, lat, eleM, onClick) {
    const el = document.createElement("div");
    el.className = className;
    el.innerHTML = html;
    if (onClick) {
      el.addEventListener("click", function (e) {
        e.stopPropagation();
        onClick();
      });
    }
    overlayEl.appendChild(el);
    const rec = { el: el, lon: lon, lat: lat, eleM: eleM || 0, sx: 0, sy: 0, visible: true };
    allProjectedMarkers.push(rec);
    return rec;
  }

  function buildBeacons() {
    if (!courseData || !overlayEl) return;

    const cutoffNums = { 3: true, 4: true, 5: true, 6: true, 8: true };
    const majorOverviewNums = { 3: true, 4: true, 5: true, 6: true };
    const seenCoords = [];

    (courseData.pois || []).forEach(function (poi) {
      const keepCats = ["start", "summit", "checkpoint", "crew_uturn"];
      if (keepCats.indexOf(poi.category) === -1) return;

      const tooClose = seenCoords.some(function (c) {
        return Math.abs(c[0] - poi.lon) < 0.015 && Math.abs(c[1] - poi.lat) < 0.015;
      });
      if (tooClose && poi.category !== "summit") return;
      seenCoords.push([poi.lon, poi.lat]);

      const isMinor =
        poi.category === "crew_uturn" ||
        (poi.category === "checkpoint" && !majorOverviewNums[poi.checkpoint_num]);

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

      const html =
        '<div class="' + badgeCls + '">' +
          '<span>' + title + '</span>' +
          '<span style="opacity:0.75;font-family:var(--font-mono);font-size:9px;">' + poi.course_km.toFixed(1) + 'K</span>' +
        '</div>' +
        '<div class="poi-stem"></div>' +
        '<div class="poi-dot"></div>';

      const m = createOverlayElement(
        html,
        "poi-marker-3d" + (isMinor ? " is-minor" : ""),
        poi.lon,
        poi.lat,
        poi.ele_m,
        function () {
          if (onSelectCameraCb) onSelectCameraCb(poi.lon, poi.lat, 13.6, 62, -25);
        }
      );
      poiMarkers.push(m);
    });

    // 10K milestones
    (courseData.milestones || []).forEach(function (ms) {
      const cls = ms.type === "special" ? "three-ms-dot special" : "three-ms-dot";
      const m = createOverlayElement("", cls, ms.lon, ms.lat, 400, null);
      m.el.style.display = milestonesVisible ? "block" : "none";
      milestoneMarkers.push(m);
    });

    // Official Toilets & Aid badges
    (courseData.toilets_aid || []).forEach(function (stop) {
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
      const html =
        '<div class="poi-badge ' + badgeCls + '">' +
          '<span>' + icon + ' · ' + stop.shortName + '</span>' +
          '<span style="opacity:0.8;font-family:var(--font-mono);font-size:9px;">' + stop.course_km.toFixed(1) + 'K</span>' +
        '</div>' +
        '<div class="poi-stem"></div>' +
        '<div class="poi-dot"></div>';
      const m = createOverlayElement(html, "poi-marker-3d toilet-marker-3d", stop.lon, stop.lat, stop.ele_m, function () {
        if (window.C2KApp && window.C2KApp.openStopDetailModal) {
          window.C2KApp.openStopDetailModal(stop);
        }
      });
      m.el.style.display = toiletsVisible ? "flex" : "none";
      toiletMarkers.push(m);
    });

    // Last Fix marker
    lastFixMarkerObj = createOverlayElement(
      '<div class="marker-lastfix-chip">LAST FIX · <span id="three-lastfix-sub">--</span></div><div class="poi-stem"></div><div class="poi-dot"></div>',
      "marker-3d-lastfix",
      149.87226,
      -37.09205,
      4,
      null
    );
    lastFixMarkerObj.el.style.display = "none";

    // Crew Car beacon
    crewMarkerObj = createOverlayElement(
      '<div class="marker-crew-card"><span>CREW</span><span id="three-crew-sub" style="font-family:var(--font-mono);font-size:10px;opacity:0.9;">0.0k</span></div><div class="marker-crew-stem"></div><div class="marker-crew-dot"></div>',
      "marker-3d-crew",
      149.87195,
      -37.09225,
      5,
      function () {
        if (onSelectCameraCb && crewMarkerObj) onSelectCameraCb(crewMarkerObj.lon, crewMarkerObj.lat, 13.4, 58, -24);
      }
    );

    // Simon beacon
    runnerMarkerObj = createOverlayElement(
      '<div class="marker-runner-card"><span id="three-runner-title">SIMON</span><span id="three-runner-sub" style="font-family:var(--font-mono);font-size:10px;opacity:0.95;">0.0k · 4m</span></div><div class="marker-runner-stem"></div><div class="marker-runner-dot"></div>',
      "marker-3d-runner",
      149.87226,
      -37.09205,
      4,
      function () {
        if (onSelectCameraCb && runnerMarkerObj) onSelectCameraCb(runnerMarkerObj.lon, runnerMarkerObj.lat, 13.6, 58, -25);
      }
    );
  }

  function updateEntities(runnerState, crewState) {
    if (runnerState) lastRunnerState = runnerState;
    if (crewState) lastCrewState = crewState;

    if (runnerState && runnerMarkerObj) {
      lastKnownRunnerKm = runnerState.course_km || 0;
      runnerMarkerObj.lon = runnerState.lon;
      runnerMarkerObj.lat = runnerState.lat;
      runnerMarkerObj.eleM = runnerState.ele_m || 0;

      const isHyp = runnerState.epistemic === "HYPOTHESIS_PACE_ESTIMATE";
      runnerMarkerObj.el.classList.toggle("is-hypothesis", isHyp);
      const tEl = document.getElementById("three-runner-title");
      if (tEl) tEl.textContent = isHyp ? "SIMON (EST.)" : "SIMON";
      const sEl = document.getElementById("three-runner-sub");
      if (sEl) sEl.textContent = (runnerState.course_km || 0).toFixed(1) + "k · " + Math.round(runnerState.ele_m || 0) + "m";

      if (lastFixMarkerObj) {
        if (isHyp && runnerState.confirmed_lon !== undefined && runnerState.confirmed_lat !== undefined) {
          lastFixMarkerObj.lon = runnerState.confirmed_lon;
          lastFixMarkerObj.lat = runnerState.confirmed_lat;
          lastFixMarkerObj.el.style.display = "flex";
          const lfSub = document.getElementById("three-lastfix-sub");
          if (lfSub) lfSub.textContent = runnerState.fix_age_text || ((runnerState.confirmed_km || 0).toFixed(1) + "k");
        } else {
          lastFixMarkerObj.el.style.display = "none";
        }
      }
      updateCompletedLine(runnerState.course_km || 0);
    }

    if (crewState && crewMarkerObj) {
      crewMarkerObj.lon = crewState.lon;
      crewMarkerObj.lat = crewState.lat;
      crewMarkerObj.eleM = crewState.ele_m || 0;
      const cSub = document.getElementById("three-crew-sub");
      if (cSub) {
        cSub.textContent =
          (crewState.course_km || 0).toFixed(1) + "k" +
          (crewState.speed_kmh > 1 ? " · " + Math.round(crewState.speed_kmh) + "k/h" : "");
      }
    }
  }

  function setImageryLayer(mode) {
    activeImageryMode = mode === "relief" ? "relief" : mode === "esri" ? "esri" : "google";
    if (!terrainMat) return;
    if (activeImageryMode === "relief") {
      if (reliefTexture) {
        terrainMat.map = reliefTexture;
        terrainMat.needsUpdate = true;
      }
    } else if (activeSatTexture) {
      terrainMat.map = activeSatTexture;
      terrainMat.needsUpdate = true;
    }
  }

  function setTerrainExaggeration(val) {
    exaggeration = Math.max(1.0, Math.min(3.5, parseFloat(val) || 2.2));
    if (reliefScaleGroup) {
      reliefScaleGroup.scale.y = exaggeration;
    }
    updateSkirtExaggeration();
  }

  function setMilestonesVisible(vis) {
    milestonesVisible = !!vis;
    for (let i = 0; i < milestoneMarkers.length; i++) {
      milestoneMarkers[i].el.style.display = milestonesVisible ? "block" : "none";
    }
  }

  function setToiletsVisible(vis) {
    toiletsVisible = !!vis;
    for (let i = 0; i < toiletMarkers.length; i++) {
      toiletMarkers[i].el.style.display = toiletsVisible ? "flex" : "none";
    }
  }

  function updateRadarTileLayer(tileUrlTemplate, visible) {
    if (!terrainGeo || !reliefScaleGroup) return;
    if (!visible || !tileUrlTemplate) {
      if (radarMesh) radarMesh.visible = false;
      return;
    }

    if (!radarMesh) {
      radarCanvas = document.createElement("canvas");
      radarCanvas.width = 512;
      radarCanvas.height = 320;
      radarTexture = new THREE.CanvasTexture(radarCanvas);
      const rMat = new THREE.MeshBasicMaterial({
        map: radarTexture,
        transparent: true,
        opacity: 0.48,
        depthWrite: false,
        polygonOffset: true,
        polygonOffsetFactor: 2,
        polygonOffsetUnits: 2
      });
      radarMesh = new THREE.Mesh(terrainGeo, rMat);
      radarMesh.position.y = 0.08;
      radarMesh.renderOrder = 5;
      reliefScaleGroup.add(radarMesh);
    }

    radarMesh.visible = true;
    if (tileUrlTemplate === lastRadarTemplate) return;
    lastRadarTemplate = tileUrlTemplate;

    const rctx = radarCanvas.getContext("2d");
    rctx.clearRect(0, 0, 512, 320);

    // Covering z=7 RainViewer tiles for corridor [148.08..150.08, -37.23..-36.23]
    const tileCoords = [
      [116, 77], [117, 77],
      [116, 78], [117, 78]
    ];
    tileCoords.forEach(function (pair) {
      const tx = pair[0];
      const ty = pair[1];
      const url = tileUrlTemplate
        .replace("{z}", "7")
        .replace("{x}", String(tx))
        .replace("{y}", String(ty));
      loadImage(url).then(function (img) {
        const lon0 = (tx / 128) * 360 - 180;
        const lon1 = ((tx + 1) / 128) * 360 - 180;
        const my0 = ty / 128;
        const my1 = (ty + 1) / 128;
        const dx0 = ((lon0 - meta.lon_min) / (meta.lon_max - meta.lon_min)) * 512;
        const dx1 = ((lon1 - meta.lon_min) / (meta.lon_max - meta.lon_min)) * 512;
        const dy0 = ((my0 - meta.merc_y_min) / (meta.merc_y_max - meta.merc_y_min)) * 320;
        const dy1 = ((my1 - meta.merc_y_min) / (meta.merc_y_max - meta.merc_y_min)) * 320;
        rctx.drawImage(img, dx0, dy0, dx1 - dx0, dy1 - dy0);
        if (radarTexture) radarTexture.needsUpdate = true;
      }).catch(function () {});
    });
  }

  let lastSkyMode = "day";
  function updateSkyForSolarAltitude(solarAltDeg) {
    if (!scene) return;
    const mode = solarAltDeg < -4 ? "night" : solarAltDeg < 12 ? "golden" : "day";
    if (mode === lastSkyMode) return;
    lastSkyMode = mode;

    if (mode === "night") {
      scene.background.setHex(0x04070e);
      scene.fog.color.setHex(0x09111f);
      if (surroundMat) surroundMat.color.setHex(0x03060c);
    } else if (mode === "golden") {
      scene.background.setHex(0x111828);
      scene.fog.color.setHex(0x281c24);
      if (surroundMat) surroundMat.color.setHex(0x0a0e18);
    } else {
      scene.background.setHex(0x06090f);
      scene.fog.color.setHex(0x070e1b);
      if (surroundMat) surroundMat.color.setHex(0x050912);
    }
  }

  function tweenCamera(toPos, toTarget, durationMs) {
    if (!camera || !controls) return;
    setFlying(false);
    tweenState = {
      fromPos: camera.position.clone(),
      toPos: toPos.clone(),
      fromTarget: controls.target.clone(),
      toTarget: toTarget.clone(),
      start: performance.now(),
      duration: durationMs || 900
    };
  }

  function resetOverview(instant) {
    if (!camera || !controls) return;
    const targetPos = new THREE.Vector3(42, 134, 188);
    const targetLook = new THREE.Vector3(2.0, -1.0, 12.0);
    if (instant) {
      tweenState = null;
      setFlying(false);
      camera.position.copy(targetPos);
      controls.target.copy(targetLook);
      controls.update();
    } else {
      tweenCamera(targetPos, targetLook, 950);
    }
  }

  function fitDualBounds(r, c) {
    if (!r || !c || !camera || !controls) return;
    const wR = lonLatToWorldUnscaled(r.lon, r.lat, r.ele_m);
    const wC = lonLatToWorldUnscaled(c.lon, c.lat, c.ele_m);
    const mx = (wR[0] + wC[0]) * 0.5;
    const my = Math.max(wR[1], wC[1]) * exaggeration * 0.5;
    const mz = (wR[2] + wC[2]) * 0.5;
    const span = Math.max(24, Math.hypot(wR[0] - wC[0], wR[2] - wC[2]) * 1.9);
    tweenCamera(
      new THREE.Vector3(mx + span * 0.42, my + span * 0.65, mz + span * 0.78),
      new THREE.Vector3(mx, my, mz),
      1000
    );
  }

  function flyToCoordinate(lon, lat, zoom, pitch, bearing) {
    setCameraFromGeoState({
      lon: lon,
      lat: lat,
      zoom: zoom !== undefined ? zoom : 10.6,
      pitch: pitch !== undefined ? pitch : 55,
      bearing: bearing !== undefined ? bearing : -25
    }, 950);
  }

  function zoomByFactor(factor) {
    if (!camera || !controls) return;
    const offset = camera.position.clone().sub(controls.target);
    const nextLen = Math.max(controls.minDistance, Math.min(controls.maxDistance, offset.length() * factor));
    offset.setLength(nextLen);
    tweenCamera(controls.target.clone().add(offset), controls.target.clone(), 260);
  }

  function resetNorth() {
    if (!camera || !controls) return;
    const offset = camera.position.clone().sub(controls.target);
    const horiz = Math.hypot(offset.x, offset.z);
    const toPos = new THREE.Vector3(controls.target.x, controls.target.y + offset.y, controls.target.z + horiz);
    tweenCamera(toPos, controls.target.clone(), 420);
  }

  function setOrbitDragMode(val) {
    orbitDragMode = !!val;
    if (controls && window.THREE) {
      controls.mouseButtons = orbitDragMode
        ? { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN }
        : { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
    }
    return orbitDragMode;
  }

  function setFlying(val) {
    flying = !!val;
    if (flying) {
      tweenState = null;
      const r = window.C2KApp ? window.C2KApp.getCurrentRunnerState() : null;
      flyProgressKm = r && r.course_km > 2 && r.course_km < 220 ? r.course_km : 0;
    }
  }

  function startFlyover() {
    setFlying(true);
  }

  function stopFlyover() {
    setFlying(false);
  }

  function projectLonLat(lon, lat, eleM) {
    if (!camera) return { x: -9999, y: -9999 };
    const rect = getStageRect();
    const wPt = lonLatToWorldUnscaled(lon, lat, eleM || 0);
    const v = new THREE.Vector3(wPt[0], wPt[1] * exaggeration, wPt[2]);
    v.project(camera);
    if (v.z > 1 || v.z < -1) return { x: -9999, y: -9999 };
    return {
      x: (v.x * 0.5 + 0.5) * rect.width,
      y: (-v.y * 0.5 + 0.5) * rect.height
    };
  }

  function showScrubHoverPin(lon, lat, visible) {
    if (!hoverDotEl || !visible || !isActive) {
      if (hoverDotEl) hoverDotEl.style.display = "none";
      return;
    }
    const scr = projectLonLat(lon, lat, 300);
    if (scr.x < -20 || scr.y < -20) {
      hoverDotEl.style.display = "none";
      return;
    }
    hoverDotEl.style.display = "block";
    hoverDotEl.style.transform = "translate(" + scr.x.toFixed(1) + "px," + scr.y.toFixed(1) + "px) translate(-50%,-50%)";
  }

  function enableMapPinPick(cb) {
    mapPinPickCallback = typeof cb === "function" ? cb : null;
    if (canvasEl) {
      canvasEl.style.cursor = mapPinPickCallback ? "crosshair" : "";
    }
  }

  function updateOverlayProjections() {
    if (!camera || !overlayEl) return;
    const rect = getStageRect();
    const w = rect.width;
    const h = rect.height;

    const geo = getCameraGeoState();
    const isOverview = geo.zoom < 10.3;
    overlayEl.classList.toggle("is-overview-zoom", isOverview);

    const compassSvg = document.getElementById("compass-needle-svg");
    if (compassSvg) {
      compassSvg.style.transform = "rotate(" + (-geo.bearing).toFixed(1) + "deg)";
    }

    const v = new THREE.Vector3();
    for (let i = 0; i < allProjectedMarkers.length; i++) {
      const m = allProjectedMarkers[i];
      if (m.el.style.display === "none") continue;
      const wPt = lonLatToWorldUnscaled(m.lon, m.lat, m.eleM);
      v.set(wPt[0], wPt[1] * exaggeration + 0.14, wPt[2]);
      v.project(camera);
      if (v.z > 1 || v.z < -1) {
        m.el.style.visibility = "hidden";
        m.visible = false;
        continue;
      }
      const sx = (v.x * 0.5 + 0.5) * w;
      const sy = (-v.y * 0.5 + 0.5) * h;
      if (sx < -80 || sx > w + 80 || sy < -80 || sy > h + 80) {
        m.el.style.visibility = "hidden";
        m.visible = false;
        continue;
      }
      m.sx = sx;
      m.sy = sy;
      m.visible = true;
      m.el.style.visibility = "visible";
      m.el.style.transform = "translate(" + sx.toFixed(1) + "px," + sy.toFixed(1) + "px) translate(-50%,-100%)";
    }

    // Center circular milestone ticks directly on the track
    for (let i = 0; i < milestoneMarkers.length; i++) {
      const mm = milestoneMarkers[i];
      if (!mm.visible) continue;
      mm.el.style.transform = "translate(" + mm.sx.toFixed(1) + "px," + mm.sy.toFixed(1) + "px) translate(-50%,-50%)";
    }

    // Prevent Crew badge text from overlapping checkpoints in wide overview
    if (crewMarkerObj && crewMarkerObj.visible) {
      const card = crewMarkerObj.el.querySelector(".marker-crew-card");
      if (card) {
        let tooClose = false;
        if (isOverview) {
          for (let j = 0; j < poiMarkers.length; j++) {
            const p = poiMarkers[j];
            if (!p.visible) continue;
            if (Math.hypot(p.sx - crewMarkerObj.sx, p.sy - crewMarkerObj.sy) < 28) {
              tooClose = true;
              break;
            }
          }
        }
        card.style.display = tooClose ? "none" : "flex";
      }
    }
  }

  let lastLoopTs = performance.now();
  function renderLoop(now) {
    if (!isActive) {
      rafId = null;
      return;
    }
    const dt = Math.min(0.05, (now - lastLoopTs) / 1000);
    lastLoopTs = now;

    if (renderer && scene && camera && controls) {
      if (flying) {
        flyProgressKm += dt * 3.8;
        if (flyProgressKm > 241.25) flyProgressKm = 0;
        const pt = getPointAtKm(flyProgressKm);
        const ahead = getPointAtKm(Math.min(241.25, flyProgressKm + 6.5)) || pt;
        if (pt && ahead) {
          const wCur = lonLatToWorldUnscaled(pt[0], pt[1], pt[2]);
          const wAhead = lonLatToWorldUnscaled(ahead[0], ahead[1], ahead[2]);
          const dx = wAhead[0] - wCur[0];
          const dz = wAhead[2] - wCur[2];
          const len = Math.hypot(dx, dz) || 1.0;
          const lookY = wCur[1] * exaggeration;
          controls.target.lerp(new THREE.Vector3(wCur[0], lookY, wCur[2]), 0.14);
          camera.position.lerp(new THREE.Vector3(wCur[0] - (dx / len) * 20, lookY + 13, wCur[2] - (dz / len) * 20), 0.10);
        }
      } else if (tweenState) {
        const rawT = Math.min(1, (now - tweenState.start) / tweenState.duration);
        const ease = 1 - Math.pow(1 - rawT, 3);
        camera.position.lerpVectors(tweenState.fromPos, tweenState.toPos, ease);
        controls.target.lerpVectors(tweenState.fromTarget, tweenState.toTarget, ease);
        if (rawT >= 1) tweenState = null;
      }

      controls.update();

      // Keep pan target bounded inside corridor slab
      const halfW = meta.world_width * 0.58;
      const halfD = meta.world_depth * 0.58;
      controls.target.x = Math.max(-halfW, Math.min(halfW, controls.target.x));
      controls.target.z = Math.max(-halfD, Math.min(halfD, controls.target.z));
      controls.target.y = Math.max(-1.5, Math.min(14, controls.target.y));

      updateOverlayProjections();
      renderer.render(scene, camera);

      // Auto-Hybrid handoff into sharp MapLibre street satellite when zoomed past threshold
      if (!flying && !tweenState && onRequestStreetZoomCb && now - lastHandoffTs > 500) {
        const geo = getCameraGeoState();
        if (geo.zoom >= STREET_ZOOM_ENTER) {
          lastHandoffTs = now;
          onRequestStreetZoomCb(geo);
        }
      }
    }

    rafId = requestAnimationFrame(renderLoop);
  }

  function startLoop() {
    if (!rafId && isActive) {
      lastLoopTs = performance.now();
      rafId = requestAnimationFrame(renderLoop);
    }
  }

  function setActive(val) {
    isActive = !!val;
    if (isActive) {
      lastHandoffTs = performance.now();
      handleResize();
      startLoop();
    } else if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  return {
    init: init,
    setActive: setActive,
    isActive: function () { return isActive; },
    isReady: function () { return assetsReady; },
    updateEntities: updateEntities,
    setImageryLayer: setImageryLayer,
    setTerrainExaggeration: setTerrainExaggeration,
    setMilestonesVisible: setMilestonesVisible,
    setToiletsVisible: setToiletsVisible,
    updateRadarTileLayer: updateRadarTileLayer,
    updateSkyForSolarAltitude: updateSkyForSolarAltitude,
    flyToCoordinate: flyToCoordinate,
    resetOverview: resetOverview,
    fitDualBounds: fitDualBounds,
    startFlyover: startFlyover,
    stopFlyover: stopFlyover,
    zoomByFactor: zoomByFactor,
    resetNorth: resetNorth,
    setOrbitDragMode: setOrbitDragMode,
    showScrubHoverPin: showScrubHoverPin,
    enableMapPinPick: enableMapPinPick,
    getCameraGeoState: getCameraGeoState,
    setCameraFromGeoState: setCameraFromGeoState,
    projectLonLat: projectLonLat
  };
})();
