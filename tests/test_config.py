from productv2.config import Settings, build_chat_model


def test_build_chat_model_uses_global_responses_streaming_config() -> None:
    settings = Settings(
        openai_api_key="sk-test",
        openai_model="gpt-5.5",
        openai_api_base="https://example.test",
        openai_use_responses_api=True,
        openai_streaming=True,
        openai_output_version="responses/v1",
        openai_stream_usage=False,
    )

    model = build_chat_model(settings)

    assert model.model_name == "gpt-5.5"
    assert model.openai_api_base == "https://example.test"
    assert model.streaming is True
    assert model.use_responses_api is True
    assert model.output_version == "responses/v1"
    assert model.stream_usage is False


def test_image_generation_defaults_use_ten_minute_timeouts() -> None:
    settings = Settings()

    assert settings.image_generation_timeout == 600
    assert settings.image_generation_poll_timeout == 600
