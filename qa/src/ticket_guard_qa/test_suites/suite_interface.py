"""모든 시험 묶음이 따르는 모양 · 못 만든 부분은 NotImplementedError → 건너뜀"""
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ticket_guard_qa.answer_key.answer_key_repository import AnswerKeyRepository
from ticket_guard_qa.domain.models import RunConfig, SuiteResult
from ticket_guard_qa.macro_bots.bot_profiles import BotProfileRegistry
from ticket_guard_qa.system_targets.target_interfaces import SystemTarget


@dataclass
class SuiteContext:
    run_id: str
    run_config: RunConfig
    system_target: SystemTarget
    answer_key_repository: AnswerKeyRepository
    case_data_dir: Path
    report_progress: Callable[..., None]  # (글, **ProgressMessage 필드) · 03 · B3 화면
    bot_profile_registry: BotProfileRegistry = field(default_factory=BotProfileRegistry)


@dataclass(frozen=True)
class SuiteGuide:
    """02 Suite 말풍선 · 비전공자 기준 쉬운 말 · 명사형"""
    purpose: str  # 검증 대상
    method: str  # 검증 방법
    pass_condition: str  # 통과 기준


class QaSuite(Protocol):
    suite_name: str
    title: str
    related_codes: tuple[str, ...]  # E · T 코드
    guide: SuiteGuide

    def run(self, context: SuiteContext) -> SuiteResult: ...
