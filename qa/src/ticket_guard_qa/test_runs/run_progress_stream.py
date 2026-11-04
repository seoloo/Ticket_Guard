"""03 화면 진행 메시지 · 메모리 보관 · 화면은 마지막 번호 이후만 읽음"""
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from ticket_guard_qa.domain.models import ActorProgress, LiveMetrics


@dataclass(frozen=True)
class ProgressMessage:
    sequence_number: int
    text: str
    is_finished: bool = False
    elapsed_sec: float | None = None
    total_sec: float | None = None
    suite_name: str | None = None
    live_metrics: LiveMetrics | None = None
    final_status: str | None = None
    actor_progress: ActorProgress | None = None  # B3 종류별 진행

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["live_metrics"] = asdict(self.live_metrics) if self.live_metrics else None
        return payload


class RunProgressStream:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages_by_run_id: dict[str, list[ProgressMessage]] = defaultdict(list)

    def publish(self, run_id: str, text: str, **fields: Any) -> None:
        with self._lock:
            messages = self._messages_by_run_id[run_id]
            messages.append(ProgressMessage(len(messages) + 1, text, **fields))

    def read_after(self, run_id: str, last_sequence_number: int) -> list[ProgressMessage]:
        with self._lock:
            return [m for m in self._messages_by_run_id[run_id] if m.sequence_number > last_sequence_number]
