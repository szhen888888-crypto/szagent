"""Runtime settings for the product listing system."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE_DATA = PROJECT_ROOT / "inyourday-candidate-products-site-raw-20260622.json"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "productv2.db"
DEFAULT_RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_PRODUCT_ASSETS_DIR = PROJECT_ROOT / "data" / "products"
DEFAULT_ENROUTE_BESTSELLERS_DIR = PROJECT_ROOT / "enroute-bestsellers"
DEFAULT_MODEL_PROFILES_DIR = PROJECT_ROOT / "data" / "model_profiles"
DEFAULT_OPENAI_BASE_URL = "https://www.lynxhub.top"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_IMAGE_GENERATION_BASE_URL = "https://grsaiapi.com"
DEFAULT_IMAGE_GENERATION_MODEL = "gpt-image-2"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    productv2_data_path: Path = DEFAULT_CANDIDATE_DATA
    productv2_database_path: Path = DEFAULT_DATABASE_PATH
    productv2_raw_data_dir: Path = DEFAULT_RAW_DATA_DIR
    productv2_product_assets_dir: Path = DEFAULT_PRODUCT_ASSETS_DIR
    productv2_enroute_bestsellers_dir: Path = DEFAULT_ENROUTE_BESTSELLERS_DIR
    productv2_model_profiles_dir: Path = DEFAULT_MODEL_PROFILES_DIR
    productv2_default_limit: int = 5
    openai_api_key: SecretStr | None = None
    openai_model: str = DEFAULT_OPENAI_MODEL
    openai_api_base: str = DEFAULT_OPENAI_BASE_URL
    openai_use_responses_api: bool = True
    openai_streaming: bool = True
    openai_output_version: str = "responses/v1"
    openai_stream_usage: bool = False
    openai_timeout: float | None = 120.0
    openai_max_retries: int = 2
    enroute_analysis_temperature: float | None = 0.9
    enroute_analysis_top_p: float | None = 0.9
    image_generation_api_key: SecretStr | None = None
    image_generation_api_base: str = DEFAULT_IMAGE_GENERATION_BASE_URL
    image_generation_model: str = DEFAULT_IMAGE_GENERATION_MODEL
    image_generation_aspect_ratio: str = "1024x1024"
    image_generation_reply_type: str = "json"
    image_generation_timeout: float | None = 600.0
    image_generation_max_retries: int = 2
    image_generation_poll_interval: float = 2.0
    image_generation_poll_timeout: float = 600.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def build_chat_model(settings: Settings | None = None):
    """Build the globally configured LangChain chat model."""

    from langchain_openai import ChatOpenAI

    active_settings = settings or Settings()
    api_key = (
        active_settings.openai_api_key.get_secret_value()
        if active_settings.openai_api_key
        else None
    )

    return ChatOpenAI(
        model=active_settings.openai_model,
        api_key=api_key,
        base_url=active_settings.openai_api_base,
        streaming=active_settings.openai_streaming,
        use_responses_api=active_settings.openai_use_responses_api,
        output_version=active_settings.openai_output_version,
        stream_usage=active_settings.openai_stream_usage,
        timeout=active_settings.openai_timeout,
        max_retries=active_settings.openai_max_retries,
    )
