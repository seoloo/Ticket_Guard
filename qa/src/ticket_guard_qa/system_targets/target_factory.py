"""설정 보고 가짜 / 실제 대상 고르기 · 시험 코드는 이 함수 결과만 사용"""
from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.settings import Settings
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.system_targets.live_django_system import (
    LiveDjangoBookingApi,
    LiveDjangoLiveMetricsReader,
    LiveDjangoVerdictReader,
    LiveDockerProcessControl,
    VirtualUserAccountPool,
)
from ticket_guard_qa.system_targets.live_mongo_reader import LiveMongoPipelineReader, LiveMongoVerdictReader
from ticket_guard_qa.system_targets.target_interfaces import SystemTarget


def build_system_target(settings: Settings, target_kind: TargetKind | None = None) -> SystemTarget:
    selected_kind = target_kind or settings.target_kind
    if selected_kind is TargetKind.FAKE:
        return build_fake_system_target(settings.random_seed)
    has_mongo = bool(settings.system_mongo_uri)
    return SystemTarget(
        kind=TargetKind.LIVE,
        booking_api=LiveDjangoBookingApi(
            settings.system_base_url, settings.system_username, settings.system_password,
            VirtualUserAccountPool(settings.test_account_count, settings.test_account_password, settings.captcha_fixed_answer),
        ),
        verdict_reader=LiveMongoVerdictReader(settings.system_mongo_uri) if has_mongo else LiveDjangoVerdictReader(),
        pipeline_reader=LiveMongoPipelineReader(settings.system_mongo_uri),
        live_metrics_reader=LiveDjangoLiveMetricsReader(),
        process_control=LiveDockerProcessControl(),
    )
