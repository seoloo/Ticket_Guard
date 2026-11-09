"""이벤트 토픽 직접 주입 · 계약 시험 전용 · 시험 환경에서만 켬 (TICKET_GUARD_QA_IS_KAFKA_CONTRACT_INJECTION_ENABLED)"""
QA_PRODUCER_CLIENT_ID = "ticketguard-qa-contract"
DELIVERY_TIMEOUT_SEC = 10.0


class EventInjectionError(RuntimeError):
    pass


class KafkaEventInjector:
    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic

    def inject_messages(self, messages: list[tuple[str | None, bytes]]) -> list[tuple[int, int]]:
        """전송 순서대로 (파티션, 오프셋) · 하나라도 실패하면 오류"""
        from confluent_kafka import Producer  # 실제 대상에서만 · 단위 테스트는 설치 불필요

        producer = Producer({"bootstrap.servers": self.bootstrap_servers, "client.id": QA_PRODUCER_CLIENT_ID,
                             "enable.idempotence": False, "allow.auto.create.topics": False})
        positions: list[tuple[int, int] | None] = [None] * len(messages)
        errors: list[str] = []

        def record_delivery(index: int):
            def on_delivery(error, message) -> None:
                if error is not None:
                    errors.append(str(error))
                else:
                    positions[index] = (message.partition(), message.offset())
            return on_delivery

        for index, (key, value) in enumerate(messages):
            producer.produce(self.topic, key=key, value=value, on_delivery=record_delivery(index))
        producer.flush(DELIVERY_TIMEOUT_SEC)
        if errors or any(position is None for position in positions):
            raise EventInjectionError(f"토픽 주입 실패 · {self.topic} · {errors[:1] or '전달 확인 시간 초과'}")
        return [position for position in positions if position is not None]
