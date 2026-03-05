"""Upload Excel → AI column mapping → AI product find (web search) for first N products → BigCommerce Excel download."""
import math
import tempfile
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.logger import get_logger
from app.services.bigcommerce_client import import_products_to_bigcommerce
from app.services.export import build_bc_dataframe, dataframe_to_excel_bytes
from app.services.pipeline import run_pipeline

router = APIRouter(tags=["upload"])
log = get_logger("app.api.upload")


def _json_safe(value: Any) -> Any:
    """Convert value to JSON-serializable form; replace NaN/Inf floats."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "item"):  # numpy scalar
        try:
            x = value.item()
            return _json_safe(x)
        except Exception:
            return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(x) for x in value]
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    try:
        return str(value)
    except Exception:
        return None


def _serialize_product_for_json(prod: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a pipeline product to JSON-serializable dict (raw_row Series → dict, NaN/Inf → None)."""
    out: Dict[str, Any] = {}
    for k, v in prod.items():
        if k == "raw_row" and v is not None:
            try:
                raw = v.to_dict() if hasattr(v, "to_dict") else dict(v)
                out[k] = _json_safe(raw)
            except Exception:
                out[k] = {}
        else:
            out[k] = _json_safe(v)
    return out


class SearchMethod(str, Enum):
    """How to get product data from the web."""
    TAVILY = "tavily"
    OPENAI = "openai"

OUTPUT_DIR = Path(tempfile.gettempdir()) / "poc_exports"


def _cleanup_export_file(path: Path) -> None:
    try:
        if path and path.exists():
            path.unlink(missing_ok=True)
    except Exception as e:
        log.warning("Cleanup export file failed | path=%s | %s", path, e)


@router.post("/upload")
async def upload_and_export(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Product Excel (.xlsx or .xls)"),
    max_products: int = Form(5, description="Number of products (from top of sheet) to enrich via AI web search. Rest keep Excel data only."),
    search_method: SearchMethod = Form(SearchMethod.TAVILY, description="How to get product data: tavily = Tavily search + page extract. openai = OpenAI Responses API with web_search tool."),
    import_to_bigcommerce: bool = Form(False, description="If true, also import products directly into BigCommerce via API."),
    preview_only: bool = Form(False, description="If true, return enriched products as JSON for review in UI; no Excel download or BC import."),
):
    """Upload Excel. AI maps columns, then for first N products runs web search + AI.
    If preview_only=true, returns JSON for frontend table review. Otherwise returns BigCommerce Excel (and optionally BC import).
    """
    log.info(
        "Upload started | file=%s | max_products=%s | search_method=%s | import_to_bigcommerce=%s | preview_only=%s",
        file.filename or "(none)",
        max_products,
        search_method.value,
        import_to_bigcommerce,
        preview_only,
    )
    if not file.filename:
        log.warning("Upload failed: no filename")
        raise HTTPException(status_code=400, detail="No filename")
    ext = Path(file.filename).suffix.lower()
    if ext not in (".xlsx", ".xls"):
        log.warning("Upload failed: invalid extension %s", ext)
        raise HTTPException(status_code=400, detail="Only .xlsx or .xls allowed.")

    try:
        contents = await file.read()
    except Exception as e:
        log.warning("Upload failed: read error | %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    log.info("File received | size=%s bytes", len(contents))
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        limit = max(max_products, 1)
        log.info("Pipeline: run_pipeline started")
        enriched, column_mapping = run_pipeline(tmp_path, max_products_to_enrich=limit, search_method=search_method.value)
        log.info("Pipeline: run_pipeline completed | products=%s", len(enriched))
        export_products = enriched[:limit]

        if preview_only:
            serialized = [_serialize_product_for_json(p) for p in export_products]
            return JSONResponse(content={"products": serialized, "column_mapping": column_mapping})

        import_summary = None
        if import_to_bigcommerce:
            log.info("BigCommerce import requested | products=%s", len(export_products))
            try:
                import_summary = import_products_to_bigcommerce(export_products)
                log.info("BigCommerce import completed | summary=%s", import_summary)
            except Exception as e:
                log.exception("BigCommerce import failed | %s", e)
                raise HTTPException(status_code=500, detail=f"BigCommerce import failed: {e}")

        log.info("Export: building BigCommerce dataframe | rows=%s (first %s products)", len(export_products), limit)
        df = build_bc_dataframe(export_products, images_base_path=None)
        log.info("Export: writing Excel (wrap text, column widths)")
        buffer = dataframe_to_excel_bytes(df, sheet_name="Products")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        export_path = OUTPUT_DIR / f"bigcommerce_export_{uuid.uuid4().hex[:12]}.xlsx"
        export_path.write_bytes(buffer.getvalue())
        log.info("Export: saved to server | path=%s", export_path)
        log.info("Upload success | returning BigCommerce Excel | rows=%s | columns=%s", len(df), list(df.columns))
        background_tasks.add_task(_cleanup_export_file, export_path)
        download_name = f"bigcommerce_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = FileResponse(
            path=str(export_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=download_name,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
        # If we imported into BigCommerce, add a simple header with summary counts (for debugging).
        if import_summary:
            try:
                summary_header = f"imported={import_summary.get('products_imported', 0)};images={import_summary.get('images_set', 0)};errors={len(import_summary.get('errors') or [])}"
                response.headers["X-BigCommerce-Import"] = summary_header
            except Exception:
                pass
        return response
    except Exception as e:
        log.exception("Upload failed | step error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/export")
async def export_approved_products(
    background_tasks: BackgroundTasks,
    body: dict = Body(..., embed=False),
):
    """Accept reviewed/edited products from frontend. Generate Excel and optionally import to BigCommerce.
    Body: { "products": [ { brand_name, sku, name, price, description, image_url, _image_urls?, source_website, _search_method?, raw_row? }, ... ], "import_to_bigcommerce": false }
    Returns Excel file. If import_to_bigcommerce=true, also imports to BC and adds X-BigCommerce-Import header.
    """
    products: List[Dict[str, Any]] = body.get("products") if isinstance(body.get("products"), list) else []
    import_to_bigcommerce = body.get("import_to_bigcommerce") is True
    if not products:
        raise HTTPException(status_code=400, detail="Missing or empty 'products' array in body")
    log.info("Export requested | products=%s | import_to_bigcommerce=%s", len(products), import_to_bigcommerce)

    import_summary = None
    if import_to_bigcommerce:
        try:
            # Ensure _image_urls is set from image_url when frontend only sends image_url
            for p in products:
                if not p.get("_image_urls") and p.get("image_url"):
                    p["_image_urls"] = [p["image_url"]]
            import_summary = import_products_to_bigcommerce(products)
            log.info("BigCommerce import completed | summary=%s", import_summary)
        except Exception as e:
            log.exception("BigCommerce import failed | %s", e)
            raise HTTPException(status_code=500, detail=f"BigCommerce import failed: {e}")

    df = build_bc_dataframe(products, images_base_path=None)
    buffer = dataframe_to_excel_bytes(df, sheet_name="Products")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = OUTPUT_DIR / f"bigcommerce_export_{uuid.uuid4().hex[:12]}.xlsx"
    export_path.write_bytes(buffer.getvalue())
    log.info("Export: saved to server | path=%s", export_path)
    background_tasks.add_task(_cleanup_export_file, export_path)
    download_name = f"bigcommerce_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    response = FileResponse(
        path=str(export_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=download_name,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
    if import_summary:
        try:
            summary_header = f"imported={import_summary.get('products_imported', 0)};images={import_summary.get('images_set', 0)};errors={len(import_summary.get('errors') or [])}"
            response.headers["X-BigCommerce-Import"] = summary_header
        except Exception:
            pass
    return response


@router.post("/import-to-bigcommerce")
async def import_only_to_bigcommerce(body: dict = Body(..., embed=False)):
    """Import approved products to BigCommerce only. No Excel file. Body: { "products": [ ... ] }."""
    products: List[Dict[str, Any]] = body.get("products") if isinstance(body.get("products"), list) else []
    if not products:
        raise HTTPException(status_code=400, detail="Missing or empty 'products' array in body")
    log.info("Import-to-BC only | products=%s", len(products))
    try:
        for p in products:
            if not p.get("_image_urls") and p.get("image_url"):
                p["_image_urls"] = [p["image_url"]]
        summary = import_products_to_bigcommerce(products)
        return JSONResponse(content=summary)
    except Exception as e:
        log.exception("BigCommerce import failed | %s", e)
        raise HTTPException(status_code=500, detail=f"BigCommerce import failed: {e}")
