"""App config from env (POC_*)."""
import os
from pathlib import Path


class Settings:
    def __init__(self):
        self.app_name = os.getenv("POC_APP_NAME", "Data Enrichment → BigCommerce")
        self.cors_origins = (
            os.getenv("POC_CORS_ORIGINS", "*").split(",") if os.getenv("POC_CORS_ORIGINS") else ["*"]
        )
        # BigCommerce API (optional). If not set, import-to-BigCommerce is disabled.
        self.bc_store_hash = (os.getenv("BIGCOMMERCE_STORE_HASH", "") or "").strip()
        self.bc_access_token = (os.getenv("BIGCOMMERCE_ACCESS_TOKEN", "") or "").strip()
        self.bc_api_base_url = (os.getenv("BIGCOMMERCE_API_BASE_URL", "https://api.bigcommerce.com") or "").rstrip("/")


def get_settings():
    return Settings()


PROJECT_ROOT = Path(__file__).resolve().parent.parent
