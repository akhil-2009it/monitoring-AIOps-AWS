"""Reuses the same async invoker pattern as the mlops/ project — async + circuit
breaker so a slow detector doesn't drag the API past its SLO.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    cooldown_sec: int = 30
    consecutive_failures: int = 0
    open_until: float = 0.0

    def is_open(self) -> bool:
        return time.time() < self.open_until

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.open_until = 0.0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.open_until = time.time() + self.cooldown_sec


class SageMakerEndpointInvoker:
    def __init__(self, endpoint_name: str, region: str, timeout_sec: float = 0.20) -> None:
        self._endpoint = endpoint_name
        self._region = region
        self._timeout = timeout_sec
        self._cb = CircuitBreaker()
        self._client_ctx = None
        self._client = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self):
        if self._client is not None:
            return
        async with self._lock:
            if self._client is not None:
                return
            from aiobotocore.session import get_session
            self._client_ctx = get_session().create_client("sagemaker-runtime", region_name=self._region)
            self._client = await self._client_ctx.__aenter__()

    async def invoke(self, payload: dict) -> dict | None:
        if self._cb.is_open():
            return None
        try:
            await self._ensure_client()
            resp = await asyncio.wait_for(
                self._client.invoke_endpoint(
                    EndpointName=self._endpoint,
                    ContentType="application/json",
                    Body=json.dumps(payload),
                ),
                timeout=self._timeout,
            )
            body = await resp["Body"].read()
            self._cb.record_success()
            return json.loads(body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Endpoint %s call failed: %s", self._endpoint, exc)
            self._cb.record_failure()
            return None

    async def close(self) -> None:
        if self._client_ctx is not None:
            try:
                await self._client_ctx.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
