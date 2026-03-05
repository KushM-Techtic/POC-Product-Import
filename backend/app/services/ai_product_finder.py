"""
AI product finder: use web search (Tavily) + OpenAI to find the product on the web,
pick one source (e.g. Amazon, Flipkart), then extract full page content + images
via Tavily Extract to get entire description and main product image URL.
Correct matching is mandatory: AI must identify the same product (SKU/model), not a different variant.
"""
import json
import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from app.logger import get_logger

log = get_logger("app.services.ai_product_finder")

# Schema we ask AI to return
RESULT_KEYS = ("name", "description", "price", "image_url", "source_website")

# Search method: "tavily" = Tavily search + extract; "openai" = OpenAI Responses API with web_search tool
SEARCH_METHOD_TAVILY = "tavily"
SEARCH_METHOD_OPENAI = "openai"

# Regex to find image URLs in text (common extensions and CDN paths)
_IMAGE_URL_RE = re.compile(
    r"https?://[^\s<>\"']+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)
# Also match common CDN/cloud patterns that don't always have extension
_IMAGE_URL_ALT_RE = re.compile(
    r"https?://(?:[a-zA-Z0-9-]+\.)*(?:amazonaws|cloudfront|img|images?|cdn|static|wp-content/uploads)[^\s<>\"']+",
    re.IGNORECASE,
)
# Relative paths (need base_url to resolve)
_IMAGE_URL_RELATIVE_RE = re.compile(
    r"[/][^\s<>\"']+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)


def _source_domain(url: str) -> str:
    """Normalized domain (netloc) for comparison: lowercase, no leading www."""
    if not url or not url.startswith("http"):
        return ""
    try:
        netloc = (urlparse(url).netloc or "").lower().strip()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def _filter_images_same_domain(image_urls: list[str], source_url: str) -> list[str]:
    """Keep only image URLs that belong to the same site as source_url. Allows same domain, subdomains, and same-brand CDNs (e.g. media-amazon.com for amazon.com)."""
    if not source_url or not image_urls:
        return list(image_urls)
    base_domain = _source_domain(source_url)
    if not base_domain:
        return list(image_urls)
    # Allow same domain, subdomains (e.g. cdn.trucksrus.shop for trucksrus.shop), and same-brand CDN (e.g. m.media-amazon.com for www.amazon.com)
    source_core = base_domain.split(".")[0] if base_domain else ""
    out = []
    for u in image_urls:
        if not u or not (u := u.strip()).startswith("http"):
            continue
        d = _source_domain(u)
        if d == base_domain or d.endswith("." + base_domain):
            out.append(u)
        elif source_core and len(source_core) > 2 and source_core in d:
            # Same brand/site CDN (e.g. amazon.com -> m.media-amazon.com, fls-na.amazon.com)
            out.append(u)
    return out


def _extract_image_urls_from_text(text: str, max_urls: int = 15, base_url: str | None = None) -> list[str]:
    """Pull image-like URLs from raw text (e.g. page content). Optionally resolve relative URLs with base_url."""
    if not text:
        return []
    seen = set()
    out = []
    for pat in (_IMAGE_URL_RE, _IMAGE_URL_ALT_RE):
        for m in pat.finditer(text):
            url = m.group(0).rstrip(".,;:)")
            if url not in seen and "favicon" not in url.lower() and "logo" not in url.lower():
                seen.add(url)
                if base_url and url.startswith("//"):
                    url = "https:" + url
                out.append(url)
                if len(out) >= max_urls:
                    return out
    if base_url:
        try:
            p = urlparse(base_url)
            base_origin = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else base_url
        except Exception:
            base_origin = base_url
        for m in _IMAGE_URL_RELATIVE_RE.finditer(text):
            url = m.group(0).rstrip(".,;:)")
            if url not in seen and "logo" not in url.lower() and "favicon" not in url.lower():
                seen.add(url)
                full = urljoin(base_origin, url)
                if full.startswith("http"):
                    out.append(full)
                    if len(out) >= max_urls:
                        return out
    return out


def _is_bad_image_url(url: str) -> bool:
    """True if URL is a template placeholder or known non-product image (captcha, etc.)."""
    if not url or not isinstance(url, str):
        return True
    u = url.strip().lower()
    if "{{" in u or "}}" in u:
        return True
    if "captcha" in u or "recaptcha" in u:
        return True
    return False


def _normalize_image_list(images: Any) -> list[str]:
    """Convert Tavily/API image list to list of URL strings (handles list of dicts or list of strings)."""
    if not images or not isinstance(images, list):
        return []
    out = []
    for item in images:
        if isinstance(item, str) and item.strip().startswith("http"):
            out.append(item.strip())
        elif isinstance(item, dict):
            u = item.get("url") or item.get("src") or item.get("image_url") or ""
            if isinstance(u, str) and u.strip().startswith("http"):
                out.append(u.strip())
        if len(out) >= 20:
            break
    return out


def _resolve_url(u: str, base_full: str, base: str) -> str:
    """Resolve relative or protocol-relative URL to absolute."""
    if not u:
        return ""
    u = u.strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(base_full, u)
    if not u.startswith("http"):
        return urljoin(base, u)
    return u


def _is_skip_image(u: str) -> bool:
    """True if URL is a logo, icon, tracking pixel, placeholder, or captcha to skip."""
    if not u:
        return True
    ul = u.lower()
    skip_kw = ("logo", "favicon", "icon", "placeholder", "captcha", "recaptcha",
               "tracking", "pixel", "blank", "spacer", "banner", "flag.png",
               "shipping.png", "warning.png", "sprite", "badge", "star", "rating",
               "arrow", "button", "loader", "spinner", "{{")
    return any(k in ul for k in skip_kw) or "data:" in ul


def _fetch_page_html(page_url: str, timeout: int = 12) -> str:
    """Fetch page HTML with a browser-like User-Agent."""
    if not page_url or not page_url.startswith("http"):
        return ""
    try:
        req = Request(page_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("Fetch page HTML failed | url=%s | %s", page_url[:60], e)
        return ""


def _extract_product_image_from_html(
    html: str,
    page_url: str,
    sku: str = "",
    mpn: str = "",
) -> str:
    """
    Extract the main product image from page HTML using priority layers:
    1. og:image meta tag (explicitly declares the page's main image)
    2. JSON-LD structured data Product.image
    3. <img> or link[rel=image_src] whose URL contains the SKU or MPN
    Returns the best image URL found, or "" if nothing found.
    """
    if not html:
        return ""
    base_scheme = urlparse(page_url)
    base_full = f"{base_scheme.scheme}://{base_scheme.netloc}"
    base = page_url.rsplit("/", 1)[0] + "/"

    def resolve(u: str) -> str:
        return _resolve_url(u, base_full, base)

    # --- Layer 1: og:image / twitter:image meta tags ---
    for pattern in (
        r'<meta\s+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
        r'<meta\s+(?:property|name)=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']twitter:image["\']',
    ):
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            u = resolve(m.group(1).strip())
            if u and not _is_skip_image(u):
                log.info("Image layer 1 (og:image): %s", u[:80])
                return u

    # --- Layer 2: JSON-LD structured data Product.image ---
    for script in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL):
        try:
            data = json.loads(script.strip())
            # Handle @graph arrays
            if isinstance(data, dict) and data.get("@graph"):
                data = data["@graph"]
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                t = str(item.get("@type", "")).lower()
                if "product" not in t and "offer" not in t:
                    continue
                img = item.get("image")
                if isinstance(img, list):
                    img = img[0] if img else ""
                if isinstance(img, dict):
                    img = img.get("url") or img.get("contentUrl") or ""
                if img and isinstance(img, str):
                    u = resolve(img.strip())
                    if u and not _is_skip_image(u):
                        log.info("Image layer 2 (JSON-LD): %s", u[:80])
                        return u
        except Exception:
            continue

    # --- Layer 3: <img> whose src URL contains the SKU or MPN ---
    if sku or mpn:
        sku_clean = re.sub(r"[\-_\s]", "", (sku or "").lower())
        mpn_clean = re.sub(r"[\-_\s]", "", (mpn or "").lower())
        for attr in ("data-src", "data-lazy-src", "data-zoom-image", "src"):
            for m in re.finditer(rf'<img[^>]+{re.escape(attr)}=["\']([^"\']+)["\']', html, re.IGNORECASE):
                u = resolve(m.group(1).strip())
                if not u or _is_skip_image(u):
                    continue
                u_lower = re.sub(r"[\-_\s]", "", u.lower())
                if (sku_clean and sku_clean in u_lower) or (mpn_clean and mpn_clean in u_lower):
                    log.info("Image layer 3 (SKU in URL): %s", u[:80])
                    return u

    return ""


def _fetch_image_urls_from_page(page_url: str, timeout: int = 12) -> list[str]:
    """Fetch product page HTML and return sorted product image candidates (fallback when layers 1–3 fail)."""
    html = _fetch_page_html(page_url, timeout=timeout)
    if not html:
        return []
    base_scheme = urlparse(page_url)
    base_full = f"{base_scheme.scheme}://{base_scheme.netloc}"
    base = page_url.rsplit("/", 1)[0] + "/"

    def resolve(u: str) -> str:
        return _resolve_url(u, base_full, base)

    seen: set[str] = set()
    urls: list[str] = []
    for attr in ("data-zoom-image", "data-src", "data-lazy-src", "src"):
        for m in re.finditer(rf'<img[^>]+{re.escape(attr)}=["\']([^"\']+)["\']', html, re.IGNORECASE):
            u = resolve(m.group(1).strip())
            if u and u not in seen and not _is_skip_image(u) and u.startswith("http"):
                seen.add(u)
                urls.append(u)

    if not urls:
        urls = _extract_image_urls_from_text(html, max_urls=15, base_url=base_full)

    log.info("Fetched %s image URLs from page HTML first=%s", len(urls), (urls[0][:80] if urls else "none"))
    for i, u in enumerate(urls[:5]):
        log.info("  fetch image[%s]=%s", i, u[:90])
    return urls


def _extract_page_content(url: str, query: str, include_images: bool = True) -> tuple[str, list[str]]:
    """Use Tavily Extract to get full page content and image URLs. Returns (raw_content, image_urls)."""
    api_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not api_key:
        return "", []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.extract(
            urls=[url],
            query=query[:200] if query else None,
            chunks_per_source=5,
            include_images=include_images,
            extract_depth="advanced",
        )
        results = response.get("results") if isinstance(response, dict) else getattr(response, "results", [])
        log.info("Tavily extract response: %s results, keys=%s", len(results) if results else 0, list(r.keys()) if results and isinstance(r := (results[0] if isinstance(results, list) else results), dict) else "n/a")
        if not results:
            return "", []
        r = results[0] if isinstance(results, list) else results
        raw = r.get("raw_content", "") or ""
        raw_images = r.get("images")
        log.info("Tavily extract: raw_content len=%s, raw images type=%s len=%s sample=%s", len(raw), type(raw_images).__name__, len(raw_images) if isinstance(raw_images, list) else 0, (raw_images[:2] if isinstance(raw_images, list) and raw_images else raw_images))
        images = _normalize_image_list(r.get("images") if isinstance(r.get("images"), list) else [])
        log.info("Tavily extract: normalized images count=%s first=%s", len(images), (images[0][:80] if images else "none"))
        return raw, images
    except Exception as e:
        log.warning("Tavily extract failed | url=%s | %s", url[:60], e)
        return "", []


def _crawl_page_content(url: str, query: str, include_images: bool = True) -> tuple[str, list[str]]:
    """Use Tavily Crawl on a single URL to get page content and image URLs. Returns (raw_content, image_urls)."""
    api_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not api_key:
        return "", []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        instructions = f"Extract the full product description and all product image URLs from this page. Query: {query[:150]}"
        response = client.crawl(
            url=url,
            instructions=instructions,
            extract_depth="advanced",
            limit=1,
            max_depth=1,
            include_images=include_images,
        )
        results = response.get("results") if isinstance(response, dict) else getattr(response, "results", [])
        log.info("Tavily crawl response: %s results", len(results) if results else 0)
        if not results:
            return "", []
        raw_parts = []
        images = []
        for r in results if isinstance(results, list) else [results]:
            raw_parts.append(r.get("raw_content", "") or "")
            raw_imgs = r.get("images")
            log.info("Tavily crawl result: raw_content len=%s, images type=%s len=%s", len(r.get("raw_content") or ""), type(raw_imgs).__name__, len(raw_imgs) if isinstance(raw_imgs, list) else 0)
            imgs = _normalize_image_list(r.get("images") if isinstance(r.get("images"), list) else [])
            images.extend(imgs)
        log.info("Tavily crawl: total normalized images=%s first=%s", len(images), (images[0][:80] if images else "none"))
        return "\n\n".join(p for p in raw_parts if p).strip(), images
    except Exception as e:
        log.warning("Tavily crawl failed | url=%s | %s", url[:60], e)
        return "", []


def _search_web(query: str, max_results: int = 8) -> tuple[list[dict[str, Any]], list[str]]:
    """Run Tavily search with images; return (results, image_urls).
    Each result has {title, url, content, images}. Top-level images are also returned."""
    api_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not api_key:
        log.warning("TAVILY_API_KEY not set; skipping web search")
        return [], []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query,
            max_results=max_results,
            search_depth="advanced",
            include_images=True,
            include_image_descriptions=True,
        )
        raw = response if isinstance(response, dict) else {}
        results = raw.get("results") or []
        # Top-level images list from search response
        top_images: list[str] = []
        raw_imgs = raw.get("images") or []
        for img in raw_imgs:
            if isinstance(img, str) and img.startswith("http"):
                top_images.append(img)
            elif isinstance(img, dict):
                u = (img.get("url") or "").strip()
                if u and u.startswith("http"):
                    top_images.append(u)

        log.info("Tavily search response: %s results, %s top-level images", len(results), len(top_images))
        for i, r in enumerate((results or [])[:5]):
            if isinstance(r, dict):
                log.info("Tavily search [%s] title=%s url=%s", i, (r.get("title") or "")[:60], (r.get("url") or "")[:70])
        if top_images:
            log.info("Tavily search images (%s total):", len(top_images))
            for i, u in enumerate(top_images):
                log.info("  [IMG%s] %s", i + 1, u)
        if not results:
            return [], top_images
        out = []
        for r in (results if isinstance(results, list) else []):
            entry = {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            # Some Tavily plans return per-result images too
            r_imgs = r.get("images") or []
            per_imgs = []
            for img in r_imgs:
                if isinstance(img, str) and img.startswith("http"):
                    per_imgs.append(img)
                elif isinstance(img, dict):
                    u = (img.get("url") or "").strip()
                    if u and u.startswith("http"):
                        per_imgs.append(u)
            entry["images"] = per_imgs
            out.append(entry)
        return out, top_images
    except Exception as e:
        log.warning("Tavily search failed | %s", e)
        return [], []


def _build_search_query(product: dict[str, Any]) -> str:
    """Build a search query from product so we find the correct product."""
    parts = []
    if product.get("brand_name"):
        parts.append(str(product["brand_name"]).strip())
    if product.get("name"):
        parts.append(str(product["name"]).strip())
    if product.get("sku"):
        parts.append(str(product["sku"]).strip())
    return " ".join(parts) if parts else "product"


def _call_llm_for_product(
    product: dict[str, Any],
    search_results: list[dict[str, Any]],
    search_images: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    Send product + search results (including images from Tavily) to OpenAI.
    LLM returns JSON with name, description, price, image_url, source_website in one step.
    image_url is picked directly from the search images — same flow as text details.
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        log.warning("OPENAI_API_KEY not set; cannot run AI product finder")
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
    except ImportError:
        log.warning("openai package not installed")
        return None

    sku = (product.get("sku") or product.get("sku_raw") or "").strip()
    name = (product.get("name") or "").strip()
    brand = (product.get("brand_name") or "").strip()

    search_blob = ""
    if search_results:
        for i, r in enumerate(search_results[:10], 1):
            imgs = r.get("images") or []
            img_note = f"\n   Images on this page: {', '.join(imgs[:3])}" if imgs else ""
            search_blob += f"\n[{i}] Title: {r.get('title', '')}\nURL: {r.get('url', '')}\nContent: {r.get('content', '')[:400]}{img_note}\n"
    else:
        search_blob = "\n(No web search results available; use product name/brand and return best-effort JSON.)"

    prompt = f"""You are a product data expert. We have a product from our Excel sheet.
Your task: find the CORRECT matching product on the web and return its data.

Product from our sheet:
- Brand: {brand}
- Name: {name}
- SKU: {sku}

Web search results:
{search_blob}

Instructions:
1. Match the EXACT product (same SKU/model). Do NOT pick a different variant.
2. PRIORITY for source_website:
   a. Official brand/manufacturer website (e.g. tuffyproducts.com for Tuffy Security) — FIRST choice.
   b. Dedicated retailer product page (e.g. trucksrus.shop, truckworksunlimited.com) — second choice.
   c. Amazon, eBay, Walmart — LAST RESORT only, avoid if any other option exists.
3. Return valid JSON only, no markdown, with these exact keys:
   name, description, price, image_url, source_website
   - image_url: leave as "" (image is handled separately)

Example: {{"name": "Product Name", "description": "Short description if available", "price": "29.99", "image_url": "", "source_website": "https://..."}}
"""

    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            response_format={"type": "json_object"},
        )
        text = (r.choices[0].message.content or "").strip()
        log.info("Tavily LLM (pick source+image) response length=%s preview=%s", len(text), text[:400] if text else "empty")
        data = json.loads(text)
        if isinstance(data, dict):
            out = {k: (data.get(k) or "") for k in RESULT_KEYS}
            log.info("LLM result: name=%s", (out.get("name") or "")[:60])
            log.info("LLM result: source_website=%s", out.get("source_website") or "")
            log.info("LLM result: image_url=%s", out.get("image_url") or "")
            return out
    except Exception as e:
        log.warning("OpenAI product finder failed | %s", e)
    return None


def _extract_full_description_and_image(
    product: dict[str, Any],
    page_content: str,
    image_urls: list[str],
    source_url: str,
) -> tuple[str, str]:
    """From extracted page content and image list (all from source_url only), get full description and main product image.
    Only uses content from this single source page; image must be from the provided list (same source website).
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not page_content and not image_urls:
        return "", ""
    # When no API key or LLM fails, still return first valid image so images appear
    if not api_key:
        if image_urls:
            first = next((u for u in image_urls if not _is_bad_image_url(u)), "")
            if first:
                return "", first.strip()
        return "", ""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
    except ImportError:
        return "", ""
    name = (product.get("name") or product.get("sku") or "").strip()
    content_preview = (page_content[:12000] + "...") if len(page_content) > 12000 else (page_content or "(no text content extracted)")
    # image_urls here are already filtered to same domain as source_url by caller
    images_blob = "\n".join(image_urls[:15]) if image_urls else "(no images extracted)"
    prompt = f"""You are extracting product data from a SINGLE web page. All content below is from this one page only.

Product: {name}
Source URL (the only page we use): {source_url}

PAGE CONTENT (all from the above URL — copy description only from here, do not add from elsewhere):
{content_preview}

IMAGE URLs (all from the same page above — you MUST choose the main product image ONLY from this list; do not use any URL not listed):
{images_blob}

Instructions (mandatory):
1. description: Copy the COMPLETE product description from the page content only. Do not summarize. Do not add text from other sources. If no useful content, return "".
2. image_url: Pick exactly ONE URL from the image list above that is the main product photo (not logo/icon). You must return one of the URLs listed; if none are product images return "".
3. Return valid JSON only, no markdown: {{"description": "...", "image_url": "..."}}
"""

    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        text = (r.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text).strip()
            text = re.sub(r"\n?```\s*$", "", text).strip()
        data = json.loads(text)
        if isinstance(data, dict):
            desc = (data.get("description") or "").strip()
            img = (data.get("image_url") or "").strip()
            if _is_bad_image_url(img):
                img = ""
            log.info("Tavily LLM (extract desc/image) response: description len=%s image_url=%s", len(desc), (img or "empty")[:80])
            # Ensure image is from source website only: must be in our list or same domain
            if img:
                allowed = {u.strip() for u in image_urls}
                if img not in allowed and _source_domain(img) != _source_domain(source_url):
                    log.info("Tavily: LLM returned image not from source page; using first from source list")
                    img = image_urls[0].strip() if image_urls else ""
            if not img and image_urls:
                img = next((u for u in image_urls if not _is_bad_image_url(u)), "")
                if img:
                    img = img.strip()
                    log.info("Using first valid image URL (LLM returned none or bad)")
            return desc, img
    except Exception as e:
        log.warning("OpenAI extract description/image failed | %s", e)
    if image_urls:
        return "", image_urls[0].strip()
    return "", ""


def _find_product_with_openai_web_search(product: dict[str, Any]) -> dict[str, Any]:
    """
    Use OpenAI Responses API with tools=[{"type": "web_search"}] to find the product
    and return name, description, price, image_url, source_website. Single call; no Tavily.
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        log.warning("OPENAI_API_KEY not set; cannot use OpenAI web search")
        return {k: "" for k in RESULT_KEYS}
    sku = (product.get("sku") or product.get("sku_raw") or "").strip()
    name = (product.get("name") or "").strip()
    brand = (product.get("brand_name") or "").strip()
    query = _build_search_query(product)
    prompt = f"""You are a product data expert. Use web search to find the CORRECT product page for this exact item (same SKU/model). Prefer the official brand site or a main retailer page that has full product details.

Product from our sheet: Brand={brand}, Name={name}, SKU={sku}

Rules (mandatory):
1. Pick ONE product page that has full details (description, price, main product image). Prefer: official brand website > major retailer (e.g. Amazon) > other stores. The page must be for this exact product/SKU.
2. source_website = the URL of that product PAGE (the page you chose), e.g. https://tuffyproducts.com/products/395-01
3. All data (name, description, price, image_url) must come FROM THAT SAME PAGE. Do not mix: do not use an image URL from a different site. image_url must be the main product image URL as shown ON that same product page (same domain as source_website).
4. image_url = direct URL of the main product photo (not logo/favicon). It should be from the same site as source_website.

Return valid JSON only, no markdown, with exactly these keys: name, description, price, image_url, source_website.
Example: {{"name": "...", "description": "...", "price": "29.99", "image_url": "https://same-site.com/.../image.jpg", "source_website": "https://same-site.com/product-page"}}
"""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.responses.create(
            model="gpt-4o",
            input=prompt,
            tools=[{"type": "web_search"}],
            max_output_tokens=2000,
        )
        text = (getattr(response, "output_text", None) or "").strip()
        log.info("OpenAI web_search response: output_text length=%s preview=%s", len(text), (text[:500] if text else "empty"))
        if not text and getattr(response, "output", None):
            for out in response.output:
                if getattr(out, "type", None) == "message" and getattr(out, "content", None):
                    for block in out.content:
                        if getattr(block, "type", None) == "output_text" and getattr(block, "text", None):
                            text = (text + block.text).strip()
        if not text:
            log.warning("OpenAI web search returned no output_text")
            return {k: "" for k in RESULT_KEYS}
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text).strip()
            text = re.sub(r"\n?```\s*$", "", text).strip()
        data = json.loads(text)
        if isinstance(data, dict):
            result = {k: (data.get(k) or "").strip() for k in RESULT_KEYS}
            source_url = result.get("source_website") or ""
            image_url = result.get("image_url") or ""
            if image_url and source_url:
                try:
                    from urllib.parse import urlparse
                    src_domain = (urlparse(source_url).netloc or "").lower().replace("www.", "")
                    img_domain = (urlparse(image_url).netloc or "").lower().replace("www.", "")
                    if src_domain and img_domain and src_domain != img_domain:
                        log.warning("OpenAI: image_url domain %s != source_website domain %s; clearing image", img_domain, src_domain)
                        result["image_url"] = ""
                except Exception:
                    pass
            if not (result.get("image_url") or "").strip() and text:
                urls = _extract_image_urls_from_text(text, max_urls=5)
                if urls and source_url:
                    try:
                        from urllib.parse import urlparse
                        src_domain = (urlparse(source_url).netloc or "").lower().replace("www.", "")
                        for u in urls:
                            d = (urlparse(u).netloc or "").lower().replace("www.", "")
                            if d == src_domain:
                                result["image_url"] = u
                                log.info("OpenAI web search: used image URL from same domain as source")
                                break
                        if not (result.get("image_url") or "").strip() and urls:
                            result["image_url"] = urls[0]
                            log.info("OpenAI web search: used image URL from response text")
                    except Exception:
                        if urls:
                            result["image_url"] = urls[0]
                elif urls:
                    result["image_url"] = urls[0]
            if not (result.get("image_url") or "").strip() and source_url:
                fetched = _fetch_image_urls_from_page(source_url)
                log.info("OpenAI direct page fetch: got %s image URLs first=%s", len(fetched), (fetched[0][:80] if fetched else "none"))
                if fetched:
                    result["image_url"] = fetched[0]
                    log.info("OpenAI: used image from direct page fetch")
            log.info("OpenAI final result: name=%s source_website=%s image_url=%s", (result.get("name") or "")[:50], (result.get("source_website") or "")[:60], (result.get("image_url") or "")[:80])
            return result
    except json.JSONDecodeError as e:
        log.warning("OpenAI web search: JSON parse failed | %s", e)
    except Exception as e:
        log.warning("OpenAI web search failed | %s", e)
    return {k: "" for k in RESULT_KEYS}


def find_product_with_ai(product: dict[str, Any], search_method: str = SEARCH_METHOD_TAVILY) -> dict[str, Any]:
    """
    For one product from Excel: get product data + source website.
    - search_method=tavily: Tavily search + extract (full description + image from page).
    - search_method=openai: OpenAI Responses API with web_search tool (single call).
    Returns dict with keys: name, description, price, image_url, source_website.
    """
    if (search_method or "").strip().lower() == SEARCH_METHOD_OPENAI:
        log.info("AI product finder | method=openai (Responses API + web_search)")
        return _find_product_with_openai_web_search(product)
    log.info("AI product finder | method=tavily")
    query = _build_search_query(product)
    log.info("AI product finder | query=%s", query[:80])
    search_results, search_images = _search_web(query)
    log.info("Web search returned %s results, %s images", len(search_results), len(search_images))

    # LLM picks: source_website AND image_url together from search results + images in ONE call
    result = _call_llm_for_product(product, search_results, search_images)

    # Fallback: if LLM failed (e.g. quota), use first non-blocked search result
    _BLOCKED_DOMAINS = ("amazon.com", "ebay.com", "walmart.com", "facebook.com")

    def _is_blocked(url: str) -> bool:
        return any(b in _source_domain(url) for b in _BLOCKED_DOMAINS)

    if not result and search_results:
        fallback_url = next(
            (r.get("url", "") for r in search_results if not _is_blocked(r.get("url", ""))),
            (search_results[0].get("url", "") if search_results else ""),
        )
        if fallback_url and fallback_url.startswith("http"):
            log.info("LLM failed; using fallback source | url=%s", fallback_url[:60])
            result = {k: "" for k in RESULT_KEYS}
            result["name"] = (product.get("name") or product.get("sku") or "").strip()
            result["source_website"] = fallback_url

    if not result:
        return {k: "" for k in RESULT_KEYS}

    source_url = (result.get("source_website") or "").strip()
    sku = (product.get("sku") or product.get("sku_raw") or "").strip()

    log.info("LLM chose source_website=%s", source_url if source_url else "(none)")

    # === Images: keep all valid Tavily search images (up to 5); first one is the main/thumbnail ===
    valid_search_images = [u for u in search_images if not _is_bad_image_url(u)]
    main_image = valid_search_images[0] if valid_search_images else ""
    if valid_search_images:
        log.info("Images from Tavily search (%s valid):", len(valid_search_images))
        for i, u in enumerate(valid_search_images):
            log.info("  [IMG%s] %s", i + 1, u)
    else:
        log.warning("No valid images in Tavily search results")

    # === Get full description via Tavily extract ===
    if source_url and source_url.startswith("http"):
        page_content, _ = _extract_page_content(source_url, query)
        if not page_content:
            crawl_content, _ = _crawl_page_content(source_url, query)
            page_content = crawl_content
        if page_content:
            full_desc, _ = _extract_full_description_and_image(
                product, page_content, ([main_image] if main_image else []), source_url
            )
            if full_desc:
                result["description"] = full_desc
                log.info("Description extracted | len=%s", len(full_desc))

    if main_image and not _is_bad_image_url(main_image):
        result["image_url"] = main_image
        result["_image_urls"] = valid_search_images  # all 5 kept for Excel + BC
        log.info("Final product image (main) | %s", main_image)
        log.info("All product images (%s) | %s", len(valid_search_images), valid_search_images)
    else:
        result["image_url"] = ""
        result["_image_urls"] = []
        log.warning("No product image found | source=%s", source_url[:60] if source_url else "(none)")

    return result
