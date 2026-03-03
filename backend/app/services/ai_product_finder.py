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
    """Keep only image URLs that belong to the same domain as source_url. Ensures no mismatch with source website."""
    if not source_url or not image_urls:
        return list(image_urls)
    base_domain = _source_domain(source_url)
    if not base_domain:
        return list(image_urls)
    out = []
    for u in image_urls:
        if not u or not (u := u.strip()).startswith("http"):
            continue
        d = _source_domain(u)
        if d == base_domain or d.endswith("." + base_domain):
            out.append(u)
    # Return only same-domain images; if none, return [] so we never use an image from another site
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


def _fetch_image_urls_from_page(page_url: str, timeout: int = 12) -> list[str]:
    """Fetch product page HTML and extract image URLs from img src/data-src. Fallback when Tavily returns no images."""
    if not page_url or not page_url.startswith("http"):
        return []
    try:
        req = Request(page_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0"})
        with urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("Fetch page for images failed | url=%s | %s", page_url[:50], e)
        return []
    base = page_url.rsplit("/", 1)[0] + "/"
    base_scheme = urlparse(page_url)
    base_full = f"{base_scheme.scheme}://{base_scheme.netloc}"
    urls = []
    for attr in ("data-src", "data-lazy-src", "src"):
        pat = re.compile(rf'<img[^>]+{re.escape(attr)}=["\']([^"\']+)["\']', re.IGNORECASE)
        for m in pat.finditer(html):
            u = m.group(1).strip()
            if not u or "data:" in u or "placeholder" in u.lower() or "logo" in u.lower() or "favicon" in u.lower():
                continue
            if u.startswith("//"):
                u = "https:" + u
            elif u.startswith("/"):
                u = urljoin(base_full, u)
            elif not u.startswith("http"):
                u = urljoin(base, u)
            if u.startswith("http") and u not in urls:
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


def _search_web(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    """Run Tavily search; return list of {title, url, content}."""
    api_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not api_key:
        log.warning("TAVILY_API_KEY not set; skipping web search")
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=max_results, search_depth="advanced")
        # Response has .get("results", []) with title, url, content
        results = response.get("results") if isinstance(response, dict) else getattr(response, "results", [])
        log.info("Tavily search response: %s results", len(results) if results else 0)
        for i, r in enumerate((results or [])[:5]):
            if isinstance(r, dict):
                log.info("Tavily search [%s] title=%s url=%s", i, (r.get("title") or "")[:60], (r.get("url") or "")[:70])
        if not results:
            return []
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in (results if isinstance(results, list) else [])
        ]
    except Exception as e:
        log.warning("Tavily search failed | %s", e)
        return []


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
) -> dict[str, Any] | None:
    """
    Send product + search results to OpenAI. Strict instructions: match the CORRECT product
    (same SKU/model), pick ONE best source, return JSON with name, description, price, image_url, source_website.
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
            search_blob += f"\n[{i}] Title: {r.get('title', '')}\nURL: {r.get('url', '')}\nContent: {r.get('content', '')[:500]}\n"
    else:
        search_blob = "\n(No web search results available; use product name/brand and return best-effort JSON.)"

    prompt = f"""You are a product data expert. We have a product from our Excel sheet. Your task is to find the CORRECT matching product on the web (same product/SKU/model, not a different variant).

Product from our sheet:
- Brand: {brand}
- Name: {name}
- SKU: {sku}

Web search results:
{search_blob}

Instructions (mandatory):
1. Match the EXACT product or the same model/SKU. Do not pick a different product or variant.
2. Pick ONE best source (e.g. Amazon, Flipkart, official brand site) where this product is listed.
3. Extract from that source: product name, price (number or string), and the source page URL. Description and image_url will be filled later from the page; you may leave them empty or put a short snippet.
4. Return valid JSON only, no markdown, with these exact keys: name, description, price, image_url, source_website.
   - source_website must be the full URL of the page you picked (e.g. https://www.amazon.com/...). This is required so we can fetch the full page content.
   - If you cannot find the correct product, return JSON with empty strings for missing fields but still set source_website to the best URL you found, or "" if none.

Example output: {{"name": "Product Name", "description": "", "price": "29.99", "image_url": "", "source_website": "https://..."}}
"""

    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
        text = (r.choices[0].message.content or "").strip()
        log.info("Tavily LLM (pick source) response length=%s preview=%s", len(text), text[:400] if text else "empty")
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text).strip()
            text = re.sub(r"\n?```\s*$", "", text).strip()
        data = json.loads(text)
        if isinstance(data, dict):
            out = {k: (data.get(k) or "") for k in RESULT_KEYS}
            log.info("Tavily LLM parsed result: name=%s source_website=%s image_url=%s", (out.get("name") or "")[:50], (out.get("source_website") or "")[:60], (out.get("image_url") or "")[:80])
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
    if not api_key or (not page_content and not image_urls):
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
    search_results = _search_web(query)
    log.info("Web search returned %s results", len(search_results))
    result = _call_llm_for_product(product, search_results)
    if not result:
        return {k: "" for k in RESULT_KEYS}
    source_url = (result.get("source_website") or "").strip()
    log.info("AI product finder | source_website=%s", source_url[:60] if source_url else "(none)")
    if source_url and source_url.startswith("http"):
        log.info("Extracting full page content and images from source URL (extract + crawl)")
        page_content, image_urls = _extract_page_content(source_url, query)
        crawl_content, crawl_images = _crawl_page_content(source_url, query)
        if crawl_content or crawl_images:
            log.info("Crawl got content len=%s, images=%s", len(crawl_content), len(crawl_images))
            page_content = (page_content + "\n\n" + crawl_content).strip() if page_content else crawl_content
            image_urls = list(dict.fromkeys(image_urls + crawl_images))
        if not image_urls and page_content:
            image_urls = _extract_image_urls_from_text(page_content, base_url=source_url)
            log.info("Extracted %s image URLs from page text", len(image_urls))
        # Keep only images from the source website so content and image never mismatch
        image_urls = _filter_images_same_domain(image_urls, source_url)
        # If we still have no same-domain images, try direct page fetch (same URL = same domain)
        if not image_urls:
            image_urls = _fetch_image_urls_from_page(source_url)
            log.info("Tavily: no same-domain images yet; direct page fetch | count=%s", len(image_urls))
        # Drop placeholder/captcha URLs so we never use them as main image
        image_urls = [u for u in image_urls if not _is_bad_image_url(u)]
        log.info("Tavily: using same-domain images only | count=%s", len(image_urls))
        log.info("Combined content len=%s, images=%s first_image=%s", len(page_content), len(image_urls), (image_urls[0][:80] if image_urls else "none"))
        if page_content or image_urls:
            full_desc, main_image = _extract_full_description_and_image(
                product, page_content, image_urls, source_url
            )
            if full_desc:
                result["description"] = full_desc
                log.info("Using full description | len=%s", len(full_desc))
            if main_image and not _is_bad_image_url(main_image):
                result["image_url"] = main_image
                # Return full candidate list (main first) so BC can try next if first fails
                rest = [u for u in image_urls if u != main_image and not _is_bad_image_url(u)]
                result["_image_urls"] = [main_image] + rest
                log.info("Using main product image | %s (total candidates=%s)", main_image[:60], len(result["_image_urls"]))
    return result
