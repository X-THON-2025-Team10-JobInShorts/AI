import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import httpx

from src.callback_client import BackendCallbackClient
from src.models import JobContext, CallbackRequest


class TestBackendCallbackClient:
    """BackendCallbackClient 테스트"""
    
    def test_callback_client_initialization(self, mock_settings):
        """CallbackClient 초기화 테스트"""
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            
            assert client.base_url == mock_settings.backend_base_url
            assert client.internal_token == mock_settings.backend_internal_token
            assert client.max_retries == mock_settings.max_retries
    
    @patch('src.callback_client.httpx.Client')
    def test_send_success_callback(self, mock_httpx_client, mock_settings, sample_job_context):
        """성공 콜백 전송 테스트"""
        # Mock HTTP 응답
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result = client.send_success_callback(
                sample_job_context,
                result_s3_key="results/test_user_456/test_job_123.json",
                processing_time_ms=5000
            )
        
        assert result is True
        mock_client_instance.post.assert_called_once()
        
        # 호출된 인자 확인
        call_args = mock_client_instance.post.call_args
        assert mock_settings.backend_base_url in call_args[0][0]  # URL
        assert "test_job_123" in call_args[0][0]  # job_id in URL
        
        # Headers 확인
        headers = call_args[1]['headers']
        assert headers['Content-Type'] == 'application/json'
        assert headers['X-Internal-Token'] == mock_settings.backend_internal_token
        assert 'User-Agent' in headers
        
        # Request body 확인
        request_data = call_args[1]['json']
        assert request_data['status'] == 'DONE'
        assert request_data['s3_bucket'] == sample_job_context.s3_bucket
        assert request_data['s3_key'] == sample_job_context.s3_key
        assert request_data['transcript'] == sample_job_context.transcript
        assert request_data['summary'] == sample_job_context.summary
        assert request_data['result_s3_key'] == "results/test_user_456/test_job_123.json"
        assert request_data['meta']['duration_ms'] == 5000
        assert request_data['meta']['model'] == mock_settings.claude_model
        assert request_data['meta']['stt_engine'] == 'clova'
    
    @patch('src.callback_client.httpx.Client')
    def test_send_failure_callback(self, mock_httpx_client, mock_settings, sample_job_context):
        """실패 콜백 전송 테스트"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result = client.send_failure_callback(
                sample_job_context,
                error_code="STT_TIMEOUT",
                error_message="Clova STT request timed out"
            )
        
        assert result is True
        
        # Request body 확인
        call_args = mock_client_instance.post.call_args
        request_data = call_args[1]['json']
        assert request_data['status'] == 'FAILED'
        assert request_data['error_code'] == 'STT_TIMEOUT'
        assert request_data['error_message'] == 'Clova STT request timed out'
        assert 'transcript' not in request_data or request_data['transcript'] is None
        assert 'summary' not in request_data or request_data['summary'] is None
    
    @patch('src.callback_client.httpx.Client')
    def test_send_callback_http_error_4xx(self, mock_httpx_client, mock_settings, sample_job_context):
        """4xx HTTP 에러 테스트 (재시도 안함)"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": "Bad Request"}
        mock_response.text = "Bad Request"
        
        http_error = httpx.HTTPStatusError(
            "Bad Request", request=Mock(), response=mock_response
        )
        
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = http_error
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result = client.send_failure_callback(
                sample_job_context,
                error_code="TEST_ERROR",
                error_message="Test error message"
            )
        
        assert result is False
        # 4xx 에러는 재시도하지 않으므로 1번만 호출
        assert mock_client_instance.post.call_count == 1
    
    @patch('src.callback_client.httpx.Client')
    def test_send_callback_http_error_5xx_retry(self, mock_httpx_client, mock_settings, sample_job_context):
        """5xx HTTP 에러 테스트 (재시도)"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"message": "Internal Server Error"}
        mock_response.text = "Internal Server Error"
        
        http_error = httpx.HTTPStatusError(
            "Internal Server Error", request=Mock(), response=mock_response
        )
        
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = http_error
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.callback_client.settings', mock_settings):
            # retry_delay를 0으로 설정하여 테스트 속도 향상
            with patch('time.sleep'):
                client = BackendCallbackClient()
                result = client.send_failure_callback(
                    sample_job_context,
                    error_code="TEST_ERROR", 
                    error_message="Test error message"
                )
        
        assert result is False
        # max_retries + 1 번 호출되었는지 확인
        expected_calls = mock_settings.max_retries + 1
        assert mock_client_instance.post.call_count == expected_calls
    
    @patch('src.callback_client.boto3')
    def test_upload_result_to_s3_success(self, mock_boto3, mock_settings, sample_job_context):
        """S3에 결과 업로드 성공 테스트"""
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.put_object.return_value = {'ETag': '"test-etag"'}
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result_key = client.upload_result_to_s3(sample_job_context)
        
        expected_key = f"results/{sample_job_context.user_id}/{sample_job_context.job_id}.json"
        assert result_key == expected_key
        
        # S3 put_object 호출 확인
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args
        
        assert call_args[1]['Bucket'] == mock_settings.result_bucket_name
        assert call_args[1]['Key'] == expected_key
        assert call_args[1]['ContentType'] == 'application/json'
        
        # 업로드된 JSON 데이터 확인
        uploaded_data = json.loads(call_args[1]['Body'].decode('utf-8'))
        assert uploaded_data['job_id'] == sample_job_context.job_id
        assert uploaded_data['user_id'] == sample_job_context.user_id
        assert uploaded_data['transcript'] == sample_job_context.transcript
        assert uploaded_data['summary'] == sample_job_context.summary
        assert uploaded_data['metadata']['model'] == mock_settings.claude_model
        assert uploaded_data['metadata']['stt_engine'] == 'clova'
    
    @patch('src.callback_client.boto3')
    def test_upload_result_to_s3_no_data(self, mock_boto3, mock_settings):
        """데이터가 없을 때 S3 업로드 테스트"""
        # transcript, summary가 모두 None인 JobContext
        empty_job_context = JobContext(
            job_id="test_job",
            s3_bucket="test-bucket",
            s3_key="test-key"
        )
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result_key = client.upload_result_to_s3(empty_job_context)
        
        assert result_key is None
        # S3 클라이언트가 생성되지 않아야 함
        mock_boto3.client.assert_not_called()
    
    @patch('src.callback_client.boto3')
    def test_upload_result_to_s3_error(self, mock_boto3, mock_settings, sample_job_context):
        """S3 업로드 실패 테스트"""
        from botocore.exceptions import ClientError
        
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.put_object.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied'}}, 'PutObject'
        )
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result_key = client.upload_result_to_s3(sample_job_context)
        
        assert result_key is None  # 실패 시 None 반환
    
    @patch('src.callback_client.httpx.Client')
    def test_health_check_success(self, mock_httpx_client, mock_settings):
        """헬스체크 성공 테스트"""
        mock_response = Mock()
        mock_response.status_code = 200
        
        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result = client.health_check()
        
        assert result is True
        
        # 올바른 URL로 GET 요청이 호출되었는지 확인
        expected_url = f"{mock_settings.backend_base_url}/health"
        mock_client_instance.get.assert_called_once_with(
            expected_url,
            headers={'X-Internal-Token': mock_settings.backend_internal_token}
        )
    
    @patch('src.callback_client.httpx.Client')
    def test_health_check_failure(self, mock_httpx_client, mock_settings):
        """헬스체크 실패 테스트"""
        mock_client_instance = Mock()
        mock_client_instance.get.side_effect = httpx.RequestError("Connection failed")
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result = client.health_check()
        
        assert result is False
    
    @patch('src.callback_client.httpx.Client')
    def test_health_check_wrong_status_code(self, mock_httpx_client, mock_settings):
        """헬스체크 잘못된 상태 코드 테스트"""
        mock_response = Mock()
        mock_response.status_code = 503  # Service Unavailable
        
        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.callback_client.settings', mock_settings):
            client = BackendCallbackClient()
            result = client.health_check()
        
        assert result is False