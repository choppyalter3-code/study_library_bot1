from dataclasses import dataclass

from app.personality import PICKME_PEPE, PepeMode, get_system_prompt
from app.personality.pickme_pepe import normalize_mode


@dataclass(frozen=True)
class PepeContext:
    mode: PepeMode
    system_prompt: str
    behavior_rules: tuple[str, ...]
    style_examples: tuple[str, ...]


def get_pepe_mode(mode: PepeMode | str = PepeMode.SOFT) -> PepeMode:
    return normalize_mode(mode)


def get_pepe_system_prompt(mode: PepeMode | str = PepeMode.SOFT) -> str:
    return get_system_prompt(get_pepe_mode(mode))


def build_pepe_context(mode: PepeMode | str = PepeMode.SOFT) -> PepeContext:
    pepe_mode = get_pepe_mode(mode)
    return PepeContext(
        mode=pepe_mode,
        system_prompt=get_pepe_system_prompt(pepe_mode),
        behavior_rules=PICKME_PEPE.behavior_rules,
        style_examples=PICKME_PEPE.style_examples,
    )


def generate_personality_context(mode: PepeMode | str = PepeMode.SOFT) -> dict[str, object]:
    context = build_pepe_context(mode)
    return {
        "mode": context.mode.value,
        "system_prompt": context.system_prompt,
        "behavior_rules": list(context.behavior_rules),
        "style_examples": list(context.style_examples),
    }
