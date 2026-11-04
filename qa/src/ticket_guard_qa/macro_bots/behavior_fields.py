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
    BehaviorFieldSpec("entry_delay_after_open_ms", "① 진입 타이밍", "진입 지연(평균)", "ms", 0, 600_000, "0 = 오픈 시각(T0)"),
    BehaviorFieldSpec("entry_delay_deviation_ms", "① 진입 타이밍", "진입 지연 표준편차", "ms", 0, 600_000, "편차 작음 = 기계적 진입"),
    BehaviorFieldSpec("click_interval_mean_ms", "② 요청 간격", "평균 간격", "ms", 10, 60_000),
    BehaviorFieldSpec("click_interval_deviation_ms", "② 요청 간격", "간격 표준편차", "ms", 0, 60_000, "변동계수(CV) 0.3 미만 = 정주기"),
    BehaviorFieldSpec("sessions_per_device", "④ 디바이스당 세션", "병렬 세션", "개", 1, 50),
)

# 아직 행동 값이 없는 항목 · 트래픽 생성기 구현 후 SessionBehavior에 추가
PENDING_BEHAVIOR_GROUPS: tuple[str, ...] = ("③ 페이지 흐름", "⑤ 재고 없음 대응")


@dataclass(frozen=True)
class BehaviorPreset:
    preset_id: str
    title: str
    behavior: SessionBehavior


BEHAVIOR_PRESETS: tuple[BehaviorPreset, ...] = (  # 기본 봇 값에서 시작 · 이름은 봇 이름과 같게
    BehaviorPreset("high_speed_repeat", "고속 반복 매크로", DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_A]),
    BehaviorPreset("disguised", "위장 매크로", DEFAULT_BEHAVIOR_BY_ACTOR_TYPE[ActorType.BOT_B]),
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
            raise BehaviorInputError(f"{spec.group_title} {spec.title} · 형식 오류(숫자)") from None
        if not spec.minimum <= value <= spec.maximum:
            raise BehaviorInputError(f"{spec.group_title} {spec.title} · 범위 오류({spec.minimum:,} ~ {spec.maximum:,}{spec.unit})")
        values[spec.field_name] = value
    return SessionBehavior(**values)


def behavior_to_dict(behavior: SessionBehavior) -> dict[str, int]:
    return {field.name: getattr(behavior, field.name) for field in fields(SessionBehavior)}
