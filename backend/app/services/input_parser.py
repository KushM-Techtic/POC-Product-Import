"""Input: read Excel and parse with AI-derived column mapping."""
from pathlib import Path
from typing import Any

import pandas as pd


KEY_FIELDS = {"SKU", "Title", "Description", "MPN", "Item Level GTIN", "Brand Name"}
DESCRIPTION_FIELDS = ["Description", "DESC_MKT", "DESC_EXT", "Product Information", "DESC_DES"]


def _str_val(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _normalize_sku(sku: Any) -> str:
    if pd.isna(sku):
        return ""
    s = str(sku).strip()
    if "|" in s:
        s = s.split("|")[-1]
    return s


def _get_description(row: pd.Series) -> str:
    for col in DESCRIPTION_FIELDS:
        if col in row.index and pd.notna(row.get(col)) and str(row[col]).strip():
            return str(row[col]).strip()
    return ""


def load_excel(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() not in (".xlsx", ".xls"):
        raise ValueError(f"Expected Excel file, got {path.suffix}")
    return pd.read_excel(path, sheet_name=0, header=0)


def row_to_product(row: pd.Series, index: int) -> dict[str, Any]:
    sku_raw = row.get("SKU", "")
    sku = _normalize_sku(sku_raw)
    title = row.get("Title", "")
    if pd.isna(title):
        title = ""
    else:
        title = str(title).strip()
    description = _get_description(row)
    mpn = row.get("MPN", "")
    if pd.isna(mpn):
        mpn = ""
    else:
        mpn = str(mpn).strip()
    upc = row.get("Item Level GTIN", "")
    if pd.isna(upc):
        upc = ""
    else:
        upc = str(upc).strip()
    brand = row.get("Brand Name", "")
    if pd.isna(brand):
        brand = ""
    else:
        brand = str(brand).strip()

    missing = []
    if not sku:
        missing.append("SKU")
    if not title:
        missing.append("Title")
    if not description:
        missing.append("Description")
    if not brand:
        missing.append("Brand Name")

    return {
        "row_index": index,
        "sku_raw": sku_raw,
        "sku": sku,
        "name": title,
        "description": description,
        "brand_name": brand,
        "mpn": mpn,
        "upc": upc,
        "weight": row.get("Weight"),
        "height": row.get("Height"),
        "width": row.get("Width"),
        "length": row.get("Length"),
        "color": row.get("Color"),
        "missing_fields": missing,
        "raw_row": row,
    }


def parse_dci_file(path: str | Path) -> list[dict[str, Any]]:
    df = load_excel(path)
    products = []
    for i, row in df.iterrows():
        products.append(row_to_product(row, int(i)))
    return products


def _get_mapped(row: pd.Series, mapping: dict[str, str], canonical: str) -> str:
    source_col = mapping.get(canonical)
    if not source_col or source_col not in row.index:
        return ""
    return _str_val(row.get(source_col))


def row_to_product_with_mapping(row: pd.Series, mapping: dict[str, str], index: int) -> dict[str, Any]:
    sku_raw = _get_mapped(row, mapping, "SKU")
    sku = _normalize_sku(sku_raw)
    name = _get_mapped(row, mapping, "Name")
    description = _get_mapped(row, mapping, "Description")
    if not description and "Description" not in mapping:
        for col in row.index:
            if col and ("desc" in str(col).lower() or "description" in str(col).lower()):
                description = _str_val(row.get(col))
                if description:
                    break
    brand_name = _get_mapped(row, mapping, "Brand Name")
    upc = _get_mapped(row, mapping, "UPC")
    price = _get_mapped(row, mapping, "Price")
    if not price:
        price = row.get("Retail Price") or row.get("List Price") or row.get("Jobber Price")
        price = _str_val(price)
    mpn = _get_mapped(row, mapping, "MPN")
    product_url = _get_mapped(row, mapping, "Product URL")

    missing = []
    if not sku:
        missing.append("SKU")
    if not name:
        missing.append("Name")
    if not description:
        missing.append("Description")
    if not brand_name:
        missing.append("Brand Name")

    return {
        "row_index": index,
        "sku_raw": sku_raw or sku,
        "sku": sku,
        "name": name,
        "description": description,
        "brand_name": brand_name,
        "upc": upc,
        "price": price,
        "mpn": mpn,
        "weight": row.get(mapping.get("Weight")) if mapping.get("Weight") in row.index else row.get("Weight"),
        "height": row.get(mapping.get("Height")) if mapping.get("Height") in row.index else row.get("Height"),
        "width": row.get(mapping.get("Width")) if mapping.get("Width") in row.index else row.get("Width"),
        "length": row.get(mapping.get("Length")) if mapping.get("Length") in row.index else row.get("Length"),
        "color": _get_mapped(row, mapping, "Color") or (row.get("Color") if "Color" in row.index else None),
        "product_url": product_url or "",
        "missing_fields": missing,
        "raw_row": row,
    }


def parse_excel_with_mapping(path: str | Path, column_mapping: dict[str, str]) -> list[dict[str, Any]]:
    df = load_excel(path)
    products = []
    for i, row in df.iterrows():
        products.append(row_to_product_with_mapping(row, column_mapping, int(i)))
    return products
