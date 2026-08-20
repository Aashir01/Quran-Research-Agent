"""Transcription adapters (WP-41 support).

A scholar dictating a question in Urdu is the target case, so language is an
explicit field everywhere: a transcriber that silently assumes English will
turn ``سورہ بقرہ`` into nonsense and the user will never see why.

Transcribed text is *never* treated as scripture. It goes through the same
placeholder rendering as anything else — whatever the microphone heard, the
ayah in the output comes from the database.
"""

from __future__ import annotations

from qra.ai.adapters._http import DEFAULT_TIMEOUT, LOCAL_TIMEOUT, post, require_key
from qra.ai.base import ProviderUnavailable, TranscriptionResult
from qra.ai.registry import ModelSpec

_LOCAL_CACHE: dict[str, object] = {}


class _Base:
    def __init__(self, spec: ModelSpec, *, api_key: str | None = None, base_url: str | None = None):
        self.spec = spec
        self.api_key = api_key
        self.base_url = (base_url or spec.base_url or "").rstrip("/")
        self.timeout = LOCAL_TIMEOUT if spec.local else DEFAULT_TIMEOUT

    @property
    def name(self) -> str:
        return f"{self.spec.provider}/{self.spec.id}"

    def _check_language(self, language: str | None) -> None:
        if language and self.spec.languages and language not in self.spec.languages:
            raise ProviderUnavailable(
                f"{self.name} is not registered for {language!r} "
                f"(registry lists {', '.join(self.spec.languages)})",
                reason="policy",
                provider=self.spec.provider,
            )


class OpenAITranscription(_Base):
    def transcribe(self, audio: bytes, *, language: str | None = None,
                   filename: str = "audio.wav") -> TranscriptionResult:
        self._check_language(language)
        form = {"model": self.spec.id, "response_format": "verbose_json"}
        if language:
            form["language"] = language
        payload = post(
            f"{self.base_url}/audio/transcriptions",
            provider=self.spec.provider,
            headers={"authorization": f"Bearer {require_key(self.spec, self.api_key)}"},
            data=form,
            files={"file": (filename, audio)},
            timeout=self.timeout,
        )
        return TranscriptionResult(
            text=payload.get("text", ""),
            language=payload.get("language", language or ""),
            model=self.spec.id,
            provider=self.spec.provider,
            segments=payload.get("segments", []),
            duration_seconds=float(payload.get("duration", 0.0)),
        )


class DeepgramTranscription(_Base):
    def transcribe(self, audio: bytes, *, language: str | None = None,
                   filename: str = "audio.wav") -> TranscriptionResult:
        self._check_language(language)
        params = {"model": self.spec.id, "smart_format": "true"}
        if language:
            params["language"] = language
        payload = post(
            f"{self.base_url}/listen",
            provider=self.spec.provider,
            headers={
                "authorization": f"Token {require_key(self.spec, self.api_key)}",
                "content-type": "application/octet-stream",
            },
            data=audio,
            params=params,
            timeout=self.timeout,
        )
        channels = payload.get("results", {}).get("channels", [])
        alternatives = channels[0].get("alternatives", []) if channels else []
        best = alternatives[0] if alternatives else {}
        return TranscriptionResult(
            text=best.get("transcript", ""),
            language=language or "",
            model=self.spec.id,
            provider=self.spec.provider,
            segments=best.get("words", []),
            duration_seconds=float(payload.get("metadata", {}).get("duration", 0.0)),
        )


class ElevenLabsTranscription(_Base):
    def transcribe(self, audio: bytes, *, language: str | None = None,
                   filename: str = "audio.wav") -> TranscriptionResult:
        self._check_language(language)
        form = {"model_id": self.spec.id}
        if language:
            form["language_code"] = language
        payload = post(
            f"{self.base_url}/speech-to-text",
            provider=self.spec.provider,
            headers={"xi-api-key": require_key(self.spec, self.api_key)},
            data=form,
            files={"file": (filename, audio)},
            timeout=self.timeout,
        )
        return TranscriptionResult(
            text=payload.get("text", ""),
            language=payload.get("language_code", language or ""),
            model=self.spec.id,
            provider=self.spec.provider,
            segments=payload.get("words", []),
        )


class _LocalWhisper(_Base):
    """Shared bookkeeping for the two local Whisper paths."""

    def _write_temp(self, audio: bytes, filename: str) -> str:
        import tempfile
        from pathlib import Path

        suffix = Path(filename).suffix or ".wav"
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        handle.write(audio)
        handle.close()
        return handle.name


class WhisperTranscription(_LocalWhisper):
    """openai-whisper, running on this machine. Nothing leaves the box — which
    is the point when the audio is an unpublished lecture."""

    def _model(self):
        cached = _LOCAL_CACHE.get(f"whisper:{self.spec.id}")
        if cached is not None:
            return cached
        try:
            import whisper  # noqa: PLC0415
        except ImportError as exc:
            raise ProviderUnavailable(
                "whisper_local needs openai-whisper (pip install openai-whisper)",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        model = whisper.load_model(self.spec.id)
        _LOCAL_CACHE[f"whisper:{self.spec.id}"] = model
        return model

    def transcribe(self, audio: bytes, *, language: str | None = None,
                   filename: str = "audio.wav") -> TranscriptionResult:
        self._check_language(language)
        import os

        path = self._write_temp(audio, filename)
        try:
            result = self._model().transcribe(path, language=language)
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(
                f"local whisper failed: {exc}", reason="unavailable", provider=self.spec.provider
            ) from exc
        finally:
            os.unlink(path)
        return TranscriptionResult(
            text=result.get("text", "").strip(),
            language=result.get("language", language or ""),
            model=self.spec.id,
            provider=self.spec.provider,
            segments=result.get("segments", []),
        )


class FasterWhisperTranscription(_LocalWhisper):
    """Same model, CTranslate2 runtime. Several times faster on CPU."""

    def _model(self):
        cached = _LOCAL_CACHE.get(f"faster:{self.spec.id}")
        if cached is not None:
            return cached
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except ImportError as exc:
            raise ProviderUnavailable(
                "faster_whisper needs faster-whisper (pip install faster-whisper)",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        model = WhisperModel(self.spec.id, compute_type="int8")
        _LOCAL_CACHE[f"faster:{self.spec.id}"] = model
        return model

    def transcribe(self, audio: bytes, *, language: str | None = None,
                   filename: str = "audio.wav") -> TranscriptionResult:
        self._check_language(language)
        import os

        path = self._write_temp(audio, filename)
        try:
            segments, info = self._model().transcribe(path, language=language)
            rows = [
                {"start": s.start, "end": s.end, "text": s.text} for s in segments
            ]
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(
                f"faster-whisper failed: {exc}", reason="unavailable", provider=self.spec.provider
            ) from exc
        finally:
            os.unlink(path)
        return TranscriptionResult(
            text="".join(r["text"] for r in rows).strip(),
            language=getattr(info, "language", language or ""),
            model=self.spec.id,
            provider=self.spec.provider,
            segments=rows,
            duration_seconds=float(getattr(info, "duration", 0.0)),
        )


TRANSCRIPTION_ADAPTERS: dict[str, type[_Base]] = {
    "openai": OpenAITranscription,
    "deepgram": DeepgramTranscription,
    "elevenlabs": ElevenLabsTranscription,
    "whisper": WhisperTranscription,
    "faster_whisper": FasterWhisperTranscription,
}
