import os
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

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
    
    @field_validator('sqs_queue_url')
    @classmethod
    def validate_sqs_url(cls, v):
        if v and not v.startswith('https://sqs.'):
            raise ValueError('Invalid SQS Queue URL format')
        return v
    
    @field_validator('backend_base_url')
    @classmethod
    def validate_backend_url(cls, v):
        if v and not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('Invalid Backend URL format')
        return v
    
    @field_validator('claude_api_url')
    @classmethod
    def validate_claude_url(cls, v):
        if v and not v.startswith('https://api.anthropic.com'):
            raise ValueError('Invalid Claude API URL format')
        return v
    
    model_config = {"case_sensitive": False}


def validate_required_settings(settings_instance=None):
    """필수 환경 변수 검증"""
    if settings_instance is None:
        settings_instance = Settings()
    
    required_vars = [
        ('SQS_QUEUE_URL', settings_instance.sqs_queue_url),
        ('BACKEND_BASE_URL', settings_instance.backend_base_url),
        ('BACKEND_INTERNAL_TOKEN', settings_instance.backend_internal_token),
        ('CLOVA_API_KEY_ID', settings_instance.clova_api_key_id),
        ('CLOVA_API_KEY', settings_instance.clova_api_key),
        ('CLAUDE_API_KEY', settings_instance.claude_api_key)
    ]
    
    missing_vars = [name for name, value in required_vars if not value]
    
    if missing_vars:
        raise ValueError(f"필수 환경 변수가 누락되었습니다: {', '.join(missing_vars)}")


settings = Settings()