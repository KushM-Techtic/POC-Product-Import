"""Upload Excel → AI column mapping → AI product find (web search) for first N products → BigCommerce Excel download."""
import tempfile
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.logger import get_logger
from app.services.bigcommerce_client import import_products_to_bigcommerce
from app.services.export import dataframe_to_excel_bytes
from app.services.pipeline import build_export_dataframe, run_pipeline

router = APIRouter(tags=["upload"])
log = get_logger("app.api.upload")


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
):
    """Upload Excel. AI maps columns, then for first N products runs web search + AI.
    Choose search_method to compare results.
    Always returns a BigCommerce-style Excel file. Optionally also imports products into BigCommerce via API.
    """
    log.info(
        "Upload started | file=%s | max_products=%s | search_method=%s | import_to_bigcommerce=%s",
        file.filename or "(none)",
        max_products,
        search_method.value,
        import_to_bigcommerce,
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
        enriched, _ = run_pipeline(tmp_path, max_products_to_enrich=limit, search_method=search_method.value)
        log.info("Pipeline: run_pipeline completed | products=%s", len(enriched))
        export_products = enriched[:limit]
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
        df = build_export_dataframe(export_products, images_base_path=None)
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
