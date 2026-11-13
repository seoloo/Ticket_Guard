"""
[홍석환] 원본 배치 처리 설정
필수값과 배치 크기·대기·쓰기 시간의 허용 범위를 검사한다.
자격 증명은 로그로 출력하지 않는다.
"""
import os
from dataclasses import dataclass


def required(name):
    value = os.environ.get(name, '')
    if not value or value.startswith('CHANGE_ME'):
        raise ValueError('Missing setting: ' + name)
    return value


def number(name, default, minimum, maximum, typ=int):
    try:
        value = typ(os.environ.get(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError()
        return value
    except ValueError:
        raise ValueError('Invalid setting: ' + name) from None


@dataclass(frozen=True)
class BatchSettings:
    count: int = 200
    seconds: float = 1.0
    bytes: int = 4194304
    write_seconds: float = 35.0
    shutdown_seconds: float = 45.0
    max_poll_ms: int = 300000

    @classmethod
    def load(cls):
        result = cls(number('RAW_BATCH_MAX_MESSAGES', 200, 1, 10000),
                     number('RAW_BATCH_WAIT_SECONDS', 1, .01, 10, float),
                     number('RAW_BATCH_MAX_BYTES', 4194304, 1, 67108864),
                     number('RAW_BATCH_WRITE_SECONDS', 35, 1, 40, float))
        return result
