# 프로젝트명: TalkFlow 
TalkFlow는 실시간 데이터를 후처리하여 Redis에 저장하고, 실험적으로 언어 모델과 텍스트-투-스피치(TTS) 시스템을 통합하여 실시간 대화가 가능한 환경을 설계한 프로젝트입니다.

# 사용 방법
## 환경 설정
.env 파일을 작성하여 필요한 환경 변수를 설정합니다.

```env
# 컨테이너 포트와 gpu index 매핑
STT_HOST_1 = localhost
STT_PORT_1=8001
GPU_1=0
REDIS_DB_STT_1=0
REDIS_DB_LLM_1=1

# autocommit
COMMIT_OPENAI_API_KEY=your_open_api_key
COMMIT_MODEL=gpt-4o-mini

# 언어모델 답변
OPENAI_API_KEY=your_open_api_key

# redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=redis
```
## 도커 실행

docker compose up -d --build