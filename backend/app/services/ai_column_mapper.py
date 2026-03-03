"""
Use AI to map source Excel column names to our canonical columns.
"""
import json
import logging
import os
import re

from app.core.canonical_schema import CANONICAL_COLUMNS, OPTIONAL_CANONICAL

log = logging.getLogger("app.services.ai_column_mapper")


def map_columns_with_ai(source_column_names: list[str]) -> dict[str, str]:
    """
    Given list of source Excel column names, return mapping:
      canonical_column -> source_column_name
    Uses OpenAI if OPENAI_API_KEY is set; otherwise falls back to simple keyword match.
    """
    source_cols = [c for c in source_column_names if c and str(c).strip()]
    if not source_cols:
        return {}

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        log.info("Column mapping: OPENAI_API_KEY not set, using keyword fallback")
        return _map_with_keywords(source_cols)
    mapping = _map_with_openai(source_cols)
    if mapping:
        log.info("Column mapping: OpenAI succeeded | mapping=%s", mapping)
        return mapping
    log.warning("Column mapping: OpenAI failed or returned no mapping, using keyword fallback")
    return _map_with_keywords(source_cols)


def _map_with_openai(source_cols: list[str]) -> dict[str, str] | None:
    try:
        import openai
    except ImportError:
        log.warning("Column mapping: openai package not installed")
        return None
    try:
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        log.info("Column mapping: calling OpenAI API (chat.completions.create)...")
        canonical_list = ", ".join(CANONICAL_COLUMNS + OPTIONAL_CANONICAL)
        source_list = "\n".join(f"- {c!r}" for c in source_cols[:80])
        prompt = f"""You are mapping Excel column headers to a fixed schema for e-commerce import.

Canonical columns (we need these in the output): {canonical_list}

Source column names from the user's Excel file:
{source_list}

For each canonical column, choose the ONE source column that best fits (or leave unmapped if none fit).
Reply with a JSON object only, no markdown. Keys are canonical names, values are exact source column names.
Example: {{"SKU": "Product SKU", "Name": "Item Name", "Description": "Long Description", "Brand Name": "Brand", "UPC": "GTIN", "Price": "Retail Price"}}
Unmapped canonical columns should be omitted from the JSON."""

        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        text = (r.choices[0].message.content or "").strip()
        text = re.sub(r"^```\w*\n?", "", text).replace("```", "").strip()
        mapping = json.loads(text)
        if isinstance(mapping, dict):
            out = {k: v for k, v in mapping.items() if k in CANONICAL_COLUMNS + OPTIONAL_CANONICAL and v in source_cols}
            if out:
                return out
    except Exception as e:
        log.warning("Column mapping: OpenAI request failed | %s", e)
    return None


_KEYWORDS: dict[str, list[str]] = {
    "SKU": ["sku", "product sku", "item sku", "part number", "part no", "part #", "item number", "product code"],
    "Name": ["name", "title", "product name", "item name", "product title", "description short"],
    "Description": ["description", "long description", "product description", "desc", "details", "full description", "marketing description", "desc_mkt", "desc_ext"],
    "Brand Name": ["brand", "brand name", "manufacturer", "vendor"],
    "UPC": ["upc", "gtin", "ean", "barcode", "item level gtin", "upc-12"],
    "Price": ["price", "retail price", "list price", "msrp", "sale price", "jobber price", "retail map price"],
    "MPN": ["mpn", "manufacturer part", "mfr part", "part number"],
    "Weight": ["weight"],
    "Height": ["height"],
    "Width": ["width"],
    "Length": ["length"],
    "Color": ["color", "colour", "body color", "armrest color"],
    "Product URL": ["product url", "url", "link", "product link", "page url", "product page", "website"],
}


def _normalize(s: str) -> str:
    return " ".join(str(s).lower().split())


def _map_with_keywords(source_cols: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    norm_src = {_normalize(c): c for c in source_cols}

    for canonical, keywords in _KEYWORDS.items():
        if canonical not in CANONICAL_COLUMNS + OPTIONAL_CANONICAL:
            continue
        if canonical in mapping:
            continue
        if canonical == "Name":
            for prefer in ["title", "product name", "item name", "name"]:
                for src_norm, src_orig in norm_src.items():
                    if src_orig in used:
                        continue
                    if "brand" in src_norm and "name" in src_norm:
                        continue
                    if prefer in src_norm or src_norm == prefer:
                        mapping[canonical] = src_orig
                        used.add(src_orig)
                        break
                if canonical in mapping:
                    break
            continue
        if canonical == "Brand Name":
            for kw in ["brand", "brand name", "manufacturer", "vendor"]:
                for src_norm, src_orig in norm_src.items():
                    if src_orig in used:
                        continue
                    if kw in src_norm or src_norm in kw:
                        mapping[canonical] = src_orig
                        used.add(src_orig)
                        break
                if canonical in mapping:
                    break
            continue
        for src_norm, src_orig in norm_src.items():
            if src_orig in used:
                continue
            if src_norm in keywords:
                mapping[canonical] = src_orig
                used.add(src_orig)
                break
        if canonical in mapping:
            continue
        for kw in keywords:
            for src_norm, src_orig in norm_src.items():
                if src_orig in used:
                    continue
                if kw in src_norm or src_norm in kw:
                    mapping[canonical] = src_orig
                    used.add(src_orig)
                    break
            if canonical in mapping:
                break
    return mapping
