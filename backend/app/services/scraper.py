"""
Scraping + images: product listing and pages, extract title/description/images, download and resize.
"""
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

log = logging.getLogger("app.services.scraper")

# Browser-like headers for product pages (reduce 403)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# Simpler headers for listing pages: some sites return SSR HTML with product links only without Sec-Fetch-* / Referer
LISTING_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _headers_for_url(url: str, custom_headers: dict | None = None) -> dict:
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    h = {**DEFAULT_HEADERS, **(custom_headers or {})}
    if "Referer" not in h:
        h["Referer"] = base + "/"
    return h


def fetch_html(url: str, *, timeout: int = 15, max_retries: int = 2, delay_sec: float = 1, headers: dict | None = None, use_headers_as_is: bool = False) -> str | None:
    for attempt in range(max_retries + 1):
        try:
            h = (headers if use_headers_as_is and headers else _headers_for_url(url, headers))
            r = requests.get(url, timeout=timeout, headers=h)
            if r.status_code in (403, 503, 429):
                time.sleep(delay_sec * (attempt + 1))
                continue
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt < max_retries:
                time.sleep(delay_sec * (attempt + 1))
            continue
    return None


def extract_product_links_from_listing(html: str, base_url: str, *, link_selector: str = "a[href*='/product'], a[href*='/products/']", href_attr: str = "href") -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select(link_selector):
        href = a.get(href_attr)
        if not href or not href.strip():
            continue
        full = urljoin(base_url, href.strip())
        if full not in links and (base_url in full or urlparse(base_url).netloc in full):
            links.append(full)
    if not links:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product" in href.lower() or "/p/" in href:
                full = urljoin(base_url, href)
                if full not in links:
                    links.append(full)
    # Fallback: regex for href with /products/ (handles JS-rendered or odd markup)
    if not links and "/products/" in html:
        for m in re.finditer(r'href\s*=\s*["\']([^"\']*?/products/[^"\']+)["\']', html, re.IGNORECASE):
            href = m.group(1).strip()
            if not href or "javascript:" in href.lower():
                continue
            full = urljoin(base_url, href)
            if full not in links and urlparse(full).path.count("/") >= 2:
                links.append(full)
    # Keep only product-detail URLs (skip /products/page/, /products/categories/, /products/feed)
    out = [u for u in links if "/products/page/" not in u and "/products/categories/" not in u and "/products/feed" not in u and "?page=" not in u]
    return out[:500]


def collect_product_links_from_all_pages(
    listing_url: str,
    base_url: str,
    *,
    max_pages: int = 25,
    timeout: int = 15,
    max_retries: int = 2,
    delay_sec: float = 1,
) -> list[str]:
    """Fetch listing page 1, 2, 3, ... and collect all unique product-detail links until empty page or max_pages."""
    log.info("Scraper: collect_product_links_from_all_pages started | max_pages=%s", max_pages)
    seen: set[str] = set()
    listing_base = listing_url.rstrip("/")
    for page in range(1, max_pages + 1):
        if page == 1:
            page_url = listing_url if listing_url.endswith("/") else listing_url + "/"
        else:
            page_url = f"{listing_base}/page/{page}/"
        time.sleep(delay_sec)
        html = fetch_html(page_url, timeout=timeout, max_retries=max_retries, delay_sec=delay_sec, headers=LISTING_HEADERS, use_headers_as_is=True)
        if not html and page > 1:
            # Try ?page=N style (e.g. WordPress)
            page_url_alt = f"{listing_base}?page={page}" if "?" not in listing_base else f"{listing_url}&page={page}"
            time.sleep(delay_sec)
            html = fetch_html(page_url_alt, timeout=timeout, max_retries=max_retries, delay_sec=delay_sec, headers=LISTING_HEADERS, use_headers_as_is=True)
        if not html:
            log.info("Scraper: pagination page %s empty or failed, stopping", page)
            break
        page_links = extract_product_links_from_listing(html, base_url)
        if not page_links:
            log.info("Scraper: pagination page %s had 0 product links, stopping", page)
            break
        new = [u for u in page_links if u not in seen]
        for u in new:
            seen.add(u)
        log.info("Scraper: page %s | new links=%s | total unique=%s", page, len(new), len(seen))
        if not new:
            break
    log.info("Scraper: collect_product_links_from_all_pages completed | total_unique_links=%s", len(seen))
    return list(seen)


def extract_product_data_from_page(
    html: str, page_url: str,
    *,
    title_selector: str = "h1, .product-title, .product-name, [data-product-name]",
    desc_selector: str = ".product-description, .description, [itemprop='description'], .product-details",
    image_selector: str = "img[src*='product'], .product-gallery img, .product-image img, main img",
    img_src_attr: str = "src",
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    title = ""
    for sel in title_selector.split(", "):
        el = soup.select_one(sel.strip())
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    description = ""
    for sel in desc_selector.split(", "):
        el = soup.select_one(sel.strip())
        if el:
            description = el.get_text(separator="\n", strip=True)
            if len(description) > 50:
                break
    if not description and soup.find("meta", attrs={"name": "description"}):
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            description = meta["content"]
    image_urls = []
    for el in soup.select(image_selector):
        src = el.get("data-src") or el.get("data-lazy-src") or el.get(img_src_attr)
        if not src:
            srcset = el.get("data-srcset") or el.get("srcset") or ""
            if isinstance(srcset, str) and srcset.strip():
                src = srcset.split(",")[0].strip().split()[0]
        if not src or not isinstance(src, str):
            continue
        src = src.strip()
        if not src.startswith("http"):
            src = urljoin(base, src)
        if src not in image_urls and _looks_like_product_image(src):
            image_urls.append(src)
    if not image_urls:
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if not src:
                continue
            if not src.startswith("http"):
                src = urljoin(base, src)
            if _looks_like_product_image(src) and src not in image_urls:
                image_urls.append(src)
    if not image_urls:
        og = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "og:image"})
        if og and og.get("content") and _looks_like_product_image(og["content"]):
            image_urls.append(urljoin(base, og["content"].strip()))
    # Prefer main product image: drop logo/partner URLs so first image is not Baja-Designs etc.
    filtered = [u for u in image_urls if not _is_likely_logo_or_partner(u)]
    if filtered:
        image_urls = filtered
    return {"title": title, "description": description, "image_urls": image_urls[:20]}


def _looks_like_product_image(url: str) -> bool:
    u = url.lower()
    if not u.startswith("http"):
        return False
    if any(skip in u for skip in ["icon", "logo", "sprite", "1x1", "pixel", "avatar"]):
        return False
    if any(x in u for x in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
        return True
    if "image" in u or "img" in u or "photo" in u or "product" in u or "uploads" in u or "wp-content" in u:
        return True
    return False


_LOGO_PARTNER_PATTERNS = (
    "baja-designs", "aluminess", "bestop", "bullring", "logo", "icon", "sprite",
    "avatar", "1x1", "pixel", "favicon", "brand-", "-logo", "partner", "sponsor",
)


def _is_likely_logo_or_partner(url: str) -> bool:
    """True if URL looks like a partner logo / brand image, not main product photo."""
    u = url.lower()
    return any(p in u for p in _LOGO_PARTNER_PATTERNS)


def download_image(url: str, dest_path: Path, *, timeout: int = 15, headers: dict | None = None) -> bool:
    try:
        h = headers or _headers_for_url(url)
        r = requests.get(url, timeout=timeout, headers=h)
        r.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(r.content)
        return True
    except Exception:
        return False


def resize_image(path: Path, max_width: int = 1000, max_height: int = 1000, quality: int = 90, output_format: str = "JPEG") -> bool:
    try:
        with Image.open(path) as im:
            im.load()
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            w, h = im.size
            if w <= max_width and h <= max_height:
                if path.suffix.upper() not in (".JPG", ".JPEG") and output_format == "JPEG":
                    path_new = path.with_suffix(".jpg")
                    im.save(path_new, output_format, quality=quality)
                    if path_new != path:
                        path.unlink(missing_ok=True)
                return True
            ratio = min(max_width / w, max_height / h)
            new_size = (int(w * ratio), int(h * ratio))
            im = im.resize(new_size, Image.Resampling.LANCZOS)
            out_path = path.with_suffix(".jpg") if output_format == "JPEG" else path
            im.save(out_path, output_format, quality=quality)
            if out_path != path:
                path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def scrape_single_product_page(
    url: str,
    *,
    timeout: int = 15,
    max_retries: int = 2,
    delay_sec: float = 1,
) -> dict[str, Any] | None:
    """Scrape one product page; return {title, description, image_urls} or None on failure."""
    html = fetch_html(url, timeout=timeout, max_retries=max_retries, delay_sec=delay_sec)
    if not html:
        return None
    return extract_product_data_from_page(html, url)


def download_and_resize_images_for_product(
    image_urls: list[str],
    output_dir: Path,
    prefix: str,
    *,
    max_width: int = 1000,
    max_height: int = 1000,
    max_images: int = 10,
    timeout: int = 15,
    resize: bool = True,
) -> list[Path]:
    """Download images; optionally resize. prefix used for filenames (e.g. SKU)."""
    paths: list[Path] = []
    prefix = re.sub(r"[^\w\-]", "_", prefix)[:60]
    for j, img_url in enumerate(image_urls[:max_images]):
        dest = output_dir / f"{prefix}_{j}.jpg"
        if download_image(img_url, dest, timeout=timeout):
            if resize:
                if resize_image(dest, max_width=max_width, max_height=max_height, quality=90):
                    paths.append(dest)
            else:
                paths.append(dest)
    return paths


def scrape_listing_and_pages(
    listing_url: str,
    base_url: str,
    output_images_dir: Path,
    *,
    max_products: int = 500,
    max_pages: int = 25,
    max_width: int = 1000,
    max_height: int = 1000,
    timeout: int = 15,
    max_retries: int = 2,
    delay_sec: float = 1,
    resize_images: bool = True,
) -> list[dict[str, Any]]:
    # Collect product links from all pagination pages first
    product_urls = collect_product_links_from_all_pages(
        listing_url, base_url, max_pages=max_pages, timeout=timeout, max_retries=max_retries, delay_sec=delay_sec,
    )
    if not product_urls:
        log.warning("Scraper: no product links found from any listing page | url=%s", listing_url[:60])
        return []
    product_urls = product_urls[:max_products]
    log.info("Scraper: scraping %s product pages (extract data + image URLs only, no download)", len(product_urls))
    results = []
    for i, url in enumerate(product_urls):
        time.sleep(delay_sec)
        if (i + 1) % 25 == 0 or i == 0 or i == len(product_urls) - 1:
            log.info("Scraper: product page progress %s/%s", i + 1, len(product_urls))
        page_html = fetch_html(url, timeout=timeout, max_retries=max_retries, delay_sec=delay_sec, headers=LISTING_HEADERS, use_headers_as_is=True)
        if not page_html:
            continue
        data = extract_product_data_from_page(page_html, url)
        # Map image URLs only; no download (export uses URL in Image 1 File)
        results.append({
            "url": url, "title": data.get("title", ""), "description": data.get("description", ""),
            "image_paths": [], "image_urls": data.get("image_urls", []),
        })
    log.info("Scraper: scrape_listing_and_pages done | scraped=%s products", len(results))
    return results
