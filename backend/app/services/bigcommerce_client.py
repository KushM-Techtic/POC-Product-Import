"""BigCommerce client: create/update products directly via API.

Uses v3 Catalog API:
- Create/Update:   POST/PUT /stores/{store_hash}/v3/catalog/products
- Images (from URL): POST /stores/{store_hash}/v3/catalog/products/{product_id}/images
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

import requests

from app.config import get_settings
from app.logger import get_logger

log = get_logger("app.services.bigcommerce_client")

# Sanitize strings so JSON and BigCommerce API accept them (no control chars, null bytes, etc.)
_CONTROL_OR_NULL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_string(s: Any, max_len: int = 0) -> str:
    if s is None:
        return ""
    out = str(s).strip()
    out = _CONTROL_OR_NULL.sub(" ", out)
    out = out.encode("utf-8", errors="replace").decode("utf-8")
    if max_len and len(out) > max_len:
        out = out[:max_len]
    return out


class BigCommerceConfig:
    def __init__(self) -> None:
        s = get_settings()
        self.store_hash: str = s.bc_store_hash
        self.access_token: str = s.bc_access_token
        self.api_base_url: str = s.bc_api_base_url or "https://api.bigcommerce.com"

    @property
    def is_configured(self) -> bool:
        return bool(self.store_hash and self.access_token)

    @property
    def base(self) -> str:
        # e.g. https://api.bigcommerce.com/stores/{hash}
        return f"{self.api_base_url.rstrip('/')}/stores/{self.store_hash}"


def _headers(cfg: BigCommerceConfig) -> Dict[str, str]:
    return {
        "X-Auth-Token": cfg.access_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _safe_get_raw(raw_row: Any, key: str, default: Any = "") -> Any:
    """Get value from raw_row (dict or pandas Series) for alignment with export."""
    if raw_row is None:
        return default
    try:
        v = raw_row.get(key, default)
        if v is None or (hasattr(v, "__float__") and str(v) == "nan"):
            return default
        return v
    except Exception:
        return default


def _is_valid_image_url(url: str, timeout: int = 8) -> bool:
    """Check that URL is reachable and returns an image so BigCommerce accepts it."""
    if not url or not url.startswith("http"):
        return False
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return False
        ct = (resp.headers.get("Content-Type") or "").lower()
        return "image/" in ct
    except Exception:
        return False


def _find_product_by_sku(cfg: BigCommerceConfig, sku: str) -> Dict[str, Any] | None:
    if not sku:
        return None
    url = f"{cfg.base}/v3/catalog/products"
    params = {"sku": sku}
    try:
        resp = requests.get(url, headers=_headers(cfg), params=params, timeout=15)
        if resp.status_code != 200:
            log.warning("BigCommerce: GET products by sku failed | sku=%s | status=%s | body=%s", sku, resp.status_code, resp.text[:300])
            return None
        data = resp.json()
        items = data.get("data") or []
        return items[0] if items else None
    except Exception as e:
        log.warning("BigCommerce: GET products by sku error | sku=%s | %s", sku, e)
        return None


def _create_or_update_product(cfg: BigCommerceConfig, prod: Dict[str, Any]) -> Tuple[int | None, str | None]:
    """Create or update a product based on SKU. Returns (product_id, error)."""
    sku = _sanitize_string(prod.get("sku") or prod.get("sku_raw") or "")
    name = _sanitize_string(prod.get("name") or sku or "Product", max_len=250)
    description = _sanitize_string(prod.get("description") or "", max_len=65535)

    # Same source as export: prod price, then raw_row Retail Price / List Price
    raw_row = prod.get("raw_row")
    price_raw = prod.get("price") or _safe_get_raw(raw_row, "Retail Price") or _safe_get_raw(raw_row, "List Price") or 0
    # Normalize price: strip $ and commas so "$249.00" and "1,299.99" parse correctly (Excel shows same value)
    price_str = re.sub(r"[\$\s,]", "", str(price_raw).strip()) or "0"
    try:
        price = float(price_str)
    except ValueError:
        price = 0.0
    if price != price or price < 0:  # NaN check
        price = 0.0

    weight_raw = prod.get("weight")
    try:
        weight = float(weight_raw)
    except (TypeError, ValueError):
        try:
            weight = float(str(weight_raw or "0").strip() or "0")
        except (TypeError, ValueError):
            weight = 0.0
    if weight != weight or weight < 0:
        weight = 0.0

    payload: Dict[str, Any] = {
        "name": name,
        "price": price,
        "type": "physical",
        "weight": weight,
        "description": description or "No description",
        "is_visible": True,
    }
    if sku:
        payload["sku"] = sku

    existing = _find_product_by_sku(cfg, sku) if sku else None
    try:
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as e:
        log.warning("BigCommerce: payload JSON encode failed | sku=%s | %s", sku, e)
        return None, str(e)

    try:
        if existing:
            product_id = existing.get("id")
            url = f"{cfg.base}/v3/catalog/products/{product_id}"
            log.info("BigCommerce: updating product | sku=%s | id=%s", sku, product_id)
            resp = requests.put(url, headers=_headers(cfg), data=body_bytes, timeout=20)
        else:
            url = f"{cfg.base}/v3/catalog/products"
            log.info("BigCommerce: creating product | sku=%s", sku)
            resp = requests.post(url, headers=_headers(cfg), data=body_bytes, timeout=20)
        if resp.status_code not in (200, 201):
            log.warning("BigCommerce: upsert failed | sku=%s | status=%s | body=%s", sku, resp.status_code, resp.text[:500])
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        data = body.get("data") or body
        product_id = data.get("id")
        return int(product_id) if product_id is not None else None, None
    except Exception as e:
        log.warning("BigCommerce: upsert error | sku=%s | %s", sku, e)
        return None, str(e)


def _set_main_image_from_url(cfg: BigCommerceConfig, product_id: int, image_url: str) -> str | None:
    if not image_url or not product_id:
        return None
    url = f"{cfg.base}/v3/catalog/products/{product_id}/images"
    payload = {"image_url": image_url, "is_thumbnail": True}
    try:
        log.info("BigCommerce: setting main image | product_id=%s | url=%s", product_id, image_url[:120])
        resp = requests.post(url, headers=_headers(cfg), data=json.dumps(payload), timeout=20)
        if resp.status_code not in (200, 201):
            log.warning("BigCommerce: set image failed | product_id=%s | status=%s | body=%s", product_id, resp.status_code, resp.text[:300])
            return f"HTTP {resp.status_code}: {resp.text[:200]}"
        return None
    except Exception as e:
        log.warning("BigCommerce: set image error | product_id=%s | %s", product_id, e)
        return str(e)


def import_products_to_bigcommerce(products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Import (create or update) products into BigCommerce. Returns summary."""
    cfg = BigCommerceConfig()
    if not cfg.is_configured:
        log.warning("BigCommerce import requested but credentials are not configured")
        raise RuntimeError("BigCommerce credentials are not configured. Set BIGCOMMERCE_STORE_HASH and BIGCOMMERCE_ACCESS_TOKEN.")

    total = 0
    created_or_updated = 0
    image_set = 0
    errors: List[Dict[str, Any]] = []

    for p in products:
        total += 1
        sku = str((p.get("sku") or p.get("sku_raw") or "").strip())
        product_id, err = _create_or_update_product(cfg, p)
        if err or not product_id:
            errors.append({"sku": sku, "step": "product", "error": err or "no product id"})
            continue
        created_or_updated += 1

        # Upload all images (up to 5); first one is the thumbnail
        all_image_urls = p.get("_image_urls") or []
        canonical_url = (p.get("image_url") or "").strip()
        if canonical_url and canonical_url not in all_image_urls:
            all_image_urls = [canonical_url] + all_image_urls
        any_image_set = False
        for img_idx, img_url in enumerate(all_image_urls[:5]):
            img_url = (img_url or "").strip()
            if not img_url:
                continue
            if not _is_valid_image_url(img_url):
                log.debug("BigCommerce: skip image (invalid URL) | sku=%s | url=%s", sku, img_url[:60])
                continue
            is_thumb = (img_idx == 0)
            url = f"{cfg.base}/v3/catalog/products/{product_id}/images"
            payload = {"image_url": img_url, "is_thumbnail": is_thumb, "sort_order": img_idx}
            try:
                log.info("BigCommerce: adding image %s/%s | thumbnail=%s | sku=%s | url=%s",
                         img_idx + 1, len(all_image_urls[:5]), is_thumb, sku, img_url[:120])
                resp = requests.post(url, headers=_headers(cfg), data=json.dumps(payload), timeout=20)
                if resp.status_code in (200, 201):
                    if is_thumb:
                        image_set += 1
                    any_image_set = True
                else:
                    log.warning("BigCommerce: add image failed | sku=%s | img=%s | status=%s | body=%s",
                                sku, img_idx + 1, resp.status_code, resp.text[:200])
            except Exception as e:
                log.warning("BigCommerce: add image error | sku=%s | img=%s | %s", sku, img_idx + 1, e)
        if not any_image_set and all_image_urls:
            log.warning("BigCommerce: no images uploaded for sku=%s", sku)

    summary = {
        "total_products": total,
        "products_imported": created_or_updated,
        "images_set": image_set,
        "errors": errors,
    }
    log.info("BigCommerce import summary: %s", summary)
    return summary

