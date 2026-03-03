# Data Enrichment → BigCommerce POC (AI-only)

Proof of concept: upload an Excel file → AI maps columns → for the first N products, AI uses **web search** to find the product (e.g. on Amazon, Flipkart) and returns real product data plus **which website** it came from. No scraping. Output Excel includes a **Source Website** column.

## Flow

1. **Upload Excel** – any column names.
2. **AI column mapping** – map source headers to canonical columns (SKU, Name, Description, Brand Name, Price, etc.).
3. **Parse** – first N products (default 5) are sent to the AI product finder.
4. **AI product finder** – for each product:
   - Web search (Tavily) using brand + name + SKU.
   - OpenAI receives search results and **must match the correct product** (same SKU/model), picks **one** best source (e.g. Amazon, Flipkart).
   - Returns: name, description, price, image URL, **source_website** (URL of the page).
5. **Export** – BigCommerce Excel with all rows; first N rows have AI-filled data and **Source Website** column.

## Quick start

Run from the **project root** (`poc/`):

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **POST /upload**: send Excel as `file`; optional `max_products` (default 5). Response is BigCommerce Excel download with **Source Website** column.
- **http://localhost:8000/docs** – Swagger UI.

## Environment

- **OPENAI_API_KEY** – required for column mapping and AI product finder.
- **TAVILY_API_KEY** – required for web search (get key at https://tavily.com). Without it, AI product finder skips search and returns empty/placeholder.

Copy `.env.example` to `.env` and set both keys.

## Output columns

- Brand Name, SKU, Name, Price, Description, Image 1 File, **Source Website**

For rows enriched by AI, **Source Website** is the URL of the page the AI used (e.g. Amazon product page). Other rows show "—".

## Project structure

```
poc/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── config.yaml
│   ├── logger.py
│   ├── api/upload.py
│   ├── core/canonical_schema.py
│   └── services/
│       ├── pipeline.py          # load → map → parse → AI find (first N) → export
│       ├── ai_column_mapper.py
│       ├── ai_product_finder.py  # Tavily search + OpenAI → product data + source_website
│       ├── input_parser.py
│       └── export.py
├── .env.example
├── docs/
└── requirements.txt
```

## POC scope

See **docs/POC-Scope.md** for scope and success criteria.
