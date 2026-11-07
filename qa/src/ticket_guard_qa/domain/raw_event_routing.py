"""원본 DB 컬렉션 분류표 · QA 사본 · 시스템 raw_consumer/router.py raw-routing-v1 기준 · 시스템이 바꾸면 원본 적재 검증이 오분류로 알림"""
from typing import Any

RAW_ROUTING_VERSION = "raw-routing-v1"
RAW_DATABASE_NAME = "ticketguard_raw"
UNCLASSIFIED_COLLECTION_NAME = "unclassified_events"
SUPPORTED_SCHEMA_VERSIONS = (1, 2)

RAW_EVENT_TYPES_BY_COLLECTION: dict[str, tuple[str, ...]] = {
    "behavior_events": (
        "page_enter", "page_exit", "search_change", "genre_change", "show_select", "schedule_select",
        "seat_select", "seat_cancel", "quantity_change", "ui_interaction", "page_lifecycle",
    ),
    "booking_events": (
        "queue_enter", "queue_register", "queue_admitted", "queue_cancel", "connection_timeout",
        "captcha_success", "captcha_wrong", "captcha_limit_reached", "captcha_refresh",
        "booking_confirm_request", "booking_confirm_success", "booking_confirm_fail", "booking_access_rejected",
        "booking_not_open", "booking_confirm_rejected", "booking_confirm_replayed",
    ),
    "auth_events": ("login_success", "login_fail"),
    "http_events": (
        "browser_request_start", "browser_request_body", "browser_response_headers",
        "browser_request", "server_request", "server_response_headers",
    ),
    "performance_events": ("resource_timing", "navigation_timing", "performance_entry"),
    "browser_errors": ("browser_error",),
    "collector_events": ("collector_limitation", "collector_failure", "scenario_executed"),
    "raw_chunks": ("capture_chunk",),
}
RAW_COLLECTION_NAMES: tuple[str, ...] = (*RAW_EVENT_TYPES_BY_COLLECTION, UNCLASSIFIED_COLLECTION_NAME)
RAW_COLLECTION_BY_EVENT_TYPE: dict[str, str] = {
    event_type: collection_name
    for collection_name, event_types in RAW_EVENT_TYPES_BY_COLLECTION.items()
    for event_type in event_types
}


def find_expected_raw_collection(event: dict[str, Any] | None) -> str:
    """해석 실패 · 미지원 버전 · 미등록 eventType = 미분류"""
    if event is None:
        return UNCLASSIFIED_COLLECTION_NAME
    schema_version = event.get("schemaVersion")
    if type(schema_version) is not int or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return UNCLASSIFIED_COLLECTION_NAME
    event_type = event.get("eventType")
    if not isinstance(event_type, str):
        return UNCLASSIFIED_COLLECTION_NAME
    return RAW_COLLECTION_BY_EVENT_TYPE.get(event_type, UNCLASSIFIED_COLLECTION_NAME)
