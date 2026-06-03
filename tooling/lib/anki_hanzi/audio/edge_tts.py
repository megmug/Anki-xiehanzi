"""edge-tts audio backend."""

from __future__ import annotations

import time

from anki_hanzi.audio.api import AudioBackend, AudioJob, AudioVoice
from anki_hanzi.deck import common


EDGE_TTS_VOICES = (
    AudioVoice("primary", "zh-CN-XiaoxiaoNeural", "Xiaoxiao"),
    AudioVoice("secondary", "zh-CN-YunjianNeural", "Yunjian"),
)


class EdgeTtsBackend(AudioBackend):
    engine = "edge_tts"
    voices = EDGE_TTS_VOICES

    def setup(self) -> None:
        import edge_tts  # noqa: F401

    def synthesize(self, job: AudioJob) -> None:
        import edge_tts

        max_retries = 3
        for attempt in range(max_retries):
            try:
                communicate = edge_tts.Communicate(job.text, job.voice.provider_id)
                communicate.save_sync(str(job.output_path))
                if job.output_path.exists() and job.output_path.stat().st_size > 0:
                    return
                common.remove_failed_audio_output(job.output_path)
                raise RuntimeError("edge-tts produced no audio data")
            except Exception as exc:
                common.remove_failed_audio_output(job.output_path)
                if attempt >= max_retries - 1:
                    raise
                delay = 2 ** (attempt + 1)
                print(
                    f"    Retry {attempt + 1}/{max_retries} for "
                    f"{job.text!r} ({job.voice.provider_id}) after {delay}s: {exc}",
                    flush=True,
                )
                time.sleep(delay)
