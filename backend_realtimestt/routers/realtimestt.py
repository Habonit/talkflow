# core
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import subprocess
import threading
import asyncio

# sound
from RealtimeSTT import AudioToTextRecorder    
from transformers import pipeline
from scipy.signal import resample    
import soundfile as sf

# utils
from datetime import datetime    
from loguru import logger
from pathlib import Path
import numpy as np
import redis
import json
import time
import os

# 로그 설정
logger.add("logs/stt_server.log", rotation="10 MB", level="DEBUG", enqueue=True)
logger.info("STT WebSocket server initializing...")

router = APIRouter()

# 경로 미리 지정
AUDIO_SAVE_DIR = Path("/app/audio")
AUDIO_SAVE_DIR.mkdir(parents=True, exist_ok=True)

# 욕설 감지 파이프라인
pipe = pipeline(
    "text-classification",
    model="smilegate-ai/kor_unsmile",
    device=0,
    return_all_scores=True,
    function_to_apply="softmax"
)

logger.info(f"REDIS_HOST={os.getenv('REDIS_HOST')}")
logger.info(f"REDIS_PORT={os.getenv('REDIS_PORT')}")
logger.info(f"REDIS_PASSWORD={os.getenv('REDIS_PASSWORD')}")
logger.info(f"REDIS_DB_STT={os.getenv('REDIS_DB_STT')}")

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    password=os.getenv("REDIS_PASSWORD"),
    db=int(os.getenv("REDIS_DB_STT")),
    decode_responses=True
)

@router.websocket("/ws/stt")
async def stt_websocket(websocket: WebSocket):
    await websocket.accept()

    loop = asyncio.get_running_loop()
    recorder_ready = threading.Event()
    is_running = True
    recorder = None
    
    # --- 최초 metadata 저장용 변수 선언 ---
    session_id = None
    user_id = None
    file_dir_path = None
    metadata_initialized = False
    filepath_initialized = False
    
    async def send_to_client(message: str):
        try:
            await websocket.send_text(message)
        except WebSocketDisconnect:
            logger.info("Client disconnected")
            
    # TODO: 욕설 감지 후처리 어떻게 할 것인지 고도화 필요        
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
        return label

    def text_detected(text: str):
        asyncio.run_coroutine_threadsafe(
            send_to_client(json.dumps({
                'type': 'realtime',
                'text': text
            })), loop
        )
        # 아래 로그를 활성화하면 너무 로그가 많이 출력되어 생략했습니다.
        # logger.info(f"[Realtime] {text}")

    def run_recorder():
        nonlocal recorder, is_running, filepath_initialized, file_dir_path
        logger.info("Initializing RealtimeSTT...")
        recorder = AudioToTextRecorder(**recorder_config)
        logger.info("RealtimeSTT initialized")
        recorder_ready.set()

        while is_running:
            try:
                start_time = time.time()
                full_sentence = recorder.text()                
                                
                end_time = time.time()
                stt_latency = end_time - start_time
                label = handle_transcription(full_sentence, pipe)
                if full_sentence:
                    asyncio.run_coroutine_threadsafe(
                        send_to_client(json.dumps({
                            'type': 'fullSentence',
                            'text': full_sentence,
                            'stt_latency': stt_latency,
                            'label': label,
                            "session_id": session_id,
                            "user_id": user_id,
                            "timestamp": int(end_time)
                        })), loop
                    )
                    logger.info(f"[Sentence] {full_sentence}")
                    logger.info(f"[Label] {label}")
                    logger.info(f"[Stt Latency] {stt_latency}")
                    
                    # TODO: redis 테스트 중, pub, sub로, 혹은 lpush하는 걸로 저장하는 것 검토
                    data = {
                        'type': 'fullSentence',
                        "text": full_sentence,
                        "label": label,
                        "timestamp": int(end_time),
                        "stt_latency": stt_latency,
                        "session_id": session_id,
                        "user_id": user_id,
                    }   
                    redis_client.lpush("stt:sentences", json.dumps(data))
                    redis_client.publish("stt:sentences", json.dumps(data))
                    
                    logger.info("Redis 발행 성공")
                    
                # TODO: 녹음된 오디오를 파일로 저장
                audio_array = recorder.audio
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                filename = f"{user_id}_{timestamp}.wav"
                if not filepath_initialized:
                    file_dir_path = AUDIO_SAVE_DIR / session_id 
                    file_dir_path.mkdir(parents=True, exist_ok=True)
                    filepath_initialized = True
                filepath = file_dir_path / filename

                sf.write(str(filepath), audio_array, samplerate=16000)
                logger.info(f"Audio saved to {filepath}") 
 
            except Exception as e:
                logger.error(f"Error in recorder thread: {e}")

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

    def merge_session_audio():
        if not file_dir_path or not file_dir_path.exists():
            logger.warning("No audio chunks found for merging.")
            return

        wav_files = sorted(file_dir_path.glob("*.wav"), key=lambda x: x.name)
        if not wav_files:
            logger.warning("No wav files to merge in session dir.")
            return

        logger.info(f"Merging {len(wav_files)} audio chunks from: {file_dir_path}")

        # ffmpeg용 concat list 파일 생성
        concat_list_path = file_dir_path / "concat_list.txt"
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for wav in wav_files:
                f.write(f"file '{wav.resolve()}'\n")

        output_path = AUDIO_SAVE_DIR / session_id / f"{session_id}_merged.wav"

        # ffmpeg 명령어 실행
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            str(output_path)
        ]

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"Final merged audio saved at: {output_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg merge failed: {e}")

    recorder_config = {
        'spinner': False,
        'use_microphone': False,
        'model': 'medium',
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
                
                if not metadata_initialized:
                    session_id = metadata.get('sessionId', 'unknown_session')
                    user_id = metadata.get('userId', 'unknown_user')
                    metadata_initialized = True
                    logger.info(f"Metadata initialized: session_id={session_id}, user_id={user_id}")
                
                sample_rate = metadata['sampleRate']
                chunk = message[4 + metadata_length:]
                resampled_chunk = decode_and_resample(chunk, sample_rate, 16000)
                recorder.feed_audio(resampled_chunk)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    finally:
        is_running = False
        if recorder:
            recorder.stop()
            recorder.shutdown()
        logger.info("Recorder shutdown complete")
        if session_id:
            merge_session_audio()
