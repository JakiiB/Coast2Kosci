"""
Bake pre-aligned DEM heightmap, blended Sentinel+Esri satellite textures (2K/4K/6K),
and shaded hypsometric topo relief texture for the Coast2Kosci Three.js 3D Diorama.
"""

import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

LON_MIN = 148.08
LON_MAX = 150.08
LAT_MIN = -37.23
LAT_MAX = -36.23

ELE_OFFSET_M = -100.0
ELE_SCALE_M = 2600.0

USER_AGENT = "Coast2Kosci-Diorama-Baker/1.0 (+https://jakiib.github.io/Coast2Kosci/)"


def merc_y_norm(lat_deg):
    rad = math.radians(lat_deg)
    sin_lat = math.sin(rad)
    return 0.5 - math.log((1.0 + sin_lat) / (1.0 - sin_lat)) / (4.0 * math.pi)


def lon_to_px(lon_deg, z):
    n = 256 * (1 << z)
    return ((lon_deg + 180.0) / 360.0) * n


def lat_to_px(lat_deg, z):
    n = 256 * (1 << z)
    return merc_y_norm(lat_deg) * n


def fetch_tile(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            return Image.open(BytesIO(data)).convert("RGB")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(0.35 * (attempt + 1))


def fetch_mosaic(name, url_builder, z):
    px0 = lon_to_px(LON_MIN, z)
    px1 = lon_to_px(LON_MAX, z)
    py0 = lat_to_px(LAT_MAX, z)
    py1 = lat_to_px(LAT_MIN, z)

    tx_min = math.floor(px0 / 256.0)
    tx_max = math.floor((px1 - 1e-6) / 256.0)
    ty_min = math.floor(py0 / 256.0)
    ty_max = math.floor((py1 - 1e-6) / 256.0)

    cols = tx_max - tx_min + 1
    rows = ty_max - ty_min + 1
    total = cols * rows
    print(f"[{name}] Fetching {total} tiles at z={z} ({cols}x{rows})...")

    mosaic = Image.new("RGB", (cols * 256, rows * 256))
    tasks = []
    for ty in range(ty_min, ty_max + 1):
        for tx in range(tx_min, tx_max + 1):
            tasks.append((tx, ty, url_builder(z, tx, ty)))

    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        future_map = {pool.submit(fetch_tile, url): (tx, ty) for tx, ty, url in tasks}
        for fut in as_completed(future_map):
            tx, ty = future_map[fut]
            tile_img = fut.result()
            mosaic.paste(tile_img, ((tx - tx_min) * 256, (ty - ty_min) * 256))
            done += 1
            if done % 60 == 0 or done == total:
                print(f"[{name}] {done}/{total} tiles")

    crop_box = (
        px0 - tx_min * 256.0,
        py0 - ty_min * 256.0,
        px1 - tx_min * 256.0,
        py1 - ty_min * 256.0,
    )
    return mosaic, crop_box


def gentle_smooth_2d(arr):
    # Separable 1D [0.2, 0.6, 0.2] convolution for slope smoothness without peak loss
    padded_x = np.pad(arr, ((0, 0), (1, 1)), mode="edge")
    sx = 0.2 * padded_x[:, :-2] + 0.6 * padded_x[:, 1:-1] + 0.2 * padded_x[:, 2:]
    padded_y = np.pad(sx, ((1, 1), (0, 0)), mode="edge")
    return 0.2 * padded_y[:-2, :] + 0.6 * padded_y[1:-1, :] + 0.2 * padded_y[2:, :]


def compute_hillshade(ele_m, dx_m, dy_m, azimuth_deg, altitude_deg):
    dz_dy, dz_dx = np.gradient(ele_m, dy_m, dx_m)
    # Top-down image: y increases southward, so North gradient = -dz_dy
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dx, dz_dy)
    az_rad = math.radians(azimuth_deg)
    zen_rad = math.radians(90.0 - altitude_deg)
    shade = np.cos(zen_rad) * np.cos(slope) + np.sin(zen_rad) * np.sin(slope) * np.cos(az_rad - aspect)
    return np.clip(shade, 0.0, 1.0)


def build_relief_texture(ele_4k, out_path):
    print("[Relief] Computing multi-directional hillshade & hypsometric relief (4096x2560)...")
    dx_m = 178440.0 / 4096.0
    dy_m = 111130.0 / 2560.0
    shade1 = compute_hillshade(ele_4k, dx_m, dy_m, 315.0, 42.0)
    shade2 = compute_hillshade(ele_4k, dx_m, dy_m, 250.0, 35.0)
    shade = np.clip(0.72 * shade1 + 0.28 * shade2, 0.0, 1.0)

    stops_m = np.array([0.0, 350.0, 800.0, 1300.0, 1750.0, 2050.0, 2228.0], dtype=np.float32)
    stops_rgb = np.array(
        [
            [31, 54, 43],
            [47, 69, 52],
            [85, 84, 65],
            [117, 104, 86],
            [148, 139, 130],
            [197, 204, 212],
            [237, 242, 247],
        ],
        dtype=np.float32,
    )

    h, w = ele_4k.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    for ch in range(3):
        rgb[:, :, ch] = np.interp(ele_4k, stops_m, stops_rgb[:, ch])

    land_mask = ele_4k > 0.5
    light_gain = (0.52 + 0.68 * shade)[:, :, None]
    rgb = np.where(land_mask[:, :, None], np.clip(rgb * light_gain, 0.0, 255.0), np.array([14.0, 27.0, 38.0]))

    # Subtle 250m elevation contour lines across land
    band = np.floor(np.maximum(0.0, ele_4k) / 250.0).astype(np.int32)
    contour = np.zeros((h, w), dtype=bool)
    contour[:, :-1] |= band[:, :-1] != band[:, 1:]
    contour[:-1, :] |= band[:-1, :] != band[1:, :]
    contour &= ele_4k > 10.0
    rgb[contour] *= 0.92

    img = Image.fromarray(np.clip(np.round(rgb), 0, 255).astype(np.uint8), mode="RGB")
    img.save(out_path, format="JPEG", quality=86, optimize=True, progressive=True)
    return shade


def main():
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "assets" / "corridor"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Bake 16-bit precision DEM heightmap (1024x640) + 4K float array for hillshading
    dem_mosaic, dem_crop = fetch_mosaic(
        "DEM-AWS",
        lambda z, x, y: f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
        11,
    )
    dem_arr = np.asarray(dem_mosaic, dtype=np.float64)
    ele_native = (dem_arr[:, :, 0] * 256.0 + dem_arr[:, :, 1] + dem_arr[:, :, 2] / 256.0) - 32768.0
    ele_f_img = Image.fromarray(ele_native.astype(np.float32), mode="F")

    ele_4k_img = ele_f_img.transform((4096, 2560), Image.Transform.EXTENT, dem_crop, resample=Image.Resampling.BICUBIC)
    ele_4k = np.asarray(ele_4k_img, dtype=np.float32)

    ele_1024_img = ele_f_img.transform((1024, 640), Image.Transform.EXTENT, dem_crop, resample=Image.Resampling.BICUBIC)
    ele_1024 = gentle_smooth_2d(np.asarray(ele_1024_img, dtype=np.float32))
    print(f"[DEM] Peak elevation baked: {float(np.max(ele_1024)):.1f} m (raw 4K max {float(np.max(ele_4k)):.1f} m)")

    val16 = np.clip(np.round((ele_1024 - ELE_OFFSET_M) / ELE_SCALE_M * 65535.0), 0, 65535).astype(np.uint16)
    h_rgb = np.zeros((640, 1024, 3), dtype=np.uint8)
    h_rgb[:, :, 0] = (val16 >> 8).astype(np.uint8)
    h_rgb[:, :, 1] = (val16 & 0xFF).astype(np.uint8)
    h_rgb[:, :, 2] = np.where(ele_1024 <= 0.5, 255, 0).astype(np.uint8)
    Image.fromarray(h_rgb, mode="RGB").save(out_dir / "height.png", format="PNG", optimize=True)

    # 2. Bake Hypsometric Topo Relief Texture (4096x2560) and retain shade for sat shading
    shade_4k = build_relief_texture(ele_4k, out_dir / "relief-4k.jpg")

    # 3. Bake Blended Esri (z=12) + EOxCloudless (z=11) Satellite Megatextures
    esri_mosaic, esri_crop = fetch_mosaic(
        "Esri-Sat",
        lambda z, x, y: f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        12,
    )
    eox_mosaic, eox_crop = fetch_mosaic(
        "EOx-Sentinel",
        lambda z, x, y: f"https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg",
        11,
    )

    print("[Sat] Compositing seamless 5760x3600 Esri + EOxCloudless corridor megatexture...")
    esri_6k = np.asarray(
        esri_mosaic.transform((5760, 3600), Image.Transform.EXTENT, esri_crop, resample=Image.Resampling.BICUBIC),
        dtype=np.float32,
    )
    eox_6k = np.asarray(
        eox_mosaic.transform((5760, 3600), Image.Transform.EXTENT, eox_crop, resample=Image.Resampling.BICUBIC),
        dtype=np.float32,
    )
    blend_6k = 0.78 * esri_6k + 0.22 * eox_6k

    # Subtle micro-relief contrast on land only
    shade_6k_img = Image.fromarray(shade_4k.astype(np.float32), mode="F").resize((5760, 3600), Image.Resampling.BILINEAR)
    ele_6k_img = ele_4k_img.resize((5760, 3600), Image.Resampling.BILINEAR)
    shade_6k = np.asarray(shade_6k_img, dtype=np.float32)
    ele_6k = np.asarray(ele_6k_img, dtype=np.float32)
    sat_gain = np.where(ele_6k > 1.0, 0.92 + 0.14 * shade_6k, 1.0)[:, :, None]
    sat_6k_img = Image.fromarray(np.clip(np.round(blend_6k * sat_gain), 0, 255).astype(np.uint8), mode="RGB")

    sat_6k_img.save(out_dir / "sat-6k.jpg", format="JPEG", quality=85, optimize=True, progressive=True)
    sat_6k_img.resize((4096, 2560), Image.Resampling.LANCZOS).save(
        out_dir / "sat-4k.jpg", format="JPEG", quality=85, optimize=True, progressive=True
    )
    sat_6k_img.resize((2048, 1280), Image.Resampling.LANCZOS).save(
        out_dir / "sat-2k.jpg", format="JPEG", quality=82, optimize=True, progressive=True
    )

    meta = {
        "lon_min": LON_MIN,
        "lon_max": LON_MAX,
        "lat_min": LAT_MIN,
        "lat_max": LAT_MAX,
        "merc_y_min": merc_y_norm(LAT_MAX),
        "merc_y_max": merc_y_norm(LAT_MIN),
        "width_km": 178.44,
        "height_km": 111.13,
        "world_width": 160.0,
        "world_depth": 100.0,
        "meters_per_unit": 1115.25,
        "ele_offset_m": ELE_OFFSET_M,
        "ele_scale_m": ELE_SCALE_M,
        "height_width": 1024,
        "height_height": 640,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    total_bytes = 0
    for fn in ["height.png", "sat-2k.jpg", "sat-4k.jpg", "sat-6k.jpg", "relief-4k.jpg", "meta.json"]:
        sz = (out_dir / fn).stat().st_size
        total_bytes += sz
        print(f"[Asset] {fn}: {sz / (1024 * 1024):.2f} MB")
    print(f"[Done] Total assets/corridor size: {total_bytes / (1024 * 1024):.2f} MB")


if __name__ == "__main__":
    main()
