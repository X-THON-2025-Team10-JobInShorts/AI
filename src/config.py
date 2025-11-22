import os
from dotenv import load_dotenv
from pydantic import BaseSettings
from typing import Optional

load_dotenv()


class Settings(BaseSettings):
    # 공통
    app_env: str = os.getenv("APP_ENV", "dev")
    
    # AWS
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-2")
    video_bucket_name: str = os.getenv("VIDEO_BUCKET_NAME", "shortform-video-bucket")
    result_bucket_name: str = os.getenv("RESULT_BUCKET_NAME", "shortform-result-bucket")
    sqs_queue_url: str = os.getenv("SQS_QUEUE_URL", "")
    sqs_wait_time_seconds: int = int(os.getenv("SQS_WAIT_TIME_SECONDS", "10"))
    sqs_visibility_timeout_seconds: int = int(os.getenv("SQS_VISIBILITY_TIMEOUT_SECONDS", "90"))
    
    # Backend callback
    backend_base_url: str = os.getenv("BACKEND_BASE_URL", "")
    backend_internal_token: str = os.getenv("BACKEND_INTERNAL_TOKEN", "")
    
    # Clova STT
    clova_stt_url: str = os.getenv("CLOVA_STT_URL", "https://naveropenapi.apigw.ntruss.com/recog/v1/stt?lang=Kor")
    clova_api_key_id: str = os.getenv("CLOVA_API_KEY_ID", "")
    clova_api_key: str = os.getenv("CLOVA_API_KEY", "")
    
    # Claude / LLM
    claude_api_url: str = os.getenv("CLAUDE_API_URL", "https://api.anthropic.com/v1/messages")
    claude_api_key: str = os.getenv("CLAUDE_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-latest")
    claude_max_tokens: int = int(os.getenv("CLAUDE_MAX_TOKENS", "2000"))
    
    # 처리 설정
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_delay_seconds: int = int(os.getenv("RETRY_DELAY_SECONDS", "5"))
    
    class Config:
        case_sensitive = False


settings = Settings()