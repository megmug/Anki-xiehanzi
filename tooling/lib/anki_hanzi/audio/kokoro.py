"""Kokoro audio backend."""

from __future__ import annotations

import inspect
from typing import Any

from anki_hanzi.audio.api import AudioBackend, AudioJob, AudioVoice


KOKORO_VOICES = (
    AudioVoice("primary", "zf_xiaoxiao", "Xiaoxiao"),
    AudioVoice("secondary", "zm_yunjian", "Yunjian"),
)


def _is_audio_input_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "normal_pinyin" in message
        or "Final couldn't be detected" in message
    )


def _torch_cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _resolve_kokoro_device() -> str:
    return "cuda" if _torch_cuda_available() else "cpu"


def _create_kokoro_pipeline(KPipeline: type, device: str) -> Any:
    kwargs: dict[str, Any] = {"lang_code": "z"}
    try:
        parameters = inspect.signature(KPipeline).parameters
    except (TypeError, ValueError):
        parameters = {}
    supports_device = "device" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if supports_device:
        kwargs["device"] = device
    elif device != "cpu":
        print("  Kokoro KPipeline does not expose device=; using package default", flush=True)
    return KPipeline(**kwargs)


class KokoroBackend(AudioBackend):
    engine = "kokoro"
    voices = KOKORO_VOICES

    def __init__(self) -> None:
        self.device = _resolve_kokoro_device()
        self._fallback_to_cpu = self.device != "cpu"
        self._pipeline: Any | None = None
        self._kpipeline_type: type | None = None

    def setup(self) -> None:
        from kokoro import KPipeline

        self._kpipeline_type = KPipeline
        try:
            self._pipeline = _create_kokoro_pipeline(KPipeline, self.device)
        except Exception:
            if self.device != "cpu":
                print("  Kokoro audio device: failed to initialize cuda; falling back to cpu", flush=True)
                self.device = "cpu"
                self._fallback_to_cpu = False
                self._pipeline = _create_kokoro_pipeline(KPipeline, self.device)
            else:
                raise
        print(f"  Kokoro audio device: {self.device}", flush=True)

    def synthesize(self, job: AudioJob) -> None:
        import numpy as np
        import soundfile as sf

        if self._pipeline is None:
            self.setup()

        results = self._run_pipeline(job)
        segments = [result.audio for result in results if result.audio is not None]
        if not segments:
            raise RuntimeError("Kokoro produced no audio")

        audio = np.concatenate(segments)
        sf.write(job.output_path, audio, 24000)

    def _run_pipeline(self, job: AudioJob) -> list[Any]:
        assert self._pipeline is not None
        try:
            return list(self._pipeline(job.text, voice=job.voice.provider_id, speed=1.0))
        except Exception as exc:
            if _is_audio_input_error(exc):
                raise
            if not self._fallback_to_cpu:
                raise
            print(
                "  Kokoro audio device: cuda generation failed; "
                f"word={job.text!r} slot={job.voice.slot} voice={job.voice.provider_id!r}; "
                f"falling back to cpu ({exc})",
                flush=True,
            )
            self._fallback_to_cpu = False
            self.device = "cpu"
            assert self._kpipeline_type is not None
            self._pipeline = _create_kokoro_pipeline(self._kpipeline_type, self.device)
            return list(self._pipeline(job.text, voice=job.voice.provider_id, speed=1.0))
