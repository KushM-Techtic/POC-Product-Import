"""Pipeline: load Excel → AI map columns → parse → AI find product (web search) for first N products → export."""
import tempfile
from pathlib import Path
from typing import Any

from app.logger import get_logger
from app.services.ai_column_mapper import map_columns_with_ai
from app.services.ai_product_finder import find_product_with_ai
from app.services.export import build_bc_dataframe
from app.services.input_parser import load_excel, parse_excel_with_mapping

log = get_logger("app.services.pipeline")

# Number of products to enrich via AI (web search + LLM). Rest keep Excel data only.
AI_PRODUCT_LIMIT = 5


def run_pipeline(
    input_path: Path,
    *,
    output_dir: Path | None = None,
    max_products_to_enrich: int = AI_PRODUCT_LIMIT,
    search_method: str = "tavily",
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """
    Load Excel, map columns with AI, parse, then for first max_products_to_enrich products
    run AI product finder. search_method: "tavily" (Tavily + extract) or "openai" (Responses API + web_search).
    Returns all products; first N have AI-filled data + source_website.
    """
    log.info("========== Pipeline started (AI-only, no scrape) ==========")

    log.info("Phase 1/4: load_excel | path=%s", input_path)
    try:
        df = load_excel(input_path)
    except Exception as e:
        log.exception("Phase 1 failed: load_excel | %s", e)
        raise
    log.info("Phase 1 completed | rows=%s | columns=%s", len(df), list(df.columns)[:8])

    log.info("Phase 2/4: column_mapping (AI) started")
    column_mapping = map_columns_with_ai([str(c) for c in df.columns])
    log.info("Phase 2 completed | mapping=%s", column_mapping)

    log.info("Phase 3/4: parse_excel_with_mapping started")
    products = parse_excel_with_mapping(input_path, column_mapping)
    log.info("Phase 3 completed | products=%s", len(products))

    limit = min(max_products_to_enrich, len(products))
    log.info("Phase 4/4: AI product finder (search_method=%s) for first %s products", search_method, limit)
    for i, prod in enumerate(products):
        if i >= limit:
            break
        log.info("AI product finder | product %s/%s | sku=%s | name=%s", i + 1, limit, prod.get("sku"), (prod.get("name") or "")[:50])
        result = find_product_with_ai(prod, search_method=search_method)
        prod["_search_method"] = (search_method or "tavily").strip().lower()
        if result.get("name"):
            prod["name"] = result["name"]
        if result.get("description"):
            prod["description"] = result["description"]
        if result.get("price"):
            prod["price"] = result["price"]
        source_website = (result.get("source_website") or "").strip()
        prod["source_website"] = source_website
        # image_url = first/main image; _image_urls = all valid Tavily images (up to 5)
        canonical_image = (result.get("image_url") or "").strip()
        all_images = result.get("_image_urls") or ([canonical_image] if canonical_image else [])
        prod["image_url"] = canonical_image
        prod["_image_urls"] = all_images

    log.info("Phase 4 completed | enriched %s products with AI", limit)
    log.info("========== Pipeline finished ==========")
    return products, column_mapping


def build_export_dataframe(enriched_products: list[dict[str, Any]], images_base_path: Path | None = None):
    return build_bc_dataframe(enriched_products, images_base_path=images_base_path)
