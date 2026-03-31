from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
LOCAL_SQLITE_PATH = (BACKEND_DIR / "storage" / "invoice_recon.db").resolve().as_posix()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Invoice Reconciliation MVP"
    environment: str = "development"
    api_v1_prefix: str = "/api"
    app_debug: bool = False

    database_url: str = f"sqlite:///{LOCAL_SQLITE_PATH}"
    auto_create_schema: bool = True

    storage_root: Path = BACKEND_DIR / "storage"
    sample_source_root: Path = PROJECT_ROOT

    default_extraction_provider: str = "mock"
    azure_document_intelligence_endpoint: str | None = None
    azure_document_intelligence_key: str | None = None
    azure_document_intelligence_invoice_model_id: str = "prebuilt-invoice"
    azure_document_intelligence_layout_model_id: str = "prebuilt-layout"
    azure_document_intelligence_default_currency: str = "EUR"
    ocr_space_endpoint: str = "https://api.ocr.space/parse/image"
    ocr_space_api_key: str | None = None
    ocr_space_language: str = "eng"
    ocr_space_engine: int = 2
    ocr_space_timeout_seconds: float = 60.0
    ocr_space_max_image_side: int = 1600
    ocr_space_max_image_bytes: int = 950_000
    ocr_space_pdf_render_dpi: int = 144
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    quantity_tolerance: float = 0.0
    unit_price_tolerance: float = 0.02
    line_amount_tolerance: float = 0.5
    tax_tolerance: float = 0.5
    total_tolerance: float = 0.5
    low_confidence_threshold: float = 0.85


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
