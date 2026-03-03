# FastAPI application (all code lives here)

Run from **project root** (`poc/`):

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or: `python run.py` (if run.py exists at project root).

## Structure

- **main.py** – FastAPI app, CORS, root/health, includes upload router
- **config.py** – Settings (env `POC_*`), `PROJECT_ROOT`
- **config.yaml** – Optional app config
- **api/upload.py** – `POST /upload` (Excel file + optional max_products) → BigCommerce Excel with Source Website column
- **core/canonical_schema.py** – Canonical columns for AI mapping
- **services/** – pipeline, ai_column_mapper, ai_product_finder (web search + LLM), input_parser, export
