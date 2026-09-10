"""Deepgram Flux — streaming STT with model-integrated turn detection (ADR-002).

Protocol: wss://api.deepgram.com/v2/listen
  https://developers.deepgram.com/reference/speech-to-text/listen-flux
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from providers.base import SttEvent, TurnEvent, Word

log = logging.getLogger("intervueos.stt")

_URL = "wss://api.deepgram.com/v2/listen"

_EVENTS = {
    "StartOfTurn": TurnEvent.START_OF_TURN,
    "Update": TurnEvent.UPDATE,
    "EagerEndOfTurn": TurnEvent.EAGER_END_OF_TURN,
    "TurnResumed": TurnEvent.TURN_RESUMED,
    "EndOfTurn": TurnEvent.END_OF_TURN,
}


class DeepgramFluxStt:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "flux-general-en",
        sample_rate: int = 16000,
        eot_threshold: float = 0.7,
        eager_eot_threshold: float = 0.5,
        eot_timeout_ms: int = 4000,
    ) -> None:
        self.sample_rate = sample_rate
        self._api_key = api_key
        params = {
            "model": model,
            "encoding": "linear16",
            "sample_rate": str(sample_rate),
            "eot_threshold": f"{eot_threshold}",
            "eot_timeout_ms": str(eot_timeout_ms),
        }
        if eager_eot_threshold:
            params["eager_eot_threshold"] = f"{eager_eot_threshold}"
        self._url = f"{_URL}?{urlencode(params)}"
        self._ws: ClientConnection | None = None

    async def __aenter__(self) -> "DeepgramFluxStt":
        self._ws = await connect(
            self._url,
            additional_headers={"Authorization": f"Token {self._api_key}"},
            max_size=None,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def send_audio(self, pcm16: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("STT stream is not open")
        await self._ws.send(pcm16)

    async def events(self) -> AsyncIterator[SttEvent]:
        if self._ws is None:
            raise RuntimeError("STT stream is not open")
        async for raw in self._ws:
            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("unparseable STT frame")
                continue

            kind = msg.get("type")
            if kind == "Connected":
                log.info("flux connected request_id=%s", msg.get("request_id"))
                continue
            if kind == "Error":
                log.error("flux error: %s", msg)
                continue
            if kind != "TurnInfo":
                continue

            event = _EVENTS.get(msg.get("event", ""))
            if event is None:
                continue

            yield SttEvent(
                event=event,
                transcript=msg.get("transcript", "") or "",
                turn_index=msg.get("turn_index", 0),
                words=tuple(
                    Word(
                        word=w.get("word", ""),
                        start=w.get("start", 0.0),
                        end=w.get("end", 0.0),
                        confidence=w.get("confidence", 0.0),
                    )
                    for w in msg.get("words", []) or ()
                ),
                end_of_turn_confidence=msg.get("end_of_turn_confidence", 0.0) or 0.0,
                audio_window_start=msg.get("audio_window_start", 0.0) or 0.0,
                audio_window_end=msg.get("audio_window_end", 0.0) or 0.0,
            )
