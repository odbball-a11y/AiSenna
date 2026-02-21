
import os
import time
import threading
import logging
from collections import deque

log = logging.getLogger(__name__)


try:
    import win32com.client  # SAPI on Windows
    _HAS_SAPI = True
except Exception:
    _HAS_SAPI = False

try:
    import pyttsx3
    _HAS_PYTTSX3 = True
except Exception:
    _HAS_PYTTSX3 = False



TTS_RATE = 200  # or whatever value you used in v3


class Speaker:
    def __init__(self, rate: int = TTS_RATE, volume: int = 150):
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._rate = rate
        self._volume = max(0, min(200, volume))
        self._volume_changed = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, val: int):
        self._volume = max(0, min(200, val))

    def say(self, text: str):
        with self._lock:
            self._queue.append(text)

    def say_priority(self, text: str):
        with self._lock:
            self._queue.appendleft(text)

    def clear(self):
        with self._lock:
            self._queue.clear()

    def stop(self):
        self._stop.set()

    def _run(self):
        use_sapi = _HAS_SAPI
        sapi_voice = None
        engine = None

        if use_sapi:
            try:
                import pythoncom
                pythoncom.CoInitialize()
                sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
                sapi_voice.Rate = max(-10, min(10, (self._rate - 175) // 20))
                sapi_voice.Volume = 100
                log.info("TTS: SAPI COM initialised (rate=%d)", sapi_voice.Rate)
            except Exception as e:
                log.warning("SAPI init failed: %s — falling back to pyttsx3", e)
                use_sapi = False

        if not use_sapi and _HAS_PYTTSX3:
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", self._rate)
                engine.setProperty("volume", 1.0)
                log.info("TTS: pyttsx3 initialised")
            except Exception as e:
                log.error("pyttsx3 init failed: %s", e)
                engine = None

        while not self._stop.is_set():
            text = None
            with self._lock:
                if self._queue:
                    text = self._queue.popleft()

            if text:
                log.info("🔊 %s", text)
                try:
                    if use_sapi and self._volume > 100:
                        import io, wave, struct
                        tmp_path = os.path.join(
                            os.environ.get("TEMP", "."), "_senna_tts.wav"
                        )
                        stream = win32com.client.Dispatch("SAPI.SpFileStream")
                        stream.Open(tmp_path, 3, False)
                        sapi_voice.AudioOutputStream = stream
                        sapi_voice.Speak(text, 0)
                        stream.Close()
                        sapi_voice.AudioOutputStream = None

                        with wave.open(tmp_path, "rb") as wf:
                            params = wf.getparams()
                            frames = wf.readframes(params.nframes)

                        gain = self._volume / 100.0
                        fmt = f"<{params.nframes * params.nchannels}h"
                        samples = list(struct.unpack(fmt, frames))
                        amplified = [max(-32767, min(32767, int(s * gain))) for s in samples]
                        amp_bytes = struct.pack(fmt, *amplified)

                        amp_buf = io.BytesIO()
                        with wave.open(amp_buf, "wb") as wout:
                            wout.setparams(params)
                            wout.writeframes(amp_bytes)

                        import winsound
                        winsound.PlaySound(
                            amp_buf.getvalue(),
                            winsound.SND_MEMORY | winsound.SND_NOSTOP,
                        )
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass

                    elif use_sapi:
                        sapi_voice.Volume = self._volume
                        sapi_voice.Speak(text, 0)
                    else:
                        if engine:
                            engine.say(text)
                            engine.runAndWait()

                except Exception as e:
                    log.warning("TTS error: %s", e)
            else:
                time.sleep(0.05)


# ═══════════════════════════════════════════════════════════════════════════
# ENHANCED COACHING GENERATOR - NEW
# ═══════════════════════════════════════════════════════════════════════════
