"""B2 입력 칸 · 프리셋 · SessionBehavior 필드마다 한 줄 · 새 행동 값은 models.py 필드 + 여기 한 줄"""
from collections.abc import Mapping
from dataclasses import dataclass, fields

from ticket_guard_qa.domain.enums import ActorType
from ticket_guard_qa.domain.models import SessionBehavior
from ticket_guard_qa.macro_bots.bot_profiles import DEFAULT_BEHAVIOR_BY_ACTOR_TYPE


class BehaviorInputError(ValueError):
    pass


@dataclass(frozen=True)
class BehaviorFieldSpec:
    field_name: str  # SessionBehavior 필드 이름과 같음
    group_title: str  # 화면 묶음 · ① 진입 시점 등
    title: str
    unit: str
    minimum: int
    maximum: int
    hint: str = ""


BEHAVIOR_FIELD_SPECS: tuple[BehaviorFieldSpec, ...] = (
    BehaviorFieldSpec("entry_delay_after_open_ms", "① 진입 시점", "오픈 후 첫 진입", "ms", 0, 600_000, "0 = 오픈 순간"),
    BehaviorFieldSpec("entry_delay_deviation_ms", "① 진입 시점", "진입 흔들림", "ms", 0, 600_000, "사람은 크고 봇은 작음"),
    BehaviorFieldSpec("click_interval_mean_ms", "② 클릭 간격", "평균", "ms", 10, 60_000),
    BehaviorFieldSpec("click_interval_deviation_ms", "② 클릭 간격", "흔들림", "ms", 0, 60_000, "평균의 30% 미만이면 일정한 간격"),
    BehaviorFieldSpec("sessions_per_device", "④ 기기당 세션 수", "동시 세션", "개", 1, 50),
)

# 아직 행동 값이 없는 항목 · 트래픽 생성기 구현 후 SessionBehavior에 추가
PENDING_BEHAVIOR_GROUPS: tuple[str, ...] = ("③ 화면 흐름", "⑤ 좌석 없을 때")


@dataclass(frozen=True)
class BehaviorPreset:
    preset_id: str
    title: str
    behavior: SessionBehavior


BEHAVIOR_PRESETS: tuple[BehaviorPreset, ...] = (  # 기본 봇 값에서 시작 · "직접"은 화면에서 손으로 입력
    BehaviorPreset("open_instant", "오픈 즉시형", DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A]),
    BehaviorPreset("human_like", "사람 흉내형", DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_B]),
)


def group_field_specs() -> dict[str, list[BehaviorFieldSpec]]:
    grouped: dict[str, list[BehaviorFieldSpec]] = {}
    for spec in BEHAVIOR_FIELD_SPECS:
        grouped.setdefault(spec.group_title, []).append(spec)
    return grouped


def parse_behavior_form(form_values: Mapping[str, str]) -> SessionBehavior:
    """B2 폼 → 행동 값 · 범위 밖이면 BehaviorInputError (화면에 그대로 표시)"""
    values: dict[str, int] = {}
    for spec in BEHAVIOR_FIELD_SPECS:
        raw_value = str(form_values.get(spec.field_name, "")).strip()
        try:
            value = int(raw_value)
        except ValueError:
            raise BehaviorInputError(f"{spec.group_title} {spec.title}: 숫자를 넣어 주세요.") from None
        if not spec.minimum <= value <= spec.maximum:
            raise BehaviorInputError(f"{spec.group_title} {spec.title}: {spec.minimum:,} ~ {spec.maximum:,}{spec.unit} 사이로 넣어 주세요.")
        values[spec.field_name] = value
    return SessionBehavior(**values)


def behavior_to_dict(behavior: SessionBehavior) -> dict[str, int]:
    return {field.name: getattr(behavior, field.name) for field in fields(SessionBehavior)}
