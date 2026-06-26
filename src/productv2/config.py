"""Runtime settings for the product listing system."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE_DATA = PROJECT_ROOT / "inyourday-candidate-products-site-raw-20260622.json"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "productv2.db"
DEFAULT_RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_PRODUCT_ASSETS_DIR = PROJECT_ROOT / "data" / "products"
DEFAULT_ENROUTE_BESTSELLERS_DIR = PROJECT_ROOT / "enroute-bestsellers"
DEFAULT_MODEL_PROFILES_DIR = PROJECT_ROOT / "data" / "model_profiles"
DEFAULT_WORKFLOW_LOGS_DIR = PROJECT_ROOT / "workflow-logs"
DEFAULT_OPENAI_BASE_URL = "https://www.lynxhub.top"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_IMAGE_GENERATION_BASE_URL = "https://grsaiapi.com"
DEFAULT_IMAGE_GENERATION_MODEL = "gpt-image-2"


@dataclass(frozen=True)
class LLMProvider:
    """OpenAI-compatible Responses API provider configuration."""

    name: str
    api_base: str
    api_key: str


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    productv2_data_path: Path = DEFAULT_CANDIDATE_DATA
    productv2_database_path: Path = DEFAULT_DATABASE_PATH
    productv2_raw_data_dir: Path = DEFAULT_RAW_DATA_DIR
    productv2_product_assets_dir: Path = DEFAULT_PRODUCT_ASSETS_DIR
    productv2_enroute_bestsellers_dir: Path = DEFAULT_ENROUTE_BESTSELLERS_DIR
    productv2_model_profiles_dir: Path = DEFAULT_MODEL_PROFILES_DIR
    productv2_workflow_logs_dir: Path = DEFAULT_WORKFLOW_LOGS_DIR
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
    openai_fallback_providers: str = ""
    enroute_analysis_temperature: float | None = 0.9
    enroute_analysis_top_p: float | None = 0.9
    image_generation_api_key: SecretStr | None = None
    image_generation_api_base: str = DEFAULT_IMAGE_GENERATION_BASE_URL
    image_generation_model: str = DEFAULT_IMAGE_GENERATION_MODEL
    image_generation_aspect_ratio: str = "4/5"
    image_generation_reply_type: str = "async"
    image_generation_timeout: float | None = 600.0
    image_generation_max_retries: int = 2
    image_generation_poll_interval: float = 2.0
    image_generation_poll_timeout: float = 600.0
    ai_call_lock_wait_timeout: float = 900.0
    ai_call_lock_poll_interval: float = 2.0
    ai_call_lock_stale_after: float = 3600.0
    feishu_app_id: str = ""
    feishu_app_secret: SecretStr | None = None

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


def llm_providers(settings: Settings) -> list[LLMProvider]:
    """Return primary and fallback OpenAI-compatible providers in call order."""

    providers: list[LLMProvider] = []
    primary_key = (
        settings.openai_api_key.get_secret_value()
        if settings.openai_api_key
        else ""
    )
    if primary_key:
        providers.append(
            LLMProvider(
                name="primary",
                api_base=settings.openai_api_base,
                api_key=primary_key,
            )
        )
    providers.extend(_parse_fallback_providers(settings.openai_fallback_providers))
    return providers


def llm_provider_fingerprint(settings: Settings) -> list[dict[str, str]]:
    """Provider identity for lock/cache keys without exposing secrets."""

    return [
        {"name": provider.name, "api_base": provider.api_base}
        for provider in llm_providers(settings)
    ]


def _parse_fallback_providers(raw_value: str) -> list[LLMProvider]:
    if not raw_value.strip():
        return []
    parsed = json.loads(raw_value)
    if not isinstance(parsed, list):
        raise ValueError("OPENAI_FALLBACK_PROVIDERS must be a JSON array")
    providers: list[LLMProvider] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValueError("Each OPENAI_FALLBACK_PROVIDERS item must be an object")
        api_base = _string_value(item, "api_base") or _string_value(item, "base_url")
        api_key = _string_value(item, "api_key") or _string_value(item, "key")
        if not api_base or not api_key:
            raise ValueError(
                "Each OPENAI_FALLBACK_PROVIDERS item requires api_base and api_key"
            )
        providers.append(
            LLMProvider(
                name=_string_value(item, "name") or f"fallback_{index}",
                api_base=api_base,
                api_key=api_key,
            )
        )
    return providers


def _string_value(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    return value.strip() if isinstance(value, str) else ""
