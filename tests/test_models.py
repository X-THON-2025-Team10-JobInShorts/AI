import pytest
from datetime import datetime
from pydantic import ValidationError

from src.models import JobContext, CallbackRequest, SQSMessage, S3EventRecord


class TestJobContext:
    """JobContext 모델 테스트"""
    
    def test_job_context_creation(self):
        """기본 JobContext 생성 테스트"""
        job = JobContext(
            job_id="test123",
            user_id="user456",
            s3_bucket="test-bucket",
            s3_key="videos/user456/test123.mp4"
        )
        
        assert job.job_id == "test123"
        assert job.user_id == "user456"
        assert job.s3_bucket == "test-bucket"
        assert job.s3_key == "videos/user456/test123.mp4"
        assert job.local_video_path is None
        assert job.local_audio_path is None
        assert job.transcript is None
        assert job.summary is None
        assert isinstance(job.created_at, datetime)
    
    def test_job_context_without_user_id(self):
        """user_id 없이 JobContext 생성 테스트"""
        job = JobContext(
            job_id="test123",
            s3_bucket="test-bucket", 
            s3_key="videos/test123.mp4"
        )
        
        assert job.user_id is None
        assert job.job_id == "test123"
    
    def test_job_context_validation(self):
        """필수 필드 검증 테스트"""
        with pytest.raises(ValidationError):
            JobContext()  # job_id, s3_bucket, s3_key 필수
        
        with pytest.raises(ValidationError):
            JobContext(job_id="test")  # s3_bucket, s3_key 누락


class TestCallbackRequest:
    """CallbackRequest 모델 테스트"""
    
    def test_success_callback_request(self):
        """성공 콜백 요청 테스트"""
        callback = CallbackRequest(
            status="DONE",
            s3_bucket="test-bucket",
            s3_key="test-key",
            transcript="테스트 텍스트",
            summary="테스트 요약",
            result_s3_key="results/test.json",
            meta={"duration_ms": 5000, "model": "claude-3-7-sonnet-latest"}
        )
        
        assert callback.status == "DONE"
        assert callback.transcript == "테스트 텍스트"
        assert callback.summary == "테스트 요약"
        assert callback.meta["duration_ms"] == 5000
        assert callback.error_code is None
        assert callback.error_message is None
    
    def test_failure_callback_request(self):
        """실패 콜백 요청 테스트"""
        callback = CallbackRequest(
            status="FAILED",
            s3_bucket="test-bucket",
            s3_key="test-key",
            error_code="STT_TIMEOUT",
            error_message="STT request timed out"
        )
        
        assert callback.status == "FAILED"
        assert callback.error_code == "STT_TIMEOUT"
        assert callback.error_message == "STT request timed out"
        assert callback.transcript is None
        assert callback.summary is None


class TestSQSMessage:
    """SQS 메시지 모델 테스트"""
    
    def test_sqs_message_parsing(self, sample_sqs_message):
        """SQS 메시지 파싱 테스트"""
        sqs_msg = SQSMessage(**sample_sqs_message)
        
        assert len(sqs_msg.Records) == 1
        
        first_record = sqs_msg.first_record
        assert first_record.get_bucket_name() == "test-video-bucket"
        assert first_record.get_object_key() == "videos/test_user_456/test_job_123.mp4"
    
    def test_s3_event_record_methods(self):
        """S3EventRecord 메서드 테스트"""
        record_data = {
            "eventTime": "2025-11-22T05:01:23.000Z",
            "s3": {
                "bucket": {"name": "my-bucket"},
                "object": {"key": "my/object/key.mp4"}
            }
        }
        
        record = S3EventRecord(**record_data)
        assert record.get_bucket_name() == "my-bucket"
        assert record.get_object_key() == "my/object/key.mp4"
    
    def test_empty_records(self):
        """빈 Records 배열 테스트"""
        with pytest.raises(IndexError):
            # first_record 접근 시 IndexError 발생해야 함
            empty_msg = SQSMessage(Records=[])
            _ = empty_msg.first_record