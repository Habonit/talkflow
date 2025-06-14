from fastapi import FastAPI
from backend_proxy.routers.proxy import router as stt_proxy_router

app = FastAPI()
app.include_router(stt_proxy_router)