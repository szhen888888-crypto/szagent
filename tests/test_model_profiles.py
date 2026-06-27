from productv2.model_profiles import VIRTUAL_MODEL_PROFILES
from productv2.model_profiles import get_virtual_model_profile
from productv2.model_profiles import virtual_model_prompt_block
from productv2.model_profiles import virtual_model_profile_summary


def test_virtual_model_profiles_match_requested_distribution() -> None:
    ethnicities = [profile.ethnicity for profile in VIRTUAL_MODEL_PROFILES]

    assert len(VIRTUAL_MODEL_PROFILES) == 5
    assert ethnicities.count("European woman") == 3
    assert ethnicities.count("Black woman") == 1
    assert ethnicities.count("Asian woman") == 1


def test_virtual_model_profiles_keep_inyourday_style_constraints() -> None:
    for profile in VIRTUAL_MODEL_PROFILES:
        prompt = virtual_model_prompt_block(profile)

        assert "Gen Z" in prompt
        assert "real skin texture" in prompt
        assert "not a traditional jewelry model" in prompt
        assert "Jewelry" in prompt or "jewelry" in prompt
        assert "celebrity" in profile.negative_prompt
        assert "marketplace-model" in profile.negative_prompt


def test_get_virtual_model_profile_returns_named_profile() -> None:
    profile = get_virtual_model_profile("romantic_rebel_european")

    assert profile.name == "Romantic Rebel"
    assert "cross" in profile.best_for


def test_soft_romantic_slot_is_replaced_with_sharper_profile() -> None:
    profile = get_virtual_model_profile("soft_romantic_european")

    assert profile.name == "Sharp Romantic"
    assert "high-end" in profile.temperament
    assert "alert" in profile.expression
    assert "direct gaze" in profile.poses
    assert "sleepy" in profile.expression
    assert "quiet pressure" in profile.expression
    assert "soft" not in profile.temperament.lower()


def test_virtual_model_profile_summary_is_compact_for_database() -> None:
    profile = get_virtual_model_profile("romantic_rebel_european")
    summary = virtual_model_profile_summary(profile)

    assert "Romantic Rebel" in summary
    assert "European woman" in summary
    assert "适合饰品" in summary
    assert "snake chain" in summary
