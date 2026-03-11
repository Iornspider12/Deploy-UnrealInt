from aiortc import RTCConfiguration, RTCIceServer
from aiortc import RTCPeerConnection, RTCSessionDescription
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from multiprocessing import Manager, Process
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from datetime import datetime
from aiortc import AudioStreamTrack, MediaStreamError
from av import AudioFrame
import numpy as np
import fractions
import traceback
import uvicorn
import resampy
import time
import os
from dotenv import load_dotenv

# Load env variables (Main process)
load_dotenv()

config = RTCConfiguration(
    iceServers=[
        RTCIceServer(
            urls=[
                "stun:stun.l.google.com:19302",
                "turn:0.0.0.0:3478"
            ]
        )
    ]
)

class ProcessInfo(BaseModel):
    id: int
    pid: int | None = None
    start_time: datetime | None = None
    duration: int | None = None
    end_time: datetime | None = None
    sts: str
    ret: list[str] = []
    err: list[str] = []
    sdp: str = None
    type: str = None

def unified_webrtc_listener(slots, slot: str, client_sdp: str, client_type: str):
    import asyncio
    import os
    from dotenv import load_dotenv
    from llm import LLM
    from query import Query
    from stt import STT
    from tts import TTS
    
    # Reload env inside the process to ensure we get the latest VOICE_IP
    load_dotenv()
    voice_ip = os.getenv('VOICE_IP')
    
    slot_dict = slots[slot]
    start_time = datetime.now()
    slot_dict['sts'] = "Online"
    slot_dict['start_time'] = start_time
    print(f"[{slot}] Unified WebRTC listener process started.")

    async def start_listener():
        try:
            offer = RTCSessionDescription(sdp=client_sdp, type=client_type)
            pc = RTCPeerConnection(config)
            data_channel = None
            
            voice_inpq = asyncio.Queue()
            voice_sttq = asyncio.Queue()
            voice_llm_out = asyncio.Queue()
            voice_outq = asyncio.Queue() # PCM at 24k
            text_llm_input = asyncio.Queue()
            unified_llm_input = asyncio.Queue()
            
            @pc.on("iceconnectionstatechange")
            async def on_ice(): print(f"[{slot}] [ICE] {pc.iceConnectionState}")

            # No Track logic needed if DLL only supports DataChannel
            @pc.on("track")
            def on_track(track): print(f"[{slot}] [TRACK] {track.kind} received (Ignoring for DC flow)")

            print(f"[{slot}] [AI] Initializing AI stack...")
            shared_llm = LLM()
            stt_obj = STT(endpoint=f"ws://{voice_ip}:8080", show_vad=True)
            tts_obj = TTS(endpoint=f"ws://{voice_ip}:8080", voice="expresso/ex03-ex01_happy_001_channel1_334s.wav")

            # PRE-WARM LLM (Optional but recommended to reduce first-response latency)
            try:
                # We can do a dry-run or just rely on the instantiation
                print(f"[{slot}] [AI] AI stack initialized.")
            except: pass

            await pc.setRemoteDescription(offer)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            slot_dict['sdp'] = str(pc.localDescription.sdp).strip()
            slot_dict['type'] = str(pc.localDescription.type).strip().lower()
            slots[slot] = slot_dict.copy()
            print(f"[{slot}] [SDP] Answer generated and exposed.")

            async def input_router():
                while True:
                    v_task = asyncio.create_task(voice_sttq.get())
                    t_task = asyncio.create_task(text_llm_input.get())
                    done, pending = await asyncio.wait([v_task, t_task], return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        q = await t
                        s = "voice" if t == v_task else "text"
                        await unified_llm_input.put((s, q))
                    for t in pending: t.cancel()

            async def unified_llm_pipeline():
                while True:
                    source, query = await unified_llm_input.get()
                    print(f"[{slot}] [LLM] Processing {source} input...")
                    
                    if data_channel and data_channel.readyState == "open":
                        try:
                            # Send marker for Unreal Playback
                            data_channel.send("[AGENT_START]")
                        except: pass
                    
                    full_reply = ""
                    try:
                        async for resp in shared_llm.app.astream({"messages": query.raw()}, {"configurable": {"thread_id": shared_llm._id}}):
                            token = resp['model']['messages'].content
                            full_reply += token
                            
                            # Stream token to TTS immediately for lower latency
                            await voice_llm_out.put(token)
                            
                            # Stream token to DataChannel (Text)
                            if data_channel and data_channel.readyState == "open":
                                try: data_channel.send(token)
                                except: pass
                                
                    except Exception as e:
                        print(f"[{slot}] [LLM ERROR] {e}")
                        if data_channel and data_channel.readyState == "open":
                            data_channel.send(f"Error: {e}")
                    
                    print(f"[{slot}] [AI Output Complete] Sending EOL to TTS.")
                    await voice_llm_out.put("<EOL>")

            @pc.on("datachannel")
            async def on_dc(dc):
                nonlocal data_channel
                data_channel = dc
                print(f"[{slot}] [DC] Layer detected: {dc.label}")
                async def handle_dc_message(message):
                    # STEP 3: Confirm Python receives audio
                    # sparse logging handled in on_message_wrapper
                    
                    if isinstance(message, bytes):
                        # SECURITY: Packet validation
                        if len(message) > 4096:
                            print(f"[{slot}] 🛡️ [SECURITY] Dropped oversized packet ({len(message)} bytes)")
                            return
                        
                        # 48kHz PCM from Unreal
                        pcm16 = np.frombuffer(message, dtype=np.int16)
                        norm_pcm = pcm16.astype(np.float32) / 32768.0
                        
                        # Check audio level
                        rms = float(np.sqrt(np.mean(norm_pcm**2)))
                        
                        # Count packets for logging
                        if not hasattr(handle_dc_message, "_pkt_cnt"):
                            handle_dc_message._pkt_cnt = 0
                        handle_dc_message._pkt_cnt += 1
                        
                        # Log only: first packet, every 500th packet, or if speech detected
                        cnt = handle_dc_message._pkt_cnt
                        if cnt == 1:
                            print(f"[{slot}] ✅ FIRST AUDIO PACKET | {len(message)} bytes | RMS: {rms:.6f}")
                        elif cnt % 500 == 0:
                            print(f"[{slot}] [STT] Total: {cnt} packets | RMS: {rms:.6f}")
                        elif rms > 0.02:  # Speech threshold
                            print(f"[{slot}] 🎤 SPEECH | RMS: {rms:.3f} | Pkt #{cnt}")
                        
                        # Resample to 24kHz for Moshi in a thread to keep loop responsive
                        pcm_24k = await asyncio.to_thread(resampy.resample, norm_pcm, 48000, 24000)
                        await voice_inpq.put(pcm_24k.astype(np.float32))
                        return
                    
                    print(f"[{slot}] [DC] Text: {message}")
                    from query import Query
                    await text_llm_input.put(Query(message))

                # Message counter for sparse logging
                if not hasattr(on_dc, '_msg_count'):
                    on_dc._msg_count = 0
                
                @dc.on("message")
                async def on_message_wrapper(message):
                    on_dc._msg_count += 1
                    # Log first message + every 200th message
                    if on_dc._msg_count == 1 or on_dc._msg_count % 200 == 0:
                        print(f"[{slot}] 🔥 MESSAGE #{on_dc._msg_count} | Type: {type(message).__name__} | Size: {len(message) if isinstance(message, (bytes, str)) else '?'}")
                    try:
                        await handle_dc_message(message)
                    except Exception as e:
                        print(f"[{slot}] ❌ HANDLER ERROR (msg #{on_dc._msg_count}): {e}")
                        import traceback
                        traceback.print_exc()

                async def trigger_welcome():
                    print(f"[{slot}] [DC] Handshake successful. AI Bridge Active.")
                    dc.send("[SERVER_READY]")
                    await asyncio.sleep(1.0)
                    from query import Query
                    await text_llm_input.put(Query("Hello! I am ready to help. Speak or type away!"))

                # PROACTIVE TRIGGER: If already open, start now.
                if dc.readyState == "open":
                    asyncio.create_task(trigger_welcome())
                else:
                    @dc.on("open")
                    async def on_open():
                        asyncio.create_task(trigger_welcome())

            async def tts_audio_sender():
                print(f"[{slot}] [DEBUG] TTS Audio Sender Task Started.")
                """
                Sends 10ms batches of audio back over DataChannel with 'AUD' tag.
                Matches Moshi's native 24k -> 48k upsampling.
                """
                # 240 samples @ 24kHz = 10ms
                while True:
                    try:
                        # Get a 10ms chunk (240 samples @ 24k)
                        full_pcm_24k = await voice_outq.get()
                        print(f"[{slot}] [DEBUG] Popped {len(full_pcm_24k)} samples from voice_outq")
                        
                        # Up-sample to 48kHz for Unreal Playback (240 -> 480 samples) - Run in thread
                        pcm_48k = await asyncio.to_thread(resampy.resample, full_pcm_24k, 24000, 48000)
                        
                        # Convert float32 -> int16
                        pcm_int16 = (np.clip(pcm_48k, -1, 1) * 32767).astype(np.int16)
                        
                        if data_channel and data_channel.readyState == "open":
                            # DIAGNOSTIC: Send text message first to verify channel works
                            try:
                                data_channel.send("[TTS_PACKET_INCOMING]")
                            except Exception as e:
                                print(f"[{slot}] [ERROR] Text send failed: {e}")
                            
                            # STEP 5: Confirm TTS output
                            print(f"[{slot}] [TTS DEBUG] sending {len(pcm_int16)} samples to Unreal")
                            
                            # Send as binary with AUD tag
                            audio_packet = b"AUD" + pcm_int16.tobytes()
                            try:
                                data_channel.send(bytes(audio_packet))
                                print(f"[{slot}] [TTS DEBUG] ✅ Binary send succeeded ({len(audio_packet)} bytes)")
                            except Exception as e:
                                print(f"[{slot}] [ERROR] Binary send failed: {e}")
                    except asyncio.CancelledError: break
                    except Exception as e: print(f"[{slot}] [ERROR] TTS Sender: {e}")

            tasks = [
                asyncio.create_task(stt_obj.pipeline(voice_inpq, voice_sttq)),
                asyncio.create_task(unified_llm_pipeline()),
                asyncio.create_task(tts_obj.pipeline(voice_llm_out, voice_outq)),
                asyncio.create_task(input_router()),
                asyncio.create_task(tts_audio_sender())
            ]
            
            shutdown = asyncio.Event()
            @pc.on("connectionstatechange")
            async def _check():
                if pc.connectionState in ("failed", "closed", "disconnected"): shutdown.set()
            
            while not shutdown.is_set():
                await asyncio.sleep(5)
                slot_dict['duration'] = (datetime.now() - start_time).total_seconds()
                slots[slot] = slot_dict
                print(f"[{slot}] Heartbeat... {slot_dict['duration']:.0f}s")
            
            for t in tasks: t.cancel()
            await pc.close()

        except Exception as e:
            print(f"[{slot}] FATAL: {e}")
            traceback.print_exc()
            slot_dict['sts'] = "Offline"
            slots[slot] = slot_dict

    asyncio.run(start_listener())

def create_app(slots):
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    API_KEY = "secret123" # Move to .env for production

    @app.post("/offer")
    async def offer(request: Request):
        # SECURITY: API Key protection
        if request.headers.get("x-api-key") != API_KEY:
            raise HTTPException(401, "Invalid API Key")

        params = await request.json()
        for slot, meta in slots.items():
            if meta['sts'] == "Offline":
                p = Process(target=unified_webrtc_listener, args=(slots, slot, params['sdp'], params['type']))
                p.start()
                slots[slot]['pid'] = p.pid
                # Wait for SDP
                for _ in range(30):
                    time.sleep(0.5)
                    if slots[slot].get('sdp'): break
                return {'msg': 'Started', 'slot': slot, 'sdp': slots[slot]['sdp'], 'type': slots[slot]['type']}
        raise HTTPException(503, "No free slots")

    @app.get("/all")
    async def get_all(): return dict(slots)

    return app

if __name__ == "__main__":
    import uvicorn
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--slots", type=int, default=2)
    args = parser.parse_args()
    
    manager = Manager()
    slots = manager.dict({
        f"localhost:{args.port}-{x}": manager.dict(ProcessInfo(id=x, sts="Offline").model_dump()) for x in range(args.slots)
    })
    app = create_app(slots)
    uvicorn.run(app, host="0.0.0.0", port=args.port)
