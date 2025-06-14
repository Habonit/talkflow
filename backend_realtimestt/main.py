from fastapi import FastAPI
from backend_realtimestt.routers.realtimestt import router as stt_router

app = FastAPI()
app.include_router(stt_router)
