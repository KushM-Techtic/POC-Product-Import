"""
Matching + enrichment: match rows to scraped products by SKU/name; optional LLM; fill description, attach images.
"""
import os
import re
from pathlib import Path
from typing import Any

from app.logger import get_logger

log = get_logger("app.services.matcher")


def _fuzzy_match_with_llm(
    product: dict[str, Any],
    scraped_products: list[dict[str, Any]],
) -> int | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not scraped_products:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        options = "\n".join(f"{i}. {p.get('title', '')[:80]}" for i, p in enumerate(scraped_products[:30]))
        prompt = (
            f"Product: SKU={product.get('sku', '')} Name={product.get('name', '')}\n"
            f"Which scraped product (by index 0 to N-1) best matches? Reply with only the index number, or -1 if none.\n"
            f"Scraped products:\n{options}"
        )
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
        )
        text = (r.choices[0].message.content or "").strip()
        idx = int(re.sub(r"[^\d\-]", "", text) or "-1")
        if 0 <= idx < len(scraped_products):
            return idx
    except Exception:
        pass
    return None


def _normalize_for_match(s: str) -> str:
    if not s:
        return ""
    s = str(s).lower().strip()
    s = re.sub(r"[^\w\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _sku_in_text(sku: str, text: str) -> bool:
    if not sku:
        return False
    n = _normalize_for_match(sku)
    t = _normalize_for_match(text)
    n_compact = n.replace("-", "").replace(" ", "")
    t_compact = t.replace("-", "").replace(" ", "")
    return n in t or n_compact in t_compact or (len(n_compact) >= 4 and n_compact in t_compact)


def _words_overlap(name: str, title: str, min_words: int = 2) -> bool:
    """True if at least min_words significant words from name appear in title."""
    if not name or not title:
        return False
    n = _normalize_for_match(name)
    t = _normalize_for_match(title)
    words = [w for w in n.split() if len(w) >= 2 and w not in ("the", "and", "for", "with")]
    if not words:
        return n in t
    found = sum(1 for w in words if w in t)
    return found >= min(min_words, len(words))


def match_product_to_scraped(
    product: dict[str, Any],
    scraped_products: list[dict[str, Any]],
    *,
    use_llm: bool = True,
    skip_indices: set[int] | None = None,
) -> tuple[dict[str, Any] | None, int]:
    """Return (matched_scraped_product, scraped_index) or (None, -1). skip_indices = scraped indices already used (1:1 matching)."""
    skip_indices = skip_indices or set()
    sku = product.get("sku", "") or ""
    sku_raw = product.get("sku_raw", "") or ""
    name = product.get("name", "") or ""
    for idx, sp in enumerate(scraped_products):
        if idx in skip_indices:
            continue
        stitle = sp.get("title", "") or ""
        surl = sp.get("url", "") or ""
        if _sku_in_text(sku, stitle) or _sku_in_text(sku, surl):
            return sp, idx
        if _sku_in_text(sku_raw, stitle) or _sku_in_text(sku_raw, surl):
            return sp, idx
        if name and _normalize_for_match(name) in _normalize_for_match(stitle):
            return sp, idx
        if stitle and _normalize_for_match(stitle) in _normalize_for_match(name):
            return sp, idx
        if name and stitle and _words_overlap(name, stitle, 2):
            return sp, idx
    if use_llm and scraped_products:
        available = [(i, sp) for i, sp in enumerate(scraped_products) if i not in skip_indices]
        if available:
            idx = _fuzzy_match_with_llm(product, [sp for _, sp in available])
            if idx is not None and 0 <= idx < len(available):
                return available[idx][1], available[idx][0]
    return None, -1


def enrich_products(
    products: list[dict[str, Any]],
    scraped_products: list[dict[str, Any]],
    output_images_dir: Path,
    *,
    use_llm: bool = True,
    stop_after_first_match: bool = False,
) -> list[dict[str, Any]]:
    log.info("Matcher: enrich_products started | excel_rows=%s | scraped_products=%s | use_llm=%s | stop_after_first_match=%s", len(products), len(scraped_products), use_llm, stop_after_first_match)
    used_scraped: set[int] = set()  # 1:1 matching: each scraped product used at most once
    for prod in products:
        matched, scraped_idx = match_product_to_scraped(prod, scraped_products, use_llm=use_llm, skip_indices=used_scraped)
        if not matched:
            prod.setdefault("_matched", False)
            prod.setdefault("_image_paths", [])
            continue
        used_scraped.add(scraped_idx)
        prod["_matched"] = True
        if not (prod.get("description") or "").strip():
            prod["description"] = (matched.get("description") or "").strip()
        if not prod.get("_image_paths"):
            paths = matched.get("image_paths", [])
            prod["_image_paths"] = [str(p) for p in paths]
        if not prod.get("_image_urls") and matched.get("image_urls"):
            prod["_image_urls"] = list(matched.get("image_urls", []))
        if stop_after_first_match:
            log.info("Matcher: test_mode — stopping after first matched product")
            break
    matched_count = sum(1 for p in products if p.get("_matched"))
    log.info("Matcher: enrich_products completed | matched=%s/%s (1:1, scraped_used=%s)", matched_count, len(products), len(used_scraped))
    return products
