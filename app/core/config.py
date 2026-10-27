"""Application configuration managed by Pydantic Settings."""
from functools import lru_cache
from dotenv import load_dotenv
load_dotenv(override=False)
from pathlib import Path
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for MineTrace application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Storage & DB
    database_url: str = Field(
        default="sqlite:///./data/minetrace.db",
        alias="DATABASE_URL",
    )
    data_dir: Path = Field(
        default=Path("./data"),
        alias="DATA_DIR",
    )
    chroma_persist_dir: Path = Field(
        default=Path("./data/chroma"),
        alias="CHROMA_PERSIST_DIR",
    )
    documents_dir: Path = Field(
        default=Path("./data/documents"),
        alias="DOCUMENTS_DIR",
    )
    reports_dir: Path = Field(
        default=Path("./data/reports"),
        alias="REPORTS_DIR",
    )

    # Ollama & Local LLM
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(
        default="llama3.2:latest",
        alias="OLLAMA_MODEL",
    )
    embedding_model: str = Field(
        default="nomic-embed-text:latest",
        alias="EMBEDDING_MODEL",
    )
    rag_top_k: int = Field(
        default=3,
        alias="RAG_TOP_K",
    )
    rag_timeout_seconds: float = Field(
        default=60.0,
        alias="RAG_TIMEOUT_SECONDS",
    )

    # UN Comtrade
    comtrade_api_key: Optional[str] = Field(default=None, alias="COMTRADE_API_KEY")
    comtrade_base_url: str = Field(
        default="https://comtradeapi.un.org/public/v1/preview/C/A/HS",
        alias="COMTRADE_BASE_URL",
    )
    # Default mineral codes (lithium carbonates 283691, hydroxide 282520, spodumene 253090, lithium-ion accumulators 850760)
    default_commodity_codes: List[str] = Field(
        default_factory=lambda: ["283691", "282520", "253090", "850760"],
        alias="DEFAULT_COMMODITY_CODES",
    )

    # OFAC Sanctions List
    ofac_sdn_csv_url: str = Field(
        default="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
        alias="OFAC_SDN_CSV_URL",
    )
    ofac_cons_csv_url: str = Field(
        default="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/CONS_PRIM.CSV",
        alias="OFAC_CONS_CSV_URL",
    )

    # HTTP Client Configuration
    request_timeout_seconds: float = Field(
        default=30.0,
        alias="REQUEST_TIMEOUT_SECONDS",
    )

    # Model 2: GDELT Project DOC 2.0 API Configuration
    gdelt_base_url: str = Field(
        default="https://api.gdeltproject.org/api/v2/doc/doc",
        alias="GDELT_BASE_URL",
    )
    gdelt_timeout: float = Field(
        default=30.0, ge=1, le=60,
        alias="GDELT_TIMEOUT",
    )
    gdelt_max_retries: int = Field(
        default=3, ge=0, le=4,
        alias="GDELT_MAX_RETRIES",
    )
    gdelt_lookback_hours: int = Field(
        default=24,
        alias="GDELT_LOOKBACK_HOURS",
    )
    gdelt_request_interval_seconds: float = Field(
        default=5.5, ge=5.5, le=120,
        alias="GDELT_REQUEST_INTERVAL_SECONDS",
    )

    @field_validator("default_commodity_codes", mode="before")
    @classmethod
    def parse_commodity_codes(cls, v):
        if isinstance(v, str):
            return [code.strip() for code in v.split(",") if code.strip()]
        if isinstance(v, (list, tuple)):
            return [str(code).strip() for code in v if str(code).strip()]
        return v

    @property
    def raw_data_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_data_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def report_output_dir(self) -> Path:
        return self.reports_dir


@lru_cache()
def get_settings() -> Settings:
    """Returns cached application settings."""
    return Settings()
