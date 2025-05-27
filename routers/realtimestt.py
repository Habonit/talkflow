from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from RealtimeSTT import AudioToTextRecorder
import numpy as np
from scipy.signal import resample
import threading
import asyncio
import json

router = APIRouter()

@router.websocket("/ws/stt")
async def stt_websocket(websocket: WebSocket):
    await websocket.accept()

    loop = asyncio.get_running_loop()
    recorder_ready = threading.Event()
    is_running = True
    recorder = None

    async def send_to_client(message: str):
        try:
            await websocket.send_text(message)
        except WebSocketDisconnect:
            print("Client disconnected")

    def text_detected(text: str):
        asyncio.run_coroutine_threadsafe(
            send_to_client(json.dumps({
                'type': 'realtime',
                'text': text
            })), loop
        )
        print(f"\rRealtime: {text}", flush=True, end='')

    def run_recorder():
        nonlocal recorder, is_running
        print("Initializing RealtimeSTT...")
        recorder = AudioToTextRecorder(**recorder_config)
        print("RealtimeSTT initialized")
        recorder_ready.set()

        while is_running:
            try:
                full_sentence = recorder.text()
                if full_sentence:
                    asyncio.run_coroutine_threadsafe(
                        send_to_client(json.dumps({
                            'type': 'fullSentence',
                            'text': full_sentence
                        })), loop
                    )
                    print(f"\rSentence: {full_sentence}")
            except Exception as e:
                print(f"Error in recorder thread: {e}")

    def decode_and_resample(audio_data, original_sample_rate, target_sample_rate):
        try:
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            num_original_samples = len(audio_np)
            num_target_samples = int(num_original_samples * target_sample_rate / original_sample_rate)
            resampled_audio = resample(audio_np, num_target_samples)
            return resampled_audio.astype(np.int16).tobytes()
        except Exception as e:
            print(f"Error in resampling: {e}")
            return audio_data

    recorder_config = {
        'spinner': False,
        'use_microphone': False,
        'model': 'large-v3',
        'language': 'ko',
        'silero_sensitivity': 0.4,
        'webrtc_sensitivity': 2,
        'post_speech_silence_duration': 0.7,
        'min_length_of_recording': 0,
        'min_gap_between_recordings': 0,
        'enable_realtime_transcription': True,
        'realtime_processing_pause': 0,
        'realtime_model_type': 'base',
        'on_realtime_transcription_stabilized': text_detected,
        'compute_type' : 'int8',
        'device' : 'cuda'
    }

    recorder_thread = threading.Thread(target=run_recorder, daemon=True)
    recorder_thread.start()
    recorder_ready.wait()

    try:
        while True:
            message = await websocket.receive_bytes()
            if not recorder_ready.is_set():
                continue
            try:
                metadata_length = int.from_bytes(message[:4], byteorder='little')
                metadata_json = message[4:4 + metadata_length].decode('utf-8')
                metadata = json.loads(metadata_json)
                sample_rate = metadata['sampleRate']
                chunk = message[4 + metadata_length:]
                resampled_chunk = decode_and_resample(chunk, sample_rate, 16000)
                recorder.feed_audio(resampled_chunk)
            except Exception as e:
                print(f"Error processing message: {e}")
    except WebSocketDisconnect:
        print("Client disconnected")
    finally:
        is_running = False
        if recorder:
            recorder.stop()
            recorder.shutdown()
