
import asyncio
import tqdm
import sphn
import websockets
import time
import numpy as np
import sounddevice as sd
import wave
from unmute.kyutai_constants import SAMPLES_PER_FRAME
from unmute.tts.text_to_speech import (
    TextToSpeech,
    TTSAudioMessage,
    TTSClientEosMessage,
    TTSTextMessage,
)

from datetime import datetime
SAMPLE_RATE = 24000
BLOCK_SIZE = 1920


class TTS:

    def __init__(self, endpoint, voice):

        self.endpoint = endpoint
        self.voice = voice

        # Asynchronous Queues
        self.inpq = asyncio.Queue()
        self.outq = asyncio.Queue()

    def start(self):

        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            print("Interrupted by User")

    async def run(self):

        async def read_lines_from_file(path: str, inpq):
            loop = asyncio.get_running_loop()

            def producer():
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        asyncio.run_coroutine_threadsafe(inpq.put(line), loop)
                        asyncio.run_coroutine_threadsafe(inpq.put("<EOL>"), loop)
                        time.sleep(5)
                asyncio.run_coroutine_threadsafe(inpq.put("<EOS>"), loop)

            await asyncio.to_thread(producer)

        # Start stdin reading and pipeline together
        stdin_reader_task = asyncio.create_task(
            read_lines_from_file('tts_text.txt', self.inpq)
        )
        pipeline_task = asyncio.create_task(
            self.pipeline(self.inpq, self.outq)
        )
        stdout_player_task = asyncio.create_task(
            self.play_queue(self.outq)
        )
        # stdout_writer_task = asyncio.create_task(
        #     self.save_queue(self.outq)
        # )

        await asyncio.gather(
            stdin_reader_task,
            pipeline_task,
            stdout_player_task,
            # stdout_writer_task
        )



    async def pipeline(self, inpq: asyncio.Queue, outq: asyncio.Queue):
        """
        Main async TTS pipeline:
        - Gets text tokens from inpq
        - Sends to TTS server over a persistent session
        - Receives audio chunks into outq
        """
        while True:
            # Connect for a new "session" (one complete LLM response)
            tts = TextToSpeech(tts_instance=self.endpoint, voice=self.voice)
            try:
                await tts.start_up()
                print(f"[SUCCESS] TTS Connected for streaming to {self.endpoint}")

                async def receive_loop():
                    async for msg in tts:
                        if isinstance(msg, TTSAudioMessage):
                            pcm = np.array(msg.pcm).astype(np.float32)
                            # Split 80ms chunk into 10ms chunks for jitter-free streaming
                            for i in range(0, len(pcm), 240):
                                chunk = pcm[i:i+240]
                                if len(chunk) == 240:
                                    await outq.put(chunk)
                        elif isinstance(msg, TTSClientEosMessage):
                             break

                receive_task = asyncio.create_task(receive_loop())

                while True:
                    token = await inpq.get()
                    if token is None or token == "<EOS>":
                        await tts.send(TTSClientEosMessage())
                        break
                    
                    if token == "<EOL>":
                        # End of current response
                        await tts.send(TTSClientEosMessage())
                        break

                    # Send token to TTS server
                    # Small delay if the token contains multiple words to avoid congestion
                    for word in token.split(" "):
                        if word.strip():
                            await tts.send(word.strip())
                
                # Wait for all audio from the current session
                await receive_task
                if token is None or token == "<EOS>": break

            except Exception as e:
                print(f"[ERROR] TTS Connection/Pipeline error: {e}")
                await asyncio.sleep(1) # Reconnect backoff

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
    import os
    from dotenv import load_dotenv
    load_dotenv()
    voice_ip = os.getenv('VOICE_IP', '3.142.197.83')

    # Init Obj
    tts = TTS(endpoint=f"ws://{voice_ip}:8080",
              voice="expresso/ex03-ex01_happy_001_channel1_334s.wav")
    tts.start()
