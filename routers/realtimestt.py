from transformers import pipeline

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from RealtimeSTT import AudioToTextRecorder
import numpy as np
from scipy.signal import resample
import threading
import asyncio
import json
import time

router = APIRouter()
pipe = pipeline(
    "text-classification",
    model="smilegate-ai/kor_unsmile",
    device=0,  # CUDA:0
    return_all_scores=True,
    function_to_apply="softmax"
)

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
            
    def handle_transcription(text, pipe):
        start_time = time.time()
        scores = {d['label']: d['score'] for d in pipe(text)[0]}
        label = "욕설 여부: "

        threshold_clean = 0.4
        threshold_hatespeech = 0.2
        if scores['clean'] < threshold_clean:
                label += "o, "
                prioritize = dict(
                        sorted(
                                (item for item in scores.items() if item[0] != 'clean'),
                                key=lambda x: x[1],
                                reverse=True
                        )[:2]
                )
                for k, v in prioritize.items():
                        if v > threshold_hatespeech:
                                label += f"{k}: {v:.2f}"
                                
        else:
                label += f"x, 정상: {scores['clean']: .2f}"
        end_time = time.time()
        latency =end_time - start_time
        label += f", 처리 시간: {latency:.2f}초"
        return label, 

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
                label = handle_transcription(full_sentence, pipe)
                if full_sentence:
                    asyncio.run_coroutine_threadsafe(
                        send_to_client(json.dumps({
                            'type': 'fullSentence',
                            'text': full_sentence,
                            'label': label
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
