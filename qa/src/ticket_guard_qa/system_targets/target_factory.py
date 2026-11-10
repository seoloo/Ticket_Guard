"""설정 보고 가짜 / 실제 대상 고르기 · 시험 코드는 이 함수 결과만 사용"""
from ticket_guard_qa.domain.enums import TargetKind
from ticket_guard_qa.settings import Settings
from ticket_guard_qa.system_targets.fake_system import build_fake_system_target
from ticket_guard_qa.system_targets.live_django_system import (
    LiveDjangoBookingApi,
    LiveDjangoLiveMetricsReader,
    LiveDjangoVerdictReader,
    LiveDockerProcessControl,
    SystemAdminAccount,
    VirtualUserAccountPool,
)
from ticket_guard_qa.system_targets.live_kafka_injector import KafkaEventInjector
from ticket_guard_qa.system_targets.live_kafka_reader import KafkaEventStreamReader
from ticket_guard_qa.system_targets.live_mongo_reader import LiveMongoPipelineReader, LiveMongoVerdictReader
from ticket_guard_qa.system_targets.live_raw_mongo_reader import LiveMongoRawEventReader
from ticket_guard_qa.system_targets.target_interfaces import PIPELINE_SERVICE_NAME, SystemTarget


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
            SystemAdminAccount(settings.system_admin_username, settings.system_admin_password),
            queue_admission_limit=settings.queue_admission_limit,
            browser_executable_path=settings.browser_executable_path,
            max_concurrent_browsers=settings.max_concurrent_browsers,
        ),
        verdict_reader=LiveMongoVerdictReader(settings.system_mongo_uri) if has_mongo else LiveDjangoVerdictReader(),
        pipeline_reader=LiveMongoPipelineReader(settings.system_mongo_uri, settings.kafka_events_topic),
        live_metrics_reader=LiveDjangoLiveMetricsReader(),
        process_control=LiveDockerProcessControl({PIPELINE_SERVICE_NAME: settings.pipeline_container_name}, settings.docker_socket_path),
        event_stream_reader=(
            KafkaEventStreamReader(settings.kafka_bootstrap_servers, settings.kafka_events_topic)
            if settings.kafka_bootstrap_servers else None
        ),
        event_injector=(
            KafkaEventInjector(settings.kafka_bootstrap_servers, settings.kafka_events_topic)
            if settings.is_kafka_contract_injection_enabled and settings.kafka_bootstrap_servers else None
        ),
        raw_event_reader=(
            LiveMongoRawEventReader(settings.system_raw_mongo_uri, settings.kafka_events_topic, settings.system_raw_source_id)
            if settings.system_raw_mongo_uri and settings.system_raw_source_id else None
        ),
    )
