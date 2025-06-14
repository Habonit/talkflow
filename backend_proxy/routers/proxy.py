from fastapi import APIRouter, WebSocket
import websockets
import asyncio
import os
from loguru import logger

router = APIRouter()
REALTIME_STT_URL = os.getenv("REALTIME_STT_URL")

logger.add("logs/proxy_server.log", rotation="10 MB", level="DEBUG", enqueue=True)
logger.info("Proxy WebSocket server initializing...")

@router.websocket("/ws/proxy")
async def proxy_stt_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("Connected to proxy")
    
    try:
        async with websockets.connect(REALTIME_STT_URL) as stt_ws:
            logger.info(f"Connected to backend realtime STT: {REALTIME_STT_URL}")
            
            async def forward_client_to_stt():
                try: 
                    while True:
                        data = await websocket.receive_bytes()
                        await stt_ws.send(data)
                
                except Exception as e:
                    logger.warning(f"Client -> STT connection closed: {e}")
                    await stt_ws.close()
                    try:
                        # 종료 안하면 클라이언트가 종료되어도 계속 쌓이게 됨
                        await stt_ws.close()
                    except Exception:
                        pass 
                    raise e
                
            async def forward_stt_to_client():
                try: 
                    while True:
                        msg = await stt_ws.recv()
                        await websocket.send_text(msg)
                
                except Exception as e:
                    logger.warning(f"STT -> Client connection closed: {e}")
                    try:
                        # 종료 안하면 클라이언트가 종료되어도 계속 쌓이게 됨
                        await websocket.close()
                    except Exception:
                        pass
                    raise e
                
            # gather에 return_exception을 사용해서 어느 쪽이든 끊기면 중지
            await asyncio.gather(
                forward_client_to_stt(),
                forward_stt_to_client(),
                return_exceptions=True
            )
            
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

    finally:
        logger.info("WebSocket session ended.")
        try:
            # 종료 안하면 클라이언트가 종료되어도 계속 쌓이게 됨
            await websocket.close()
        except Exception:
            pass
            
        
        