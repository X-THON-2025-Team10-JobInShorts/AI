import pytest
from unittest.mock import Mock, patch
import httpx

from src.stt_client import ClovaSTTClient
from src.models import JobContext


class TestClovaSTTClient:
    """ClovaSTTClient 테스트"""
    
    def test_stt_client_initialization(self, mock_settings):
        """STT 클라이언트 초기화 테스트"""
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            
            assert client.api_url == mock_settings.clova_stt_url
            assert client.api_key_id == mock_settings.clova_api_key_id
            assert client.api_key == mock_settings.clova_api_key
            assert client.max_retries == mock_settings.max_retries
            assert client.retry_delay == mock_settings.retry_delay_seconds
    
    @patch('src.stt_client.httpx.Client')
    def test_transcribe_audio_success(self, mock_httpx_client, mock_settings, sample_job_context, temp_audio_file):
        """음성 변환 성공 테스트"""
        sample_job_context.local_audio_path = temp_audio_file
        
        # Mock HTTP 응답
        mock_response = Mock()
        mock_response.json.return_value = {"text": "안녕하세요. 테스트 음성입니다."}
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            result = client.transcribe_audio(sample_job_context)
        
        assert result == "안녕하세요. 테스트 음성입니다."
        assert sample_job_context.transcript == "안녕하세요. 테스트 음성입니다."
        
        # API 호출 확인
        mock_client_instance.post.assert_called_once()
        call_args = mock_client_instance.post.call_args
        
        # URL 확인
        assert call_args[0][0] == mock_settings.clova_stt_url
        
        # Headers 확인
        headers = call_args[1]['headers']
        assert headers['X-NCP-APIGW-API-KEY-ID'] == mock_settings.clova_api_key_id
        assert headers['X-NCP-APIGW-API-KEY'] == mock_settings.clova_api_key
        assert headers['Content-Type'] == 'application/octet-stream'
    
    def test_transcribe_audio_no_file_path(self, mock_settings, sample_job_context):
        """오디오 파일 경로 없음 테스트"""
        sample_job_context.local_audio_path = None
        
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            
            with pytest.raises(ValueError, match="Audio file path not found"):
                client.transcribe_audio(sample_job_context)
    
    def test_transcribe_audio_file_not_found(self, mock_settings, sample_job_context):
        """오디오 파일 존재하지 않음 테스트"""
        sample_job_context.local_audio_path = "/tmp/nonexistent.wav"
        
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            
            with pytest.raises(FileNotFoundError):
                client.transcribe_audio(sample_job_context)
    
    @patch('src.stt_client.httpx.Client')
    @patch('time.sleep')  # sleep 모킹으로 테스트 속도 향상
    def test_transcribe_audio_retry_on_timeout(self, mock_sleep, mock_httpx_client, mock_settings, sample_job_context, temp_audio_file):
        """타임아웃 시 재시도 테스트"""
        sample_job_context.local_audio_path = temp_audio_file
        
        # 첫 번째, 두 번째는 타임아웃, 세 번째는 성공
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = [
            httpx.TimeoutException("Request timeout"),
            httpx.TimeoutException("Request timeout"),
            Mock(json=lambda: {"text": "성공한 변환 결과"}, raise_for_status=lambda: None)
        ]
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            result = client.transcribe_audio(sample_job_context)
        
        assert result == "성공한 변환 결과"
        # 3번 호출되었는지 확인 (2번 실패, 1번 성공)
        assert mock_client_instance.post.call_count == 3
    
    @patch('src.stt_client.httpx.Client')
    @patch('time.sleep')
    def test_transcribe_audio_max_retries_exceeded(self, mock_sleep, mock_httpx_client, mock_settings, sample_job_context, temp_audio_file):
        """최대 재시도 횟수 초과 테스트"""
        sample_job_context.local_audio_path = temp_audio_file
        
        # 모든 시도에서 타임아웃
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = httpx.TimeoutException("Request timeout")
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            
            with pytest.raises(Exception, match="timeout"):
                client.transcribe_audio(sample_job_context)
        
        # max_retries + 1 번 호출되었는지 확인
        expected_calls = mock_settings.max_retries + 1
        assert mock_client_instance.post.call_count == expected_calls
    
    @patch('src.stt_client.httpx.Client')
    def test_transcribe_audio_http_error_429(self, mock_httpx_client, mock_settings, sample_job_context, temp_audio_file):
        """Rate limit 에러 테스트"""
        sample_job_context.local_audio_path = temp_audio_file
        
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        
        http_error = httpx.HTTPStatusError(
            "Rate limit exceeded", request=Mock(), response=mock_response
        )
        
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = http_error
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            
            with pytest.raises(Exception, match="rate limit"):
                client.transcribe_audio(sample_job_context)
    
    @patch('src.stt_client.httpx.Client')
    def test_transcribe_audio_empty_response(self, mock_httpx_client, mock_settings, sample_job_context, temp_audio_file):
        """빈 응답 테스트"""
        sample_job_context.local_audio_path = temp_audio_file
        
        mock_response = Mock()
        mock_response.json.return_value = {"text": ""}  # 빈 텍스트
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            
            with pytest.raises(Exception, match="Empty transcript"):
                client.transcribe_audio(sample_job_context)
    
    def test_classify_error(self, mock_settings):
        """에러 분류 테스트"""
        with patch('src.stt_client.settings', mock_settings):
            client = ClovaSTTClient()
            
            # 타임아웃 에러
            timeout_error = Exception("timeout occurred")
            assert client._classify_error(timeout_error) == "STT_TIMEOUT"
            
            # Rate limit 에러
            rate_limit_error = Exception("rate limit exceeded")
            assert client._classify_error(rate_limit_error) == "STT_TIMEOUT"
            
            # 응답 형식 에러
            format_error = Exception("invalid response format")
            assert client._classify_error(format_error) == "STT_BAD_RESPONSE"
            
            # 빈 응답 에러
            empty_error = Exception("empty transcript received")
            assert client._classify_error(empty_error) == "STT_BAD_RESPONSE"
            
            # 기타 에러
            other_error = Exception("unknown error")
            assert client._classify_error(other_error) == "STT_BAD_RESPONSE"
    
    def test_validate_audio_file_valid(self, temp_audio_file):
        """유효한 오디오 파일 검증 테스트"""
        with patch('src.stt_client.settings'):
            client = ClovaSTTClient()
            result = client.validate_audio_file(temp_audio_file)
            
            assert result is True
    
    def test_validate_audio_file_not_exists(self):
        """존재하지 않는 오디오 파일 검증 테스트"""
        with patch('src.stt_client.settings'):
            client = ClovaSTTClient()
            result = client.validate_audio_file("/tmp/nonexistent.wav")
            
            assert result is False
    
    def test_validate_audio_file_too_small(self, temp_audio_file):
        """너무 작은 파일 검증 테스트"""
        # 파일 크기를 매우 작게 만들기
        with open(temp_audio_file, 'wb') as f:
            f.write(b'small')  # 5 bytes (< 1KB)
        
        with patch('src.stt_client.settings'):
            client = ClovaSTTClient()
            result = client.validate_audio_file(temp_audio_file)
            
            assert result is False
    
    def test_validate_audio_file_invalid_format(self):
        """잘못된 형식 파일 검증 테스트"""
        import tempfile
        
        # 텍스트 파일 생성 (WAV가 아님)
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"this is not a wav file")
            temp_path = f.name
        
        try:
            with patch('src.stt_client.settings'):
                client = ClovaSTTClient()
                result = client.validate_audio_file(temp_path)
                
                assert result is False
        finally:
            import os
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass