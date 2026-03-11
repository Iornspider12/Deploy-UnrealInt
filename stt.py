import websockets
import asyncio
import msgpack
import sounddevice as sd
import numpy as np
from typing import Any
import tqdm
from unmute.kyutai_constants import SAMPLES_PER_FRAME
from query import Query

from unmute.stt.speech_to_text import (
    SpeechToText,
    STTMarkerMessage,
    STTWordMessage,
    STTStepMessage
)

SAMPLE_RATE = 24000
BLOCK_SIZE = 2048
PAUSE_PREDICTION_HEAD_INDEX = 3
DEBOUNCE_COUNT = 3

# Backoff schedule for reconnection attempts (seconds)
_RECONNECT_BACKOFFS = [2, 5, 10, 20, 30, 60]


class STT:

    def __init__(self, endpoint, show_vad):

        self.endpoint = endpoint
        self.show_vad = show_vad

        # Asynchronous Queues
        self.inpq = asyncio.Queue()
        self.outq = asyncio.Queue()

    def start(self):
        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            print("Interrupted by User")

    async def run(self):

        def audio_input(indata: np.ndarray, frames: int, time: Any, status: sd.CallbackFlags):
            mono_audio = indata[:, 0]
            self.inpq.put_nowait(mono_audio.copy())

        with sd.InputStream(callback=audio_input, blocksize=BLOCK_SIZE, samplerate=SAMPLE_RATE):
            pipeline_task = asyncio.create_task(
                self.pipeline(self.inpq, self.outq)
            )
            stdout_player_task = asyncio.create_task(
                self.print_queue(self.outq)
            )

            await asyncio.gather(
                pipeline_task,
                stdout_player_task
            )

    async def pipeline(self, inpq: asyncio.Queue, outq: asyncio.Queue):
        """
        Speech to Text pipeline — runs indefinitely with automatic reconnect.
        Retries connection with exponential backoff on failure.
        """
        attempt = 0

        def make_receive_loop(stt_inst):
            async def receive_loop():
                try:
                    delay = None
                    buffer = []
                    speech_started = False
                    debounce = 0
                    _step_log_count = 0
                    async for msg in stt_inst:
                        if isinstance(msg, STTStepMessage) and self.show_vad:
                            if _step_log_count < 5:
                                # print(f"[STT] step prs={msg.prs} (len={len(msg.prs)})")
                                _step_log_count += 1
                            if len(msg.prs) > PAUSE_PREDICTION_HEAD_INDEX:
                                pause_prediction = msg.prs[PAUSE_PREDICTION_HEAD_INDEX]
                                if pause_prediction > 0.4 and speech_started:
                                    debounce += 1
                                    if debounce > DEBOUNCE_COUNT:
                                        speech_started = False
                                        debounce = 0
                                        if buffer:
                                            full_text = " ".join(buffer).strip()
                                            print(f"[STT] voice query (flush): {full_text!r}")
                                            await outq.put(Query(sys='Keep response as concise as possible.', human=full_text))
                                            buffer.clear()

                        elif isinstance(msg, STTWordMessage):
                            buffer.append(msg.text)
                            speech_started = True
                            debounce = 0
                            print(f"[STT] word: {msg.text!r}")
                        elif isinstance(msg, STTMarkerMessage):
                            marker_time = msg.id / 1000
                            time_now = asyncio.get_event_loop().time()
                            delay = time_now - marker_time
                except Exception as e:
                    print(f"[STT] receive_loop encountered: {e}")
            return receive_loop

        while True:
            # --- Connect to STT server with backoff ---
            stt = SpeechToText(stt_instance=self.endpoint)
            try:
                await stt.start_up()
                attempt = 0  # reset on success
                print(f"[STT] Connected to {self.endpoint}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                wait = _RECONNECT_BACKOFFS[min(attempt, len(_RECONNECT_BACKOFFS) - 1)]
                print(f"Voice unavailable: STT connection failed to {self.endpoint}: {e}")
                print(f"[STT] Retrying in {wait}s... (attempt {attempt + 1})")
                attempt += 1
                # Drain stale audio from queue during backoff so we don't send old audio on reconnect
                deadline = asyncio.get_event_loop().time() + wait
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        await asyncio.wait_for(inpq.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        pass
                    except asyncio.CancelledError:
                        raise
                continue

            # --- Connected: run send/receive loops until server disconnects ---
            audio_buffer = np.zeros((0,), dtype=np.float32)
            receive_task = asyncio.create_task(make_receive_loop(stt)())

            def _on_receive_done(t: asyncio.Task):
                if not t.cancelled() and t.exception() is not None:
                    import traceback
                    print(f"[STT] receive_loop crashed: {t.exception()}")
                    traceback.print_exception(type(t.exception()), t.exception(), t.exception().__traceback__)
            receive_task.add_done_callback(_on_receive_done)

            try:
                while True:
                    # If the STT server dropped us, reconnect
                    if receive_task.done():
                        print("[STT] Receive loop ended - will reconnect")
                        break

                    try:
                        audio_chunk = await asyncio.wait_for(inpq.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        raise

                    audio_buffer = np.append(audio_buffer, audio_chunk)
                    while audio_buffer.shape[0] >= SAMPLES_PER_FRAME:
                        chunk = audio_buffer[:SAMPLES_PER_FRAME]
                        audio_buffer = audio_buffer[SAMPLES_PER_FRAME:]
                        try:
                            await stt.send_marker(int(asyncio.get_event_loop().time() * 1000))
                            await stt.send_audio(chunk)
                        except Exception as send_err:
                            print(f"[STT] send error: {send_err} - will reconnect")
                            break
                    else:
                        continue
                    break  # inner send error — break out to reconnect

            except asyncio.CancelledError:
                receive_task.cancel()
                try:
                    await receive_task
                except (asyncio.CancelledError, Exception):
                    pass
                raise
            finally:
                if not receive_task.done():
                    receive_task.cancel()
                    try:
                        await receive_task
                    except (asyncio.CancelledError, Exception):
                        pass

            # Small delay before reconnect attempt
            await asyncio.sleep(1)

    async def print_queue(self, queue: asyncio.Queue):
        while True:
            item = await queue.get()
            if isinstance(item, Query):
                print("\n", item.human)


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv
    load_dotenv()
    voice_ip = os.getenv('VOICE_IP', '3.142.197.83')

    # Init Obj
    stt = STT(endpoint=f"ws://{voice_ip}:8080", show_vad=True)
    stt.start()
