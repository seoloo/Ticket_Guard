"""관리자 전용 MongoDB 조회 · 허용 컬렉션과 필드만 읽기 · QA 저장소 접근 금지"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from pymongo import MongoClient

READ_TIMEOUT_MS = 3000
MAX_EVENTS = 5000
KST = timezone(timedelta(hours=9))
EVENT_LABELS = {
    "queue_enter": "대기열 진입", "queue_register": "대기열 등록", "queue_admitted": "입장 허용",
    "captcha_success": "보안문자 통과", "captcha_wrong": "보안문자 오답", "seat_select": "좌석 선택",
    "quantity_change": "수량 변경", "booking_confirm_request": "예매 확정 요청",
    "booking_confirm_success": "예매 확정 성공", "booking_confirm_replayed": "예매 확정 재전송",
    "booking_confirm_fail": "예매 확정 실패", "booking_confirm_rejected": "예매 확정 거부",
    "booking_access_rejected": "예매 접근 거부", "booking_not_open": "예매 오픈 전 접근",
    "login_success": "로그인 성공", "page_enter": "화면 진입", "scenario_executed": "시나리오 실행",
}
FIELDS = {name: 1 for name in (
    "eventId", "eventType", "userId", "bookingAttemptId", "showId", "scheduleId", "result",
    "errorCode", "occurredAt", "receivedAt", "normalizedAt", "isSimulation",
)} | {"_id": 0}


def format_time(value) -> str:
    return as_time(value).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST") if as_time(value) else "미관측"


def as_time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return None


class AdminMongoReader:
    def __init__(self, mongo_uri: str):
        if not mongo_uri:
            raise ValueError("관리자 MongoDB URI 미설정")
        self.mongo_uri = mongo_uri

    def read_dashboard(self, period="all", show="", schedule="", data_kind="all"):
        query = {}
        if period in ("today", "24h"):
            now = datetime.now(timezone.utc)
            start = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc) if period == "today" else now - timedelta(hours=24)
            query["occurredAt"] = {"$gte": start, "$lte": now}
        if show:
            query["showId"] = show
        if schedule:
            query["scheduleId"] = schedule
        if data_kind == "simulation":
            query["isSimulation"] = True
        elif data_kind == "normal":
            query["isSimulation"] = {"$ne": True}
        with MongoClient(self.mongo_uri, serverSelectionTimeoutMS=READ_TIMEOUT_MS,
                         connectTimeoutMS=READ_TIMEOUT_MS, socketTimeoutMS=READ_TIMEOUT_MS,
                         tz_aware=True, appname="ticketguard-admin-reader") as client:
            database = client.get_default_database()
            counts = {name: database[name].count_documents({}, maxTimeMS=READ_TIMEOUT_MS)
                      for name in ("clean_events", "quarantine_events", "event_metrics")}
            matched = database.clean_events.count_documents(query, maxTimeMS=READ_TIMEOUT_MS)
            events = list(database.clean_events.find(query, FIELDS).sort("occurredAt", -1).limit(MAX_EVENTS).max_time_ms(READ_TIMEOUT_MS))
            # rawValue와 details는 화면에 전달하지 않음.
            reasons = list(database.quarantine_events.aggregate([
                {"$group": {"_id": "$reason", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}, {"$limit": 20},
            ], maxTimeMS=READ_TIMEOUT_MS))
            options = list(database.clean_events.aggregate([
                {"$group": {"_id": {"show": "$showId", "schedule": "$scheduleId"}}}, {"$limit": 200},
            ], maxTimeMS=READ_TIMEOUT_MS))
            name = database.name
        result = build_dashboard(events)
        return result | {"database": name, "counts": counts, "matched": matched,
                         "is_truncated": matched > MAX_EVENTS, "limit": MAX_EVENTS,
                         "reasons": reasons, "options": [item["_id"] for item in options],
                         "loaded_at": format_time(datetime.now(timezone.utc))}


def build_dashboard(events):
    events = sorted(events, key=lambda event: as_time(event.get("occurredAt")) or datetime.min.replace(tzinfo=timezone.utc))
    attempts = defaultdict(list)
    users = defaultdict(list)
    event_counts = Counter()
    failures = Counter()
    failure_attempts = defaultdict(set)
    for event in events:
        event_counts[str(event.get("eventType") or "미분류")] += 1
        if event.get("bookingAttemptId"):
            attempts[str(event["bookingAttemptId"])].append(event)
        if event.get("userId"):
            users[str(event["userId"])].append(event)
        if event.get("result") in ("failure", "rejected"):
            reason = str(event.get("errorCode") or "사유 미기록")
            failures[reason] += 1
            if event.get("bookingAttemptId"):
                failure_attempts[reason].add(str(event["bookingAttemptId"]))
    starts = {key for key, rows in attempts.items() if any(e.get("eventType") in ("queue_enter", "queue_register") for e in rows)}
    completed = {key for key in starts if any(e.get("eventType") == "booking_confirm_success" and e.get("result") == "success" for e in attempts[key])}
    stages = [(label, sum(any(e.get("eventType") in types for e in rows) for rows in attempts.values())) for label, types in (
        ("대기열 진입 · 등록", {"queue_enter", "queue_register"}), ("입장 허용", {"queue_admitted"}),
        ("보안문자 통과", {"captcha_success"}), ("좌석 · 수량 선택", {"seat_select", "quantity_change"}),
        ("예매 확정 성공", {"booking_confirm_success"}),
    )]
    durations = []
    for label, before, after in [("대기열 대기", {"queue_enter", "queue_register"}, {"queue_admitted"}),
                                  ("보안문자 확인", {"queue_admitted"}, {"captcha_success"}),
                                  ("좌석 · 수량 선택", {"captcha_success"}, {"booking_confirm_request"}),
                                  ("예매 확정", {"booking_confirm_request"}, {"booking_confirm_success"})]:
        values = []
        for rows in attempts.values():
            left = [as_time(e.get("occurredAt")) for e in rows if e.get("eventType") in before and as_time(e.get("occurredAt"))]
            right = [as_time(e.get("occurredAt")) for e in rows if e.get("eventType") in after and as_time(e.get("occurredAt"))]
            if left and right and min(right) >= min(left):
                values.append((min(right) - min(left)).total_seconds())
        values.sort()
        p95 = values[max(0, (95 * len(values) + 99) // 100 - 1)] if values else None
        durations.append({"label": label, "median": round(median(values), 2) if values else None, "p95": p95, "count": len(values)})
    user_rows = []
    for user_id, rows in users.items():
        rejected = sum(e.get("result") == "rejected" for e in rows)
        failed = sum(e.get("result") == "failure" for e in rows)
        user_rows.append({"id": user_id, "count": len(rows), "rejected": rejected, "failed": failed,
                          "attempt_count": len({str(e["bookingAttemptId"]) for e in rows if e.get("bookingAttemptId")}),
                          "recent": format_time(rows[-1].get("occurredAt")),
                          "events": [{key: str(e.get(key) or "미기록") for key in ("eventId", "eventType", "bookingAttemptId", "showId", "scheduleId", "result", "errorCode")} | {"time": format_time(e.get("occurredAt")), "label": EVENT_LABELS.get(e.get("eventType"), e.get("eventType", "미분류"))} for e in reversed(rows)]})
    user_rows.sort(key=lambda user: (user["rejected"], user["recent"]), reverse=True)
    return {"users": user_rows, "event_counts": event_counts, "failures": [(reason, count, len(failure_attempts[reason])) for reason, count in failures.most_common()],
            "stages": stages, "durations": durations, "starts": len(starts), "completed": len(completed),
            "incomplete": len(starts - completed), "conversion": round(len(completed) / len(starts) * 100, 1) if starts else None,
            "latest": format_time(events[-1].get("occurredAt")) if events else "미관측",
            "user_count": len(users), "rejected_users": sum(user["rejected"] > 0 for user in user_rows),
            "failed_users": sum(user["failed"] > 0 for user in user_rows)}
