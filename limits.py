"""
Message limits for the "Say hello" box.

Per visitor: at most MESSAGES_PER_VISITOR per 24 hours, at least MESSAGE_COOLDOWN_SECONDS apart.
Site-wide: at most MESSAGES_PER_DAY_TOTAL per 24 hours (protects the owner's daily email quota).

A visitor is recognised by a hash of their IP address, kept only in server memory for counting:
it is never logged or sent anywhere. Counts survive page refreshes but reset if the server restarts
(fine for a single-instance free host; several instances would need a shared store).
"""

import hashlib
import time
from collections import deque

from config import MESSAGE_COOLDOWN_SECONDS, MESSAGES_PER_DAY_TOTAL, MESSAGES_PER_VISITOR

DAY_SECONDS = 24 * 60 * 60

# Hosting platforms put the visitor's real IP in one of these headers (the app sits behind a proxy).
IP_HEADERS = ("cf-connecting-ip", "true-client-ip", "x-real-ip", "x-forwarded-for")


def visitor_key(request) -> str:
    """A short, one-way key for counting one visitor's messages."""
    ip = ""
    if request is not None:
        for name in IP_HEADERS:
            value = request.headers.get(name)
            if value:
                ip = value.split(",")[0].strip()   # x-forwarded-for can list several hops; the first is the visitor
                break
        if not ip and request.client:
            ip = request.client.host or ""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


class MessageLimiter:

    def __init__(self):
        self._by_visitor: dict[str, deque] = {}
        self._all: deque = deque()

    @staticmethod
    def _prune(times: deque) -> deque:
        cutoff = time.time() - DAY_SECONDS
        while times and times[0] < cutoff:
            times.popleft()
        return times

    def remaining(self, key: str) -> int:
        return max(0, MESSAGES_PER_VISITOR - len(self._prune(self._by_visitor.get(key, deque()))))

    def wait_seconds(self, key: str) -> int:
        times = self._by_visitor.get(key)
        if not times:
            return 0
        return max(0, int(MESSAGE_COOLDOWN_SECONDS - (time.time() - times[-1]) + 0.999))

    def site_is_full(self) -> bool:
        return len(self._prune(self._all)) >= MESSAGES_PER_DAY_TOTAL

    def record(self, key: str) -> None:
        """Count a message. Called *before* sending, so two quick clicks can't both slip through."""
        now = time.time()
        if len(self._by_visitor) > 10_000:   # forget visitors with nothing in the last 24h (bounded memory)
            self._by_visitor = {k: times for k, times in self._by_visitor.items() if self._prune(times)}
        self._by_visitor.setdefault(key, deque()).append(now)
        self._all.append(now)

    def undo(self, key: str) -> None:
        """The message couldn't be delivered: give the visitor their attempt back."""
        if self._by_visitor.get(key):
            self._by_visitor[key].pop()
        if self._all:
            self._all.pop()


limiter = MessageLimiter()
