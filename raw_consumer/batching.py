"""A batch ends on count, raw bytes, or elapsed time from its first record."""
import time
from records import message_bytes


class Batch:
    def __init__(self, config, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.messages, self.size, self.started = [], 0, None

    def add(self, message):
        if not self.messages:
            self.started = self.clock()
        self.messages.append(message)
        self.size += message_bytes(message)

    def would_exceed(self, message):
        return bool(self.messages) and self.size + message_bytes(message) > self.config.bytes

    def due(self):
        return bool(self.messages) and (len(self.messages) >= self.config.count or
            self.size >= self.config.bytes or self.clock() - self.started >= self.config.seconds)

    def wait(self):
        return .2 if not self.messages else max(0, min(.2, self.config.seconds - (self.clock() - self.started)))

    def clear(self):
        self.messages, self.size, self.started = [], 0, None
