"""FastAPI app: upload Excel → BigCommerce Excel."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.upload import router as upload_router
from app.config import get_settings
from app.logger import setup_logging

# Load .env from project root so OPENAI_API_KEY etc. are set regardless of how the app is started
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass


def create_app() -> FastAPI:
    setup_logging()
    s = get_settings()
    app = FastAPI(title=s.app_name, version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    @app.get("/")
    def root():
        return {"message": "POST /upload with Excel; AI maps columns and finds product via web search for first N rows. Returns BigCommerce Excel with Source Website column.", "endpoints": {"POST /upload": "Upload Excel (file, optional max_products=5) → download BigCommerce Excel"}}
    @app.get("/health")
    def health():
        return {"status": "ok"}
    app.include_router(upload_router)
    return app

app = create_app()
