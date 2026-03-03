# Frontend (React + Vite)

Simple UI to upload an Excel file to the FastAPI backend and download the generated BigCommerce Excel.

## Run locally

In one terminal (backend):

```bash
cd /home/techtic/Downloads/poc
source venv/bin/activate  # if using virtualenv
cd backend
python3 run.py
```

By default the API listens on `http://localhost:8000`.

In another terminal (frontend):

```bash
cd /home/techtic/Downloads/poc/frontend
npm install
npm run dev
```

Then open the URL shown by Vite (typically `http://localhost:5173`).

## API base URL

- The frontend uses `VITE_API_BASE_URL` if set, otherwise it falls back to `http://localhost:8000`.
- To override, create a `.env` file in `frontend`:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## What the page does

- Lets you pick the **source Excel** (`.xlsx` / `.xls`).
- Lets you choose:
  - **Max products** (number of rows to enrich with AI).
  - **Search method** (`tavily` or `openai`) — this maps to the backend `search_method` field.
- Sends a `POST /upload` request with `multipart/form-data`:
  - `file`
  - `max_products`
  - `search_method`
- When the backend responds with the Excel file, the browser automatically triggers a **file download**.
