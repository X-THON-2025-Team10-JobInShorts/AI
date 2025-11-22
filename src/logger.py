import structlog
import sys
from structlog.stdlib import filter_by_level
from typing import Optional


def setup_logger(level: str = "INFO"):
    """
    구조화된 로깅 설정
    """
    structlog.configure(
        processors=[
            filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    logger = structlog.get_logger()
    return logger


def get_job_logger(job_id: str, user_id: Optional[str] = None):
    """
    Job별 로거 생성
    """
    logger = structlog.get_logger()
    context = {"job_id": job_id}
    if user_id:
        context["user_id"] = user_id
    
    return logger.bind(**context)


class LogStage:
    DOWNLOAD_START = "DOWNLOAD_START"
    DOWNLOAD_DONE = "DOWNLOAD_DONE"
    FFMPEG_START = "FFMPEG_START"
    FFMPEG_DONE = "FFMPEG_DONE"
    STT_START = "STT_START"
    STT_DONE = "STT_DONE"
    LLM_START = "LLM_START"
    LLM_DONE = "LLM_DONE"
    CALLBACK_SUCCESS = "CALLBACK_SUCCESS"
    CALLBACK_FAILED = "CALLBACK_FAILED"
    JOB_START = "JOB_START"
    JOB_DONE = "JOB_DONE"
    JOB_FAILED = "JOB_FAILED"


class ErrorCode:
    S3_DOWNLOAD_FAILED = "S3_DOWNLOAD_FAILED"
    INVALID_FILE_FORMAT = "INVALID_FILE_FORMAT"
    FFMPEG_FAILED = "FFMPEG_FAILED"
    STT_TIMEOUT = "STT_TIMEOUT"
    STT_BAD_RESPONSE = "STT_BAD_RESPONSE"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_BAD_RESPONSE = "LLM_BAD_RESPONSE"
    CALLBACK_FAILED = "CALLBACK_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"