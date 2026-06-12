from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Request


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    requests: int
    window_seconds: int

    @property
    def enabled(self) -> bool:
        return self.requests > 0 and self.window_seconds > 0

    def to_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "window_seconds": self.window_seconds,
        }


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class RateLimitSettings:
    enabled: bool
    trust_proxy_headers: bool
    global_policy: RateLimitPolicy
    login_policy: RateLimitPolicy
    register_policy: RateLimitPolicy
    predict_policy: RateLimitPolicy

    @classmethod
    def from_env(cls) -> RateLimitSettings:
        return cls(
            enabled=_env_bool("CARVALUATOR_RATE_LIMIT_ENABLED", True),
            trust_proxy_headers=_env_bool("CARVALUATOR_TRUST_PROXY_HEADERS", False),
            global_policy=_policy_from_env("GLOBAL", requests=60, window_seconds=60),
            login_policy=_policy_from_env("LOGIN", requests=10, window_seconds=15 * 60),
            register_policy=_policy_from_env("REGISTER", requests=3, window_seconds=60 * 60),
            predict_policy=_policy_from_env("PREDICT", requests=5, window_seconds=60),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "global_per_ip": self.global_policy.to_dict(),
            "login_per_ip": self.login_policy.to_dict(),
            "register_per_ip": self.register_policy.to_dict(),
            "predict_per_account": self.predict_policy.to_dict(),
        }


class SlidingWindowRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[tuple[str, str, int], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._checks = 0

    def check(
        self,
        *,
        scope: str,
        key: str,
        policy: RateLimitPolicy,
    ) -> RateLimitDecision:
        if not policy.enabled:
            return RateLimitDecision(
                allowed=True,
                limit=policy.requests,
                remaining=max(policy.requests, 0),
                retry_after_seconds=0,
            )

        now = self._clock()
        bucket_key = (scope, key, policy.window_seconds)
        cutoff = now - policy.window_seconds

        with self._lock:
            bucket = self._events[bucket_key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= policy.requests:
                retry_after = max(1, math.ceil(policy.window_seconds - (now - bucket[0])))
                decision = RateLimitDecision(
                    allowed=False,
                    limit=policy.requests,
                    remaining=0,
                    retry_after_seconds=retry_after,
                )
            else:
                bucket.append(now)
                decision = RateLimitDecision(
                    allowed=True,
                    limit=policy.requests,
                    remaining=max(policy.requests - len(bucket), 0),
                    retry_after_seconds=0,
                )

            self._checks += 1
            if self._checks % 256 == 0:
                self._remove_expired_buckets(now)

        return decision

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._checks = 0

    def _remove_expired_buckets(self, now: float) -> None:
        expired_keys = [
            bucket_key
            for bucket_key, events in self._events.items()
            if not events or events[-1] <= now - bucket_key[2]
        ]
        for bucket_key in expired_keys:
            self._events.pop(bucket_key, None)


def get_client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_headers(
    decision: RateLimitDecision,
    *,
    prefix: str = "X-RateLimit",
) -> dict[str, str]:
    headers = {
        f"{prefix}-Limit": str(decision.limit),
        f"{prefix}-Remaining": str(decision.remaining),
    }
    if not decision.allowed:
        headers[f"{prefix}-Reset"] = str(decision.retry_after_seconds)
        headers["Retry-After"] = str(decision.retry_after_seconds)
    return headers


def _policy_from_env(name: str, *, requests: int, window_seconds: int) -> RateLimitPolicy:
    return RateLimitPolicy(
        requests=_env_non_negative_int(f"CARVALUATOR_RATE_LIMIT_{name}_REQUESTS", requests),
        window_seconds=_env_positive_int(
            f"CARVALUATOR_RATE_LIMIT_{name}_WINDOW_SECONDS",
            window_seconds,
        ),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_non_negative_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), 0)
    except ValueError:
        return default


def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
