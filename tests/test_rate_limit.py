from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from starlette.requests import Request

from carvaluator_scraper.rate_limit import (
    RateLimitPolicy,
    RateLimitSettings,
    SlidingWindowRateLimiter,
    get_client_ip,
    rate_limit_headers,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SlidingWindowRateLimiterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.limiter = SlidingWindowRateLimiter(clock=self.clock)
        self.policy = RateLimitPolicy(requests=2, window_seconds=60)

    def test_blocks_after_limit_and_recovers_after_window(self) -> None:
        first = self.limiter.check(scope="predict", key="7", policy=self.policy)
        second = self.limiter.check(scope="predict", key="7", policy=self.policy)
        blocked = self.limiter.check(scope="predict", key="7", policy=self.policy)

        self.assertTrue(first.allowed)
        self.assertEqual(first.remaining, 1)
        self.assertTrue(second.allowed)
        self.assertEqual(second.remaining, 0)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.retry_after_seconds, 60)

        self.clock.advance(60)
        recovered = self.limiter.check(scope="predict", key="7", policy=self.policy)
        self.assertTrue(recovered.allowed)
        self.assertEqual(recovered.remaining, 1)

    def test_scopes_and_keys_are_independent(self) -> None:
        self.limiter.check(scope="login", key="127.0.0.1", policy=self.policy)
        self.limiter.check(scope="login", key="127.0.0.1", policy=self.policy)

        other_ip = self.limiter.check(scope="login", key="127.0.0.2", policy=self.policy)
        other_scope = self.limiter.check(scope="register", key="127.0.0.1", policy=self.policy)

        self.assertTrue(other_ip.allowed)
        self.assertTrue(other_scope.allowed)

    def test_rejection_headers_include_retry_after(self) -> None:
        self.limiter.check(scope="predict", key="7", policy=self.policy)
        self.limiter.check(scope="predict", key="7", policy=self.policy)
        decision = self.limiter.check(scope="predict", key="7", policy=self.policy)

        headers = rate_limit_headers(decision)
        self.assertEqual(headers["X-RateLimit-Limit"], "2")
        self.assertEqual(headers["X-RateLimit-Remaining"], "0")
        self.assertEqual(headers["Retry-After"], "60")


class RateLimitSettingsTests(unittest.TestCase):
    def test_defaults_match_demo_policy(self) -> None:
        names = [name for name in os.environ if name.startswith("CARVALUATOR_RATE_LIMIT_")]
        with patch.dict(os.environ, {}, clear=False):
            for name in names:
                os.environ.pop(name, None)
            settings = RateLimitSettings.from_env()

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.global_policy, RateLimitPolicy(60, 60))
        self.assertEqual(settings.login_policy, RateLimitPolicy(10, 900))
        self.assertEqual(settings.register_policy, RateLimitPolicy(3, 3600))
        self.assertEqual(settings.predict_policy, RateLimitPolicy(5, 60))

    def test_environment_overrides_are_applied(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CARVALUATOR_RATE_LIMIT_PREDICT_REQUESTS": "8",
                "CARVALUATOR_RATE_LIMIT_PREDICT_WINDOW_SECONDS": "120",
            },
        ):
            settings = RateLimitSettings.from_env()

        self.assertEqual(settings.predict_policy, RateLimitPolicy(8, 120))


class ClientIpTests(unittest.TestCase):
    def test_proxy_header_is_used_only_when_trusted(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [(b"x-forwarded-for", b"203.0.113.10, 10.0.0.2")],
            "client": ("127.0.0.1", 12345),
        }
        request = Request(scope)

        self.assertEqual(get_client_ip(request, trust_proxy_headers=True), "203.0.113.10")
        self.assertEqual(get_client_ip(request, trust_proxy_headers=False), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
