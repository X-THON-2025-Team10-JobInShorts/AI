import pytest
import os
import tempfile
from datetime import datetime
from unittest.mock import Mock, MagicMock
from pathlib import Path

from src.models import JobContext, CallbackRequest
from src.config import Settings


@pytest.fixture
def mock_settings():
    """테스트용 설정 픽스처"""
    settings = Settings()
    settings.app_env = "test"
    settings.aws_region = "ap-northeast-2"
    settings.video_bucket_name = "test-video-bucket"
    settings.result_bucket_name = "test-result-bucket"
    settings.sqs_queue_url = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/test-queue"
    settings.sqs_wait_time_seconds = 1
    settings.sqs_visibility_timeout_seconds = 30
    settings.backend_base_url = "https://test-backend.com"
    settings.backend_internal_token = "test-token"
    settings.clova_stt_url = "https://naveropenapi.apigw.ntruss.com/recog/v1/stt?lang=Kor"
    settings.clova_api_key_id = "test-clova-id"
    settings.clova_api_key = "test-clova-key"
    settings.claude_api_url = "https://api.anthropic.com/v1/messages"
    settings.claude_api_key = "test-claude-key"
    settings.claude_model = "claude-3-7-sonnet-latest"
    settings.claude_max_tokens = 2000
    settings.max_retries = 2
    settings.retry_delay_seconds = 1
    return settings


@pytest.fixture
def sample_job_context():
    """샘플 JobContext 픽스처"""
    return JobContext(
        job_id="test_job_123",
        user_id="test_user_456",
        s3_bucket="test-video-bucket",
        s3_key="videos/test_user_456/test_job_123.mp4",
        local_video_path="/tmp/test_job_123.mp4",
        local_audio_path="/tmp/test_job_123.wav",
        transcript="안녕하세요. 이것은 테스트 음성입니다.",
        summary="테스트 음성에 대한 요약입니다.",
        created_at=datetime.now()
    )


@pytest.fixture
def sample_sqs_message():
    """샘플 SQS S3 Event 메시지"""
    return {
        "Records": [
            {
                "eventTime": "2025-11-22T05:01:23.000Z",
                "s3": {
                    "bucket": {"name": "test-video-bucket"},
                    "object": {
                        "key": "videos/test_user_456/test_job_123.mp4",
                        "size": 12345678
                    }
                }
            }
        ]
    }


@pytest.fixture
def sample_sqs_message_encoded():
    """URL 인코딩된 키를 가진 SQS 메시지"""
    return {
        "Records": [
            {
                "eventTime": "2025-11-22T05:01:23.000Z",
                "s3": {
                    "bucket": {"name": "test-video-bucket"},
                    "object": {
                        "key": "videos%2Ftest_user_456%2Ftest_job_123.mp4",
                        "size": 12345678
                    }
                }
            }
        ]
    }


@pytest.fixture
def empty_sqs_message():
    """Records가 없는 테스트 메시지"""
    return {"Records": []}


@pytest.fixture
def temp_video_file():
    """임시 테스트 비디오 파일"""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        # 더미 비디오 데이터 (실제로는 FFmpeg 테스트용 최소 바이너리)
        f.write(b"dummy video content for testing")
        temp_path = f.name
    
    yield temp_path
    
    # 정리
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def temp_audio_file():
    """임시 테스트 오디오 파일"""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        # 더미 오디오 데이터 (1KB 이상)
        data_size = 1024  # 1KB 데이터
        total_size = 36 + data_size  # 헤더 36바이트 + 데이터
        
        # WAV 헤더 (최소 유효한 WAV 파일)
        wav_header = (
            b'RIFF'
            + (total_size - 8).to_bytes(4, 'little')  # 파일 크기 - 8
            + b'WAVE'
            + b'fmt '
            + b'\x10\x00\x00\x00'  # fmt 청크 크기
            + b'\x01\x00'          # 오디오 포맷 (1 = PCM)
            + b'\x01\x00'          # 채널 수 (1 = 모노)
            + b'\x40\x3F\x00\x00'  # 샘플레이트 (16000 Hz)
            + b'\x80\x7E\x00\x00'  # 바이트레이트
            + b'\x02\x00'          # 블록 align
            + b'\x10\x00'          # 비트 깊이 (16비트)
            + b'data'
            + data_size.to_bytes(4, 'little')  # 데이터 크기
        )
        f.write(wav_header)
        # 더미 오디오 데이터 추가 (1KB)
        f.write(b'\x00' * data_size)
        temp_path = f.name
    
    yield temp_path
    
    # 정리
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def mock_boto3_client():
    """Mock AWS 클라이언트"""
    mock_client = Mock()
    
    # SQS 메서드 모킹
    mock_client.receive_message.return_value = {
        'Messages': [{
            'MessageId': 'test-message-id',
            'ReceiptHandle': 'test-receipt-handle',
            'Body': '{"Records":[{"s3":{"bucket":{"name":"test-bucket"},"object":{"key":"test-key"}}}]}'
        }]
    }
    mock_client.delete_message.return_value = {}
    
    # S3 메서드 모킹
    mock_client.download_file.return_value = None
    mock_client.put_object.return_value = {'ETag': '"test-etag"'}
    
    return mock_client


@pytest.fixture
def mock_httpx_client():
    """Mock HTTP 클라이언트"""
    mock_client = Mock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"text": "테스트 음성 변환 결과"}
    mock_response.raise_for_status.return_value = None
    mock_client.post.return_value = mock_response
    mock_client.get.return_value = mock_response
    return mock_client


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """모든 테스트에 자동 적용되는 환경 설정"""
    # 로그 레벨을 WARNING으로 설정하여 테스트 출력 정리
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    
    # 테스트 환경변수 설정
    test_env_vars = {
        "APP_ENV": "test",
        "AWS_REGION": "ap-northeast-2",
        "VIDEO_BUCKET_NAME": "test-video-bucket",
        "SQS_QUEUE_URL": "https://sqs.ap-northeast-2.amazonaws.com/123456789012/test-queue",
        "BACKEND_BASE_URL": "https://test-backend.com",
        "BACKEND_INTERNAL_TOKEN": "test-token",
        "CLOVA_API_KEY_ID": "test-clova-id",
        "CLOVA_API_KEY": "test-clova-key",
        "CLAUDE_API_KEY": "test-claude-key"
    }
    
    for key, value in test_env_vars.items():
        monkeypatch.setenv(key, value)