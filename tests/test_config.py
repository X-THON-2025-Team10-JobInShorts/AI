import pytest
import os
from unittest.mock import patch
from pydantic import ValidationError

from src.config import Settings, validate_required_settings


class TestSettings:
    """Settings 설정 테스트"""
    
    def test_settings_with_env_vars(self):
        """환경변수로 설정 테스트"""
        test_env = {
            'APP_ENV': 'production',
            'AWS_REGION': 'us-west-2',
            'VIDEO_BUCKET_NAME': 'my-video-bucket',
            'SQS_QUEUE_URL': 'https://sqs.us-west-2.amazonaws.com/123456789012/my-queue',
            'BACKEND_BASE_URL': 'https://my-backend.com',
            'CLAUDE_API_URL': 'https://api.anthropic.com/v1/messages',
            'CLAUDE_MODEL': 'claude-3-sonnet',
            'CLAUDE_MAX_TOKENS': '3000',
            'MAX_RETRIES': '5'
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            settings = Settings()
            
            assert settings.app_env == 'production'
            assert settings.aws_region == 'us-west-2'
            assert settings.video_bucket_name == 'my-video-bucket'
            assert settings.sqs_queue_url == 'https://sqs.us-west-2.amazonaws.com/123456789012/my-queue'
            assert settings.backend_base_url == 'https://my-backend.com'
            assert settings.claude_api_url == 'https://api.anthropic.com/v1/messages'
            assert settings.claude_model == 'claude-3-sonnet'
            assert settings.claude_max_tokens == 3000
            assert settings.max_retries == 5
    
    def test_settings_default_values(self):
        """기본값 테스트"""
        # 환경변수 없이 기본값만 사용
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
            
            assert settings.app_env == 'dev'
            assert settings.aws_region == 'ap-northeast-2'
            assert settings.video_bucket_name == 'shortform-video-bucket'
            assert settings.sqs_wait_time_seconds == 10
            assert settings.sqs_visibility_timeout_seconds == 90
            assert settings.claude_max_tokens == 2000
            assert settings.max_retries == 3
            assert settings.retry_delay_seconds == 5
    
    def test_sqs_url_validation_valid(self):
        """유효한 SQS URL 검증 테스트"""
        test_env = {
            'SQS_QUEUE_URL': 'https://sqs.ap-northeast-2.amazonaws.com/123456789012/test-queue'
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            settings = Settings()
            assert settings.sqs_queue_url == test_env['SQS_QUEUE_URL']
    
    def test_sqs_url_validation_invalid(self):
        """잘못된 SQS URL 검증 테스트"""
        test_env = {
            'SQS_QUEUE_URL': 'https://invalid-url.com/queue'
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            assert "Invalid SQS Queue URL format" in str(exc_info.value)
    
    def test_backend_url_validation_valid(self):
        """유효한 Backend URL 검증 테스트"""
        test_cases = [
            'https://backend.example.com',
            'http://localhost:8000',
            'https://api.company.internal'
        ]
        
        for url in test_cases:
            test_env = {'BACKEND_BASE_URL': url}
            with patch.dict(os.environ, test_env, clear=False):
                settings = Settings()
                assert settings.backend_base_url == url
    
    def test_backend_url_validation_invalid(self):
        """잘못된 Backend URL 검증 테스트"""
        test_cases = [
            'ftp://backend.com',
            'backend.com',
            'not-a-url'
        ]
        
        for invalid_url in test_cases:
            test_env = {'BACKEND_BASE_URL': invalid_url}
            with patch.dict(os.environ, test_env, clear=False):
                with pytest.raises(ValidationError) as exc_info:
                    Settings()
                
                assert "Invalid Backend URL format" in str(exc_info.value)
    
    def test_claude_url_validation_valid(self):
        """유효한 Claude API URL 검증 테스트"""
        test_env = {
            'CLAUDE_API_URL': 'https://api.anthropic.com/v1/messages'
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            settings = Settings()
            assert settings.claude_api_url == test_env['CLAUDE_API_URL']
    
    def test_claude_url_validation_invalid(self):
        """잘못된 Claude API URL 검증 테스트"""
        test_cases = [
            'https://api.openai.com/v1/chat',
            'https://example.com/api',
            'not-anthropic-url'
        ]
        
        for invalid_url in test_cases:
            test_env = {'CLAUDE_API_URL': invalid_url}
            with patch.dict(os.environ, test_env, clear=False):
                with pytest.raises(ValidationError) as exc_info:
                    Settings()
                
                assert "Invalid Claude API URL format" in str(exc_info.value)
    
    def test_integer_conversion(self):
        """정수 변환 테스트"""
        test_env = {
            'SQS_WAIT_TIME_SECONDS': '15',
            'SQS_VISIBILITY_TIMEOUT_SECONDS': '120',
            'CLAUDE_MAX_TOKENS': '4000',
            'MAX_RETRIES': '10',
            'RETRY_DELAY_SECONDS': '3'
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            settings = Settings()
            
            assert settings.sqs_wait_time_seconds == 15
            assert settings.sqs_visibility_timeout_seconds == 120
            assert settings.claude_max_tokens == 4000
            assert settings.max_retries == 10
            assert settings.retry_delay_seconds == 3
    
    def test_case_insensitive_config(self):
        """대소문자 구분하지 않는 설정 테스트"""
        test_env = {
            'app_env': 'PRODUCTION',  # 소문자 키
            'AWS_REGION': 'us-east-1'  # 대문자 키
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            settings = Settings()
            
            # case_sensitive = False이므로 정상 동작
            assert settings.app_env in ['PRODUCTION', 'production']
            assert settings.aws_region == 'us-east-1'


class TestValidateRequiredSettings:
    """validate_required_settings 함수 테스트"""
    
    def test_validate_required_settings_success(self):
        """필수 설정 검증 성공 테스트"""
        test_env = {
            'SQS_QUEUE_URL': 'https://sqs.ap-northeast-2.amazonaws.com/123456789012/test-queue',
            'BACKEND_BASE_URL': 'https://backend.example.com',
            'BACKEND_INTERNAL_TOKEN': 'test-token-123',
            'CLOVA_API_KEY_ID': 'clova-key-id',
            'CLOVA_API_KEY': 'clova-api-key',
            'CLAUDE_API_KEY': 'claude-api-key'
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            # 새로운 설정 인스턴스로 검증
            test_settings = Settings()
            validate_required_settings(test_settings)
    
    def test_validate_required_settings_missing_single(self):
        """단일 필수 설정 누락 테스트"""
        # CLOVA_API_KEY를 명시적으로 제거
        test_env = {
            'SQS_QUEUE_URL': 'https://sqs.ap-northeast-2.amazonaws.com/123456789012/test-queue',
            'BACKEND_BASE_URL': 'https://backend.example.com',
            'BACKEND_INTERNAL_TOKEN': 'test-token-123',
            'CLOVA_API_KEY_ID': 'clova-key-id',
            'CLAUDE_API_KEY': 'claude-api-key',
            'CLOVA_API_KEY': ''  # 빈 값으로 설정
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            with pytest.raises(ValueError) as exc_info:
                test_settings = Settings()
                validate_required_settings(test_settings)
            
            assert "CLOVA_API_KEY" in str(exc_info.value)
            assert "필수 환경 변수가 누락되었습니다" in str(exc_info.value)
    
    def test_validate_required_settings_missing_multiple(self):
        """복수 필수 설정 누락 테스트"""
        test_env = {
            'SQS_QUEUE_URL': 'https://sqs.ap-northeast-2.amazonaws.com/123456789012/test-queue',
            'BACKEND_BASE_URL': 'https://backend.example.com',
            'BACKEND_INTERNAL_TOKEN': '',  # 빈 값으로 설정
            'CLOVA_API_KEY_ID': '',
            'CLOVA_API_KEY': '',
            'CLAUDE_API_KEY': ''
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            with pytest.raises(ValueError) as exc_info:
                test_settings = Settings()
                validate_required_settings(test_settings)
            
            error_message = str(exc_info.value)
            assert "BACKEND_INTERNAL_TOKEN" in error_message
            assert "CLOVA_API_KEY_ID" in error_message
            assert "CLOVA_API_KEY" in error_message
            assert "CLAUDE_API_KEY" in error_message
    
    def test_validate_required_settings_empty_values(self):
        """빈 값 설정 테스트"""
        test_env = {
            'SQS_QUEUE_URL': 'https://sqs.ap-northeast-2.amazonaws.com/123456789012/test-queue',
            'BACKEND_BASE_URL': 'https://backend.example.com',
            'BACKEND_INTERNAL_TOKEN': '',  # 빈 문자열
            'CLOVA_API_KEY_ID': 'clova-key-id',
            'CLOVA_API_KEY': 'clova-api-key',
            'CLAUDE_API_KEY': '   '  # 공백만
        }
        
        with patch.dict(os.environ, test_env, clear=False):
            with pytest.raises(ValueError) as exc_info:
                validate_required_settings()
            
            error_message = str(exc_info.value)
            # 빈 값도 누락으로 처리되어야 함
            assert "BACKEND_INTERNAL_TOKEN" in error_message or "CLAUDE_API_KEY" in error_message