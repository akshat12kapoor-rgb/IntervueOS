"""Deepgram Aura-2 — streaming TTS (ADR-003).

Protocol: wss://api.deepgram.com/v1/speak
  https://developers.deepgram.com/reference/text-to-speech-api/speak-streaming

Barge-in note: after we send `Clear`, audio synthesised before the clear may
still be in flight on the socket. Deepgram acknowledges with `Cleared`, so we
drop every binary frame between the two. Without this the candidate hears a
fragment of the question they just interrupted.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

log = logging.getLogger("intervueos.tts")

_URL = "wss://api.deepgram.com/v1/speak"


class DeepgramAuraTts:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "aura-2-thalia-en",
        sample_rate: int = 24000,
    ) -> None:
        self.sample_rate = sample_rate
        self._api_key = api_key
        self._url = f"{_URL}?" + urlencode(
            {"model": model, "encoding": "linear16", "sample_rate": str(sample_rate)}
        )
        self._ws: ClientConnection | None = None
        self._dropping = False
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "DeepgramAuraTts":
        self._ws = await connect(
            self._url,
            additional_headers={"Authorization": f"Token {self._api_key}"},
            max_size=None,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "Close"}))
            except Exception:
                pass
            await self._ws.close()
            self._ws = None

    async def _send(self, payload: dict) -> None:
        if self._ws is None:
            raise RuntimeError("TTS stream is not open")
        async with self._lock:
            await self._ws.send(json.dumps(payload))

    async def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._dropping = False
        await self._send({"type": "Speak", "text": text})

    async def flush(self) -> None:
        await self._send({"type": "Flush"})

    async def clear(self) -> None:
        self._dropping = True
        await self._send({"type": "Clear"})

    async def audio(self) -> AsyncIterator[bytes]:
        if self._ws is None:
            raise RuntimeError("TTS stream is not open")
        async for raw in self._ws:
            if isinstance(raw, bytes):
                if self._dropping:
                    continue
                yield raw
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "Cleared":
                self._dropping = False
            elif kind == "Warning":
                log.warning("aura warning: %s", msg.get("description"))
            elif kind == "Error":
                log.error("aura error: %s", msg)
