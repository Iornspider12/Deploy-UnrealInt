
import asyncio
import numpy as np
import sounddevice as sd
from typing import Any
from stt import STT
from llm import LLM
from tts import TTS
from datetime import datetime
import wave
import sphn

SAMPLE_RATE = 24000
BLOCK_SIZE = 1920


class Room:

    def __init__(self, endpoint):

        self.inpq = asyncio.Queue()
        self.stt = STT(endpoint=f"ws://{endpoint}:8080", show_vad=True)
        self.sttq = asyncio.Queue()
        self.llm = LLM()
        self.ttsq = asyncio.Queue()
        self.tts = TTS(endpoint=f"ws://{endpoint}:8080",
                       voice="expresso/ex03-ex01_happy_001_channel1_334s.wav")
        self.outq = asyncio.Queue()

    def start(self):
        asyncio.run(self.run())

    async def run(self):

        def audio_input(indata: np.ndarray, frames: int, time: Any, status: sd.CallbackFlags):
            mono_audio = indata[:, 0]
            self.inpq.put_nowait(mono_audio.copy())

        with sd.InputStream(callback=audio_input, blocksize=BLOCK_SIZE, samplerate=SAMPLE_RATE):

            await self.pipeline(self.inpq, self.sttq, self.ttsq, self.outq)

    async def pipeline(self, inpq, sttq, ttsq, outq):

        stt_stage_task = asyncio.create_task(
            self.stt.pipeline(inpq, sttq)
        )
        llm_stage_task = asyncio.create_task(
            self.llm.pipeline(sttq, ttsq)
        )
        tts_stage_task = asyncio.create_task(
            self.tts.pipeline(ttsq, outq)
        )
        # play_audio_task = asyncio.create_task(
        #     self.play_queue(outq)
        # )
        # save_audio_task = asyncio.create_task(
        #     self.save_queue(outq)
        # )
        await asyncio.gather(
            # inp_queue_task,
            stt_stage_task,
            llm_stage_task,
            tts_stage_task,
            # play_audio_task
            # save_audio_task
        )

    async def print_queue(self, queue: asyncio.Queue):
        while True:
            item = await queue.get()
            print(item)

    async def play_queue(self, outq: asyncio.Queue):
        """Continuously play audio from the PCM queue."""
        should_exit = False
        draining = False  # new flag

        def audio_callback(outdata, _a, _b, _c):
            nonlocal should_exit, draining

            try:
                pcm_data = outq.get_nowait()

                # End-of-stream marker received
                if pcm_data is None:
                    draining = True  # start draining remaining frames
                    outdata[:] = 0
                    return

                # Normal audio
                outdata[:, 0] = pcm_data

            except asyncio.QueueEmpty:
                # If we are draining and queue is empty -> exit
                if draining:
                    should_exit = True
                outdata[:] = 0

        with sd.OutputStream(
            samplerate=SAMPLE_RATE,
            blocksize=240,
            channels=1,
            callback=audio_callback,
        ):
            while True:
                if should_exit:
                    break
                await asyncio.sleep(0.01)  # smaller sleep for responsiveness

    async def save_queue(self, outq: asyncio.Queue):

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"audio_{timestamp}.wav"

        # Open WAV file for streaming writes
        wf = wave.open(filename, "wb")
        wf.setnchannels(1)    # mono
        wf.setsampwidth(2)    # 16-bit PCM
        wf.setframerate(SAMPLE_RATE)

        try:
            while True:
                item = await outq.get()
                print("CD", len(item))
                if item is None:
                    break

                # item is expected to be numpy array (float32 or int16)
                # Convert to int16 PCM
                if item.dtype != np.int16:
                    pcm = (item * 32767).astype(np.int16)
                else:
                    pcm = item

                # Write chunk to file
                wf.writeframes(pcm.tobytes())
                print("---")
        finally:
            wf.close()
            print(f"Saved audio to {filename}")


if __name__ == '__main__':

    room = Room(endpoint='3.135.218.25')
    room.start()
