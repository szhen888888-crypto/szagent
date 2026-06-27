"""Virtual model profiles for inyourday-style wearing image generation."""

from __future__ import annotations

from dataclasses import dataclass


GLOBAL_MODEL_DIRECTION = """
Gen Z new-romantic everyday creator, not a traditional jewelry model.
Early 20s, young but not childish. Approachable, relaxed, slightly aloof
and rebellious. Realistic face, no supermodel, celebrity, influencer,
cosmetic-surgery, or marketplace-model look. Real skin texture, low-makeup
finish, soft matte or subtle satin sheen. The jewelry should feel like a
natural part of the girl's personal style, not a rigid product display.
""".strip()

GLOBAL_NEGATIVE_DIRECTION = """
Avoid glossy plastic skin, heavy retouching, forced smiles, cute influencer
posing, marketplace-model styling, luxury catalog posing, obvious studio
jewelry-model styling, salon hair, celebrity likeness, runway model proportions,
and stiff product-demo gestures.
""".strip()


@dataclass(frozen=True)
class VirtualModelProfile:
    key: str
    name: str
    ethnicity: str
    age_feel: str
    face: str
    skin: str
    hair: str
    temperament: str
    wardrobe: str
    poses: str
    expression: str
    best_for: tuple[str, ...]
    prompt: str
    negative_prompt: str = GLOBAL_NEGATIVE_DIRECTION


VIRTUAL_MODEL_PROFILES: tuple[VirtualModelProfile, ...] = (
    VirtualModelProfile(
        key="romantic_rebel_european",
        name="Romantic Rebel",
        ethnicity="European woman",
        age_feel="early 20s, young but not childish",
        face=(
            "dark-haired European everyday fashion creator; attractive but not "
            "supermodel-like, with a real angular face and understated features"
        ),
        skin="real skin texture, low makeup, soft matte finish",
        hair="black or deep brown loose hair, slight wet texture, stray pieces",
        temperament="aloof, sharp, relaxed, a little rebellious",
        wardrobe="black thin-strap top, washed gray tank, worn denim, sheer black mesh",
        poses="off-axis crop, side face, lower face, shoulder and collarbone mid-shot",
        expression="calm, unsmiling, not performing",
        best_for=("cross", "lock", "coin", "snake chain", "black metal", "chunky chain"),
        prompt=(
            "Romantic Rebel profile: a dark-haired European Gen Z everyday fashion "
            "creator, relaxed and slightly rebellious, black thin-strap top or washed "
            "gray tank, off-axis shoulder and collarbone crop, calm unsmiling face, "
            "real skin texture and low makeup. Jewelry is part of her personal style."
        ),
    ),
    VirtualModelProfile(
        key="soft_romantic_european",
        name="Sharp Romantic",
        ethnicity="European woman",
        age_feel="early 20s, young but not childish",
        face=(
            "light-brown or dark-blonde European editorial creator with strong "
            "bone structure, clear cheekbones, a refined narrow face, focused "
            "eyes, and realistic natural proportions; expensive but not celebrity-like"
        ),
        skin=(
            "real skin texture, low makeup, controlled satin highlights, visible "
            "eye definition, refined but not retouched"
        ),
        hair=(
            "loose light brown or dark blonde hair, natural editorial waves, clean "
            "volume, imperfect flyaways, expensive but not salon-polished"
        ),
        temperament=(
            "high-end, cool, alert, editorial, self-possessed, quietly romantic, "
            "focused and adaptable"
        ),
        wardrobe=(
            "black or charcoal fitted tank, ivory mesh, sheer knit, fine straps, "
            "tailored muted layers, pale denim"
        ),
        poses=(
            "direct gaze, collarbone crop, side profile, waist-up editorial crop, "
            "off-axis shoulders, composed posture"
        ),
        expression=(
            "calm unsmiling direct gaze with quiet pressure, alert and distant, "
            "never sleepy, blank, cute, or timid"
        ),
        best_for=(
            "pearl",
            "bow",
            "flower",
            "thin chain",
            "heart",
            "soft silver",
            "crystal",
            "black cord",
        ),
        prompt=(
            "Sharp Romantic profile: a light-brown or dark-blonde European Gen Z "
            "editorial creator with high-end cold romantic presence, strong bone "
            "structure, direct alert gaze with quiet pressure, natural waves with "
            "flyaways, black or ivory minimal thin-strap styling, collarbone crop, "
            "real skin texture, low makeup with subtle eye definition. Jewelry "
            "feels intentional, expensive, and personal in her outfit."
        ),
    ),
    VirtualModelProfile(
        key="vintage_muse_european",
        name="Vintage Muse",
        ethnicity="European woman",
        age_feel="early 20s with a slightly old-soul mood",
        face=(
            "European vintage-feature face, realistic and memorable, not polished "
            "catalog beauty"
        ),
        skin="real skin texture, low makeup, muted natural red-brown lip",
        hair="soft brown or auburn hair, loose or low pinned, slightly undone",
        temperament="nostalgic, calm, artistic, quietly rebellious",
        wardrobe="old knit, ivory camisole, faded black, warm gray, worn denim",
        poses="old wall background, warm gray interior, half face, neck and hands",
        expression="still, observant, not cute, not commercial",
        best_for=("heart", "coin", "gemstone", "baroque", "court-inspired", "pearl"),
        prompt=(
            "Vintage Muse profile: a European Gen Z creator with vintage features, "
            "old-soul mood, muted red-brown lip, undone auburn or brown hair, old knit "
            "or ivory camisole, warm gray wall, half-face or neck-and-hands crop. "
            "Jewelry feels found, personal, and quietly romantic."
        ),
    ),
    VirtualModelProfile(
        key="cool_romantic_black",
        name="Cool Romantic",
        ethnicity="Black woman",
        age_feel="early 20s, expressive but not performative",
        face=(
            "Black everyday fashion creator with a real modern face, beautiful but "
            "not celebrity-like or overproduced"
        ),
        skin="deep skin with natural texture, soft satin highlights, minimal makeup",
        hair="natural curls, soft braids, or loose low tie with imperfect baby hairs",
        temperament="cool, relaxed, self-possessed, slightly guarded",
        wardrobe="charcoal tank, ivory rib knit, dark denim, sheer mesh, muted silver-gray",
        poses="three-quarter face, collarbone, hands near neck, waist-up editorial crop",
        expression="calm, composed, not smiling to please",
        best_for=("silver chain", "pearl", "gemstone", "star", "lock", "layered necklace"),
        prompt=(
            "Cool Romantic profile: a Black Gen Z everyday fashion creator, relaxed "
            "and self-possessed, deep real skin texture with soft satin highlights, "
            "natural curls or soft braids, charcoal tank or ivory rib knit, off-axis "
            "collarbone and waist-up crop. Jewelry becomes part of her cool personal style."
        ),
    ),
    VirtualModelProfile(
        key="playful_muse_asian",
        name="Playful Muse",
        ethnicity="Asian woman",
        age_feel="early 20s, light and youthful but not cute-influencer",
        face=(
            "Asian everyday fashion creator with realistic features, stylish and "
            "slightly mischievous, not idol-like or marketplace-model-like"
        ),
        skin="real skin texture, minimal makeup, soft matte finish",
        hair="dark natural hair, loose layers, messy half-up or low tie, small flyaways",
        temperament="playful, cool, casual, a little offbeat",
        wardrobe="washed denim, gray tank, ivory tee, muted cardigan, low-saturation color",
        poses="cropped mid-shot, side glance, lower face, shoulder, hands in frame",
        expression="quietly amused or neutral, never big smile",
        best_for=("starfish", "color charm", "fun pendant", "bow", "small pearl", "bead"),
        prompt=(
            "Playful Muse profile: an Asian Gen Z everyday fashion creator, playful "
            "but not cute-influencer, dark natural hair with messy layers, washed denim "
            "or gray tank with muted cardigan, offbeat cropped mid-shot with side glance "
            "or lower-face framing. Jewelry feels casually discovered in her outfit."
        ),
    ),
)


def get_virtual_model_profile(key: str) -> VirtualModelProfile:
    for profile in VIRTUAL_MODEL_PROFILES:
        if profile.key == key:
            return profile
    raise KeyError(f"Unknown virtual model profile: {key}")


def virtual_model_prompt_block(profile: VirtualModelProfile) -> str:
    return "\n".join(
        [
            GLOBAL_MODEL_DIRECTION,
            "",
            profile.prompt,
            f"Ethnicity: {profile.ethnicity}.",
            f"Age feel: {profile.age_feel}.",
            f"Face: {profile.face}.",
            f"Skin: {profile.skin}.",
            f"Hair: {profile.hair}.",
            f"Temperament: {profile.temperament}.",
            f"Wardrobe: {profile.wardrobe}.",
            f"Pose language: {profile.poses}.",
            f"Expression: {profile.expression}.",
        ]
    )


def virtual_model_profile_summary(profile: VirtualModelProfile) -> str:
    """Build a concise DB summary for LLM model-profile selection."""

    best_for = "、".join(profile.best_for)
    return (
        f"{profile.name}；{profile.ethnicity}；{profile.age_feel}；"
        f"脸部特征：{profile.face}；皮肤：{profile.skin}；"
        f"发型：{profile.hair}；气质：{profile.temperament}；"
        f"服装方向：{profile.wardrobe}；姿态语言：{profile.poses}；"
        f"表情：{profile.expression}；适合饰品：{best_for}。"
    )
