import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests
from pypdf import PdfReader

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_scrape"
DOCS_DIR = BASE_DIR / "official_docs"
PDF_TEXT_DIR = RAW_DIR / "pdf_texts"
PAGES_DIR = RAW_DIR / "pages"
TRACKING_DIR = RAW_DIR / "tracking"

for d in [RAW_DIR, DOCS_DIR, PDF_TEXT_DIR, PAGES_DIR, TRACKING_DIR]:
    d.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

CAPTCHA_MARKERS = [
    "cf-turnstile",
    "g-recaptcha",
    "hcaptcha",
    "verify you are human",
    "just a moment...",
    "attention required! | cloudflare",
]


class CleanTextExtractor(HTMLParser):
    def __init__(self, base_url="https://coasttokosci.com"):
        super().__init__()
        self.base_url = base_url
        self.skip_depth = 0
        self.in_main = False
        self.chunks = []
        self.links = []
        self.iframes = []
        self.images = []
        self.tables = []
        self._in_table = False
        self._current_table = []
        self._current_row = []
        self._in_cell = False
        self._cell_chunks = []
        self._in_a = False
        self._a_href = ""
        self._a_text = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "br", "tr", "div", "section", "article"):
            self.chunks.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.chunks.append(f"[{tag.upper()}] ")
        if tag == "li":
            self.chunks.append("- ")

        if tag == "a" and "href" in attr_dict:
            self._in_a = True
            self._a_href = urllib.parse.urljoin(self.base_url, attr_dict["href"])
            self._a_text = []
        elif tag == "iframe" and "src" in attr_dict:
            self.iframes.append(urllib.parse.urljoin(self.base_url, attr_dict["src"]))
        elif tag == "img" and "src" in attr_dict:
            self.images.append({
                "src": urllib.parse.urljoin(self.base_url, attr_dict["src"]),
                "alt": attr_dict.get("alt", ""),
            })
        elif tag == "table":
            self._in_table = True
            self._current_table = []
        elif tag == "tr" and self._in_table:
            self._current_row = []
        elif tag in ("td", "th") and self._in_table:
            self._in_cell = True
            self._cell_chunks = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return
        if self.skip_depth > 0:
            return

        if tag == "a" and self._in_a:
            txt = " ".join("".join(self._a_text).split())
            self.links.append({"text": txt, "href": self._a_href})
            self._in_a = False
        elif tag in ("td", "th") and self._in_cell:
            cell_txt = " ".join("".join(self._cell_chunks).split())
            self._current_row.append(cell_txt)
            self._in_cell = False
        elif tag == "tr" and self._in_table:
            if any(self._current_row):
                self._current_table.append(self._current_row)
        elif tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._in_table = False

        if tag in ("h1", "h2", "h3", "h4", "p", "li", "tr"):
            self.chunks.append("\n")

    def handle_data(self, data):
        if self.skip_depth > 0:
            return
        txt = unescape(data)
        self.chunks.append(txt)
        if self._in_a:
            self._a_text.append(txt)
        if self._in_cell:
            self._cell_chunks.append(txt)

    def get_clean_text(self):
        raw = "".join(self.chunks)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        cleaned = []
        for line in lines:
            if line:
                cleaned.append(line)
        return "\n".join(cleaned)


def check_captcha(text, url):
    low = text.lower()
    for marker in CAPTCHA_MARKERS:
        if marker in low:
            raise RuntimeError(f"CAPTCHA/Challenge detected at {url}: marker='{marker}'")


def fetch_url(url, timeout=30, as_json=False):
    resp = SESSION.get(url, timeout=timeout, allow_redirects=True)
    if resp.status_code in (403, 429, 503):
        check_captcha(resp.text, url)
    resp.raise_for_status()
    if not as_json:
        check_captcha(resp.text[:5000], url)
        return resp
    return resp.json(), resp.headers


def extract_html_content(html_str, base_url="https://coasttokosci.com"):
    parser = CleanTextExtractor(base_url=base_url)
    parser.feed(html_str)
    return {
        "text": parser.get_clean_text(),
        "links": parser.links,
        "iframes": parser.iframes,
        "images": parser.images,
        "tables": parser.tables,
    }


def slugify_filename(url):
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(parsed.path) or "index"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name


def harvest_wp_rest_collection(endpoint):
    items = []
    page = 1
    while True:
        sep = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{sep}per_page=100&page={page}"
        try:
            resp = SESSION.get(url, timeout=30)
            if resp.status_code == 400:
                break
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                break
            items.extend(data)
            total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            print(f"[WARN] WP API {url}: {e}")
            break
    return items


def harvest_sitemaps():
    urls = set()
    candidates = [
        "https://coasttokosci.com/wp-sitemap.xml",
        "https://coasttokosci.com/sitemap_index.xml",
        "https://coasttokosci.com/sitemap.xml",
    ]
    visited_sitemaps = set()
    queue = list(candidates)
    while queue:
        sm_url = queue.pop(0)
        if sm_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sm_url)
        try:
            resp = SESSION.get(sm_url, timeout=20)
            if resp.status_code != 200 or "<" not in resp.text:
                continue
            root = ET.fromstring(resp.text.encode("utf-8", errors="ignore"))
            for elem in root.iter():
                if elem.tag.endswith("loc") and elem.text:
                    loc = elem.text.strip()
                    if loc.endswith(".xml"):
                        queue.append(loc)
                    else:
                        urls.add(loc)
        except Exception as e:
            print(f"[INFO] Sitemap skip {sm_url}: {e}")
    return sorted(urls)


def is_downloadable_doc(url):
    low = url.lower().split("?")[0]
    exts = (".pdf", ".gpx", ".kml", ".kmz", ".xlsx", ".xls", ".csv", ".doc", ".docx", ".txt", ".zip", ".json", ".geojson")
    return any(low.endswith(ext) for ext in exts)


def is_course_or_info_image(url, title="", alt=""):
    low = f"{url} {title} {alt}".lower()
    if not any(low.split("?")[0].endswith(ext) or ext in url.lower() for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return False
    keywords = (
        "map", "course", "route", "elevation", "profile", "checkpoint", "cp",
        "schedule", "cutoff", "cut-off", "guide", "sign", "vehicle", "gear",
        "boydtown", "towamba", "rocky", "cathcart", "dalgety", "jindabyne",
        "perisher", "charlotte", "kosci", "big-jack", "beloka", "summit",
        "toilet", "chart", "table", "2026", "2025", "2024", "poster", "flyer",
    )
    return any(k in low for k in keywords)


def download_file(url, dest_path):
    try:
        resp = SESSION.get(url, timeout=45, stream=True)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)
        return dest_path.stat().st_size
    except Exception as e:
        print(f"[WARN] Failed download {url}: {e}")
        return 0


def extract_pdf_text(pdf_path, txt_path):
    try:
        reader = PdfReader(str(pdf_path))
        pages = []
        for idx, page in enumerate(reader.pages, start=1):
            t = page.extract_text() or ""
            pages.append(f"--- PAGE {idx} ---\n{t}")
        full_text = "\n\n".join(pages)
        txt_path.write_text(full_text, encoding="utf-8")
        return len(reader.pages), len(full_text)
    except Exception as e:
        print(f"[WARN] PDF extract error {pdf_path.name}: {e}")
        return 0, 0


def query_trackmelive(discovered_urls):
    tml_results = []
    candidate_urls = set()
    for u in discovered_urls:
        if "trackmelive" in u.lower() or "opentracking" in u.lower() or "followmychallenge" in u.lower():
            candidate_urls.add(u)
    candidate_urls.add("https://www.trackmelive.com.au/")
    candidate_urls.add("https://trackmelive.com.au/")

    try:
        resp = fetch_url("https://www.trackmelive.com.au/", timeout=25)
        parsed = extract_html_content(resp.text, "https://www.trackmelive.com.au/")
        for lnk in parsed["links"]:
            href = lnk["href"]
            txt = lnk["text"]
            if any(k in (href + " " + txt).lower() for k in ("kosci", "c2k", "coast")):
                candidate_urls.add(href)
        # Also regex search HTML for coast/kosci event slugs/IDs
        for m in re.findall(r'https?://[^\s"\'<>]*(?:kosci|c2k|coast)[^\s"\'<>]*', resp.text, re.I):
            candidate_urls.add(m)
        for m in re.findall(r'href=["\']([^"\']*(?:kosci|c2k|coast)[^"\']*)["\']', resp.text, re.I):
            candidate_urls.add(urllib.parse.urljoin("https://www.trackmelive.com.au/", m))
    except Exception as e:
        print(f"[WARN] TrackMeLive index fetch error: {e}")

    for idx, url in enumerate(sorted(candidate_urls)):
        try:
            resp = fetch_url(url, timeout=25)
            out_file = TRACKING_DIR / f"tracking_{idx}_{slugify_filename(url)}.html"
            out_file.write_text(resp.text, encoding="utf-8", errors="ignore")
            parsed = extract_html_content(resp.text, url)
            # Search for embedded JSON / GeoJSON / GPX / KML / API URLs
            data_refs = re.findall(
                r'https?://[^\s"\'<>]+\.(?:gpx|kml|json|geojson|csv)|/[^\s"\'<>]*(?:api|event|route|checkpoint|course)[^\s"\'<>]*',
                resp.text,
                re.I,
            )
            tml_results.append({
                "url": resp.url,
                "status": resp.status_code,
                "text_preview": parsed["text"][:4000],
                "links": [l for l in parsed["links"] if any(k in (l["href"]+l["text"]).lower() for k in ("kosci", "c2k", "coast", "gpx", "map", "track"))],
                "data_refs": sorted(set(data_refs))[:50],
                "saved_html": str(out_file),
            })
        except Exception as e:
            tml_results.append({"url": url, "error": str(e)})

    (RAW_DIR / "trackmelive_probe.json").write_text(json.dumps(tml_results, indent=2), encoding="utf-8")
    return tml_results


def query_osm_corridor_amenities():
    """
    Query OpenStreetMap Overpass API for public toilets, community halls,
    fuel stations, convenience stores, and shelters along key C2K towns/waypoints.
    """
    # Query around each key waypoint node/area along the 240 km corridor to stay fast and accurate
    corridor_points = [
        ("Boydtown / Seahorse Inn", -37.0995, 149.8825, 2500),
        ("Towamba", -37.0815, 149.6805, 3000),
        ("Rocky Hall", -36.9350, 149.5550, 3500),
        ("Wyndham", -36.9330, 149.6330, 2500),
        ("Cathcart", -36.8460, 149.4060, 3000),
        ("Bibbenluke", -36.7980, 149.3050, 2500),
        ("Bombala / Gunningrah", -36.9120, 149.2420, 5000),
        ("Dalgety", -36.5020, 148.8380, 3000),
        ("Berridale", -36.3640, 148.8290, 3000),
        ("Jindabyne", -36.4150, 148.6220, 4500),
        ("Sawpit Creek", -36.3510, 148.5630, 2500),
        ("Smiggin Holes", -36.3910, 148.4320, 2000),
        ("Perisher Valley", -36.4040, 148.4110, 2500),
        ("Charlotte Pass", -36.4330, 148.3310, 2000),
        ("Seamans Hut / Rawson Pass / Kosciuszko", -36.4580, 148.2730, 3500),
    ]

    overpass_urls = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    results = {}
    for label, lat, lon, rad in corridor_points:
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="toilets"](around:{rad},{lat},{lon});
          way["amenity"="toilets"](around:{rad},{lat},{lon});
          node["amenity"="community_centre"](around:{rad},{lat},{lon});
          way["amenity"="community_centre"](around:{rad},{lat},{lon});
          node["amenity"="fuel"](around:{rad},{lat},{lon});
          way["amenity"="fuel"](around:{rad},{lat},{lon});
          node["shop"~"convenience|general|supermarket"](around:{rad},{lat},{lon});
          way["shop"~"convenience|general|supermarket"](around:{rad},{lat},{lon});
          node["amenity"="drinking_water"](around:{rad},{lat},{lon});
          node["tourism"="alpine_hut"](around:{rad},{lat},{lon});
          way["tourism"="alpine_hut"](around:{rad},{lat},{lon});
          node["place"~"town|village|hamlet|locality"](around:{rad},{lat},{lon});
        );
        out center tags;
        """
        fetched = None
        for op_url in overpass_urls:
            try:
                r = SESSION.post(op_url, data={"data": query}, timeout=30)
                if r.status_code == 200:
                    fetched = r.json()
                    break
            except Exception as e:
                print(f"[WARN] Overpass {op_url} for {label}: {e}")
        elements = []
        if fetched and "elements" in fetched:
            for el in fetched["elements"]:
                el_lat = el.get("lat") or el.get("center", {}).get("lat")
                el_lon = el.get("lon") or el.get("center", {}).get("lon")
                tags = el.get("tags", {})
                elements.append({
                    "id": el.get("id"),
                    "type": el.get("type"),
                    "lat": el_lat,
                    "lon": el_lon,
                    "tags": tags,
                })
        results[label] = {
            "search_center": {"lat": lat, "lon": lon, "radius_m": rad},
            "count": len(elements),
            "elements": elements,
        }
        time.sleep(0.6)

    (RAW_DIR / "osm_corridor_amenities.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main():
    print("=== Step 2A: Probing Coast to Kosci WordPress API & Sitemaps ===")
    wp_pages = harvest_wp_rest_collection("https://coasttokosci.com/wp-json/wp/v2/pages")
    wp_posts = harvest_wp_rest_collection("https://coasttokosci.com/wp-json/wp/v2/posts")
    wp_media = harvest_wp_rest_collection("https://coasttokosci.com/wp-json/wp/v2/media")
    sitemap_urls = harvest_sitemaps()

    print(f"WP API -> pages: {len(wp_pages)}, posts: {len(wp_posts)}, media: {len(wp_media)}, sitemap URLs: {len(sitemap_urls)}")

    # Save raw WP collections
    (RAW_DIR / "wp_pages.json").write_text(json.dumps(wp_pages, indent=2), encoding="utf-8")
    (RAW_DIR / "wp_posts.json").write_text(json.dumps(wp_posts, indent=2), encoding="utf-8")
    (RAW_DIR / "wp_media.json").write_text(json.dumps(wp_media, indent=2), encoding="utf-8")

    # Gather all page URLs to scrape directly as live HTML
    seed_urls = {
        "https://coasttokosci.com/",
        "https://coasttokosci.com/course/",
        "https://coasttokosci.com/runners-guide/",
        "https://coasttokosci.com/race-rules/",
        "https://coasttokosci.com/race-schedule/",
        "https://coasttokosci.com/about/",
        "https://coasttokosci.com/contact/",
    }
    for p in wp_pages:
        if p.get("link"):
            seed_urls.add(p["link"])
    for p in wp_posts:
        if p.get("link"):
            seed_urls.add(p["link"])
    for u in sitemap_urls:
        if u.startswith("https://coasttokosci.com"):
            seed_urls.add(u)

    scraped_pages = {}
    discovered_links = set()
    discovered_docs = {}
    discovered_images = {}

    # Inspect WP API pages/posts content first for links/docs
    for collection_name, coll in [("page", wp_pages), ("post", wp_posts)]:
        for item in coll:
            link = item.get("link", "")
            title = unescape(item.get("title", {}).get("rendered", ""))
            html_body = item.get("content", {}).get("rendered", "")
            parsed = extract_html_content(html_body, link or "https://coasttokosci.com/")
            for l in parsed["links"]:
                discovered_links.add(l["href"])
                if is_downloadable_doc(l["href"]):
                    discovered_docs[l["href"]] = l["text"] or slugify_filename(l["href"])
            for img in parsed["images"]:
                if is_course_or_info_image(img["src"], title=title, alt=img["alt"]):
                    discovered_images[img["src"]] = img["alt"] or title

    # Inspect WP media library
    media_index = []
    for m in wp_media:
        src = m.get("source_url", "")
        title = unescape(m.get("title", {}).get("rendered", ""))
        alt = m.get("alt_text", "")
        mime = m.get("mime_type", "")
        media_index.append({
            "id": m.get("id"),
            "date": m.get("date"),
            "title": title,
            "alt": alt,
            "mime": mime,
            "url": src,
        })
        if src:
            if is_downloadable_doc(src) or "pdf" in mime or "gpx" in mime or "xml" in mime:
                discovered_docs[src] = title or slugify_filename(src)
            elif is_course_or_info_image(src, title=title, alt=alt):
                discovered_images[src] = title or alt

    (RAW_DIR / "media_index.json").write_text(json.dumps(media_index, indent=2), encoding="utf-8")

    # Crawl HTML pages on coasttokosci.com (limit to 80 pages to stay tidy)
    visited = set()
    queue = sorted(seed_urls)
    while queue and len(visited) < 80:
        url = queue.pop(0)
        norm = url.split("#")[0].rstrip("/") + "/"
        if norm in visited:
            continue
        if not norm.startswith("https://coasttokosci.com"):
            continue
        if is_downloadable_doc(norm) or any(norm.lower().endswith(ext + "/") for ext in (".jpg", ".png", ".jpeg", ".webp", ".gif")):
            continue
        visited.add(norm)
        try:
            resp = fetch_url(url, timeout=25)
            parsed = extract_html_content(resp.text, resp.url)
            slug = slugify_filename(urllib.parse.urlparse(resp.url).path.strip("/") or "home")
            (PAGES_DIR / f"{slug}.txt").write_text(parsed["text"], encoding="utf-8")
            (PAGES_DIR / f"{slug}.html").write_text(resp.text, encoding="utf-8", errors="ignore")
            scraped_pages[resp.url] = {
                "status": resp.status_code,
                "char_count": len(parsed["text"]),
                "tables_count": len(parsed["tables"]),
                "tables": parsed["tables"],
                "iframes": parsed["iframes"],
                "links": parsed["links"],
                "text_file": str(PAGES_DIR / f"{slug}.txt"),
            }
            # Extract URLs from raw HTML too (e.g., Google Drive / Dropbox / PDF links)
            for l in parsed["links"]:
                href = l["href"]
                discovered_links.add(href)
                if is_downloadable_doc(href):
                    discovered_docs[href] = l["text"] or slugify_filename(href)
                elif href.startswith("https://coasttokosci.com") and not any(
                    x in href.lower() for x in ("wp-login", "wp-json", "/feed", "mailto:", "tel:")
                ):
                    n_href = href.split("#")[0].rstrip("/") + "/"
                    if n_href not in visited and n_href not in queue:
                        queue.append(n_href)
            for img in parsed["images"]:
                if is_course_or_info_image(img["src"], alt=img["alt"]):
                    discovered_images[img["src"]] = img["alt"]
            for raw_ref in re.findall(r'https?://[^\s"\'<>]+\.(?:pdf|gpx|kml|kmz|xlsx|csv)', resp.text, re.I):
                discovered_docs[raw_ref] = slugify_filename(raw_ref)
        except Exception as e:
            print(f"[WARN] Page fetch {url}: {e}")
            scraped_pages[url] = {"error": str(e)}

    (RAW_DIR / "scraped_pages.json").write_text(json.dumps(scraped_pages, indent=2), encoding="utf-8")

    print(f"=== Step 2B: Downloading {len(discovered_docs)} docs and {len(discovered_images)} course/map images ===")
    downloaded_files = []
    for url, desc in sorted(discovered_docs.items()):
        fname = slugify_filename(url)
        dest = DOCS_DIR / fname
        size = download_file(url, dest)
        entry = {"url": url, "description": desc, "local_path": str(dest), "size_bytes": size}
        if size > 0 and fname.lower().endswith(".pdf"):
            num_pages, text_len = extract_pdf_text(dest, PDF_TEXT_DIR / f"{fname}.txt")
            entry["pdf_pages"] = num_pages
            entry["pdf_text_chars"] = text_len
            entry["pdf_text_path"] = str(PDF_TEXT_DIR / f"{fname}.txt")
        downloaded_files.append(entry)

    for url, desc in sorted(discovered_images.items()):
        fname = slugify_filename(url)
        dest = DOCS_DIR / fname
        if not dest.exists():
            size = download_file(url, dest)
            downloaded_files.append({"url": url, "description": desc, "local_path": str(dest), "size_bytes": size})

    print("=== Step 2C: Probing TrackMeLive / Tracking Links ===")
    tml = query_trackmelive(discovered_links)

    print("=== Step 2D: Querying OpenStreetMap Corridor Amenities & Public Toilets ===")
    osm = query_osm_corridor_amenities()

    summary = {
        "wp_pages_count": len(wp_pages),
        "wp_posts_count": len(wp_posts),
        "wp_media_count": len(wp_media),
        "scraped_pages_count": len(scraped_pages),
        "scraped_urls": sorted(scraped_pages.keys()),
        "downloaded_files": downloaded_files,
        "external_links_sample": sorted(
            [u for u in discovered_links if not u.startswith("https://coasttokosci.com")]
        )[:100],
        "trackmelive_results": len(tml),
        "osm_corridor_zones": {k: v["count"] for k, v in osm.items()},
    }
    (RAW_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("=== Scrape Complete! ===")
    print(json.dumps({
        "pages": len(scraped_pages),
        "media": len(wp_media),
        "downloaded_files": len(downloaded_files),
        "osm_zones": len(osm),
    }, indent=2))


if __name__ == "__main__":
    main()
