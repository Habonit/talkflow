import os
import redis
import json
from openai import OpenAI
from loguru import logger

# 로그 저장 경로 및 설정
logger.add("logs/llm_agent.log", rotation="10 MB", level="DEBUG", enqueue=True)
logger.info("[LLM Agent] 초기화 시작")

# OpenAI 클라이언트
client = OpenAI(api_key= os.getenv("OPENAI_API_KEY"))

# Redis 클라이언트
logger.info(f"REDIS_HOST={os.getenv('REDIS_HOST')}")
logger.info(f"REDIS_PORT={os.getenv('REDIS_PORT')}")
logger.info(f"REDIS_PASSWORD={os.getenv('REDIS_PASSWORD')}")
logger.info(f"REDIS_DB_STT={os.getenv('REDIS_DB_STT')}")

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    db=int(os.getenv("REDIS_DB_STT")),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True
)

pubsub = redis_client.pubsub()
pubsub.subscribe("stt:sentences")
logger.info("[LLM Agent] Redis 채널 'stt:sentences' 구독 시작")

def query_openai(prompt: str) -> str:
    try:
        res = client.responses.create(
                model="gpt-4o-mini",
                input = [
                    {
                        "role": "user",
                        "content" : prompt
                    }
                ]
            )
            
        return res.output_text
    except Exception as e:
        logger.error(f"[LLM Agent] OpenAI 호출 실패: {e}")
        return "LLM 처리 오류"

for message in pubsub.listen():
    if message["type"] != "message":
        continue
    try:
        data = json.loads(message["data"])
        logger.info(f"[LLM Agent] 수신: {data}")

        response = query_openai(data["text"])
        logger.info(f"[LLM Agent] 응답: {response}")
    except Exception as e:
        logger.exception(f"[LLM Agent] 처리 중 예외 발생: {e}")
