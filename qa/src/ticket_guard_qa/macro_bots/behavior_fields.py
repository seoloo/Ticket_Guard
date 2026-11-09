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
    choices: tuple[tuple[int, str], ...] = ()  # 있으면 B2에서 선택 상자 · (값, 표시 문구)


BROWSER_TRACE_CHOICES: tuple[tuple[int, str], ...] = (
    (0, "흔적 없음 · 예매 API 요청만"),
    (1, "화면 조회 · 화면 이벤트 · 브라우저 정보 전송"),
)

BEHAVIOR_FIELD_SPECS: tuple[BehaviorFieldSpec, ...] = (  # SessionBehavior 필드 순서 = 화면 순서
    BehaviorFieldSpec("entry_delay_after_open_ms", "① 예매 시작 시점", "오픈 후 예매 시작까지(평균)", "ms", 0, 600_000,
                      "0 = 예매 오픈 순간(T0)"),
    BehaviorFieldSpec("entry_delay_deviation_ms", "① 예매 시작 시점", "예매 시작 시각 편차", "ms", 0, 600_000,
                      "편차 작음 = 모든 세션 동시 시작"),
    BehaviorFieldSpec("click_interval_mean_ms", "② 좌석 클릭 간격", "클릭 간격(평균)", "ms", 10, 60_000),
    BehaviorFieldSpec("click_interval_deviation_ms", "② 좌석 클릭 간격", "클릭 간격 편차", "ms", 0, 60_000,
                      "변동계수(CV) 0.3 미만 = 정주기"),
    BehaviorFieldSpec("browse_page_count", "③ 예매 전 화면 조회", "목록 · 상세 화면 조회 수", "회", 0, 10,
                      "0 = 화면 조회 없이 바로 예매"),
    BehaviorFieldSpec("page_dwell_mean_ms", "③ 예매 전 화면 조회", "화면 체류 시간(평균)", "ms", 0, 120_000),
    BehaviorFieldSpec("page_dwell_deviation_ms", "③ 예매 전 화면 조회", "화면 체류 시간 편차", "ms", 0, 120_000,
                      "편차 작음 = 화면마다 같은 시간"),
    BehaviorFieldSpec("sessions_per_device", "④ 동시 예매 창", "기기 1대당 예매 창 수", "개", 1, 50),
    BehaviorFieldSpec("sold_out_retry_count", "⑤ 매진 좌석 대응", "다른 좌석 재시도 횟수", "회", 0, 20,
                      "0 = 먼저 팔린 좌석이면 바로 포기"),
    BehaviorFieldSpec("sold_out_retry_delay_ms", "⑤ 매진 좌석 대응", "재시도 전 대기", "ms", 0, 60_000),
    BehaviorFieldSpec("browser_trace_level", "⑥ 브라우저 흔적", "화면 이벤트 · 브라우저 정보", "", 0, 1,
                      choices=BROWSER_TRACE_CHOICES),
)

# 아직 행동 값이 없는 항목 · 트래픽 생성기 구현 후 SessionBehavior에 추가
PENDING_BEHAVIOR_GROUPS: tuple[str, ...] = ()


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
        if spec.choices and value not in dict(spec.choices):
            raise BehaviorInputError(f"{spec.group_title} {spec.title} · 선택 오류")
        values[spec.field_name] = value
    return SessionBehavior(**values)


def behavior_to_dict(behavior: SessionBehavior) -> dict[str, int]:
    return {field.name: getattr(behavior, field.name) for field in fields(SessionBehavior)}
