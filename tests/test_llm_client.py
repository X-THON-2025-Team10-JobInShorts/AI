import pytest
from unittest.mock import Mock, patch
import httpx

from src.llm_client import ClaudeClient
from src.models import JobContext


class TestClaudeClient:
    """ClaudeClient 테스트"""
    
    def test_llm_client_initialization(self, mock_settings):
        """LLM 클라이언트 초기화 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            assert client.api_url == mock_settings.claude_api_url
            assert client.api_key == mock_settings.claude_api_key
            assert client.model == mock_settings.claude_model
            assert client.max_tokens == mock_settings.claude_max_tokens
            assert client.max_retries == mock_settings.max_retries
            assert client.retry_delay == mock_settings.retry_delay_seconds
    
    @patch('src.llm_client.httpx.Client')
    def test_generate_summary_success(self, mock_httpx_client, mock_settings, sample_job_context):
        """요약 생성 성공 테스트"""
        sample_job_context.transcript = "안녕하세요. 오늘은 AI에 대해 이야기하겠습니다. 인공지능은 매우 흥미로운 기술입니다."
        
        # Mock HTTP 응답
        mock_response = Mock()
        mock_response.json.return_value = {
            "content": [{"text": "이 영상은 AI 기술에 대한 소개를 다룹니다. 인공지능의 흥미로운 측면들을 설명합니다."}]
        }
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            result = client.generate_summary(sample_job_context)
        
        expected_summary = "이 영상은 AI 기술에 대한 소개를 다룹니다. 인공지능의 흥미로운 측면들을 설명합니다."
        assert result == expected_summary
        assert sample_job_context.summary == expected_summary
        
        # API 호출 확인
        mock_client_instance.post.assert_called_once()
        call_args = mock_client_instance.post.call_args
        
        # URL 확인
        assert call_args[0][0] == mock_settings.claude_api_url
        
        # Headers 확인
        headers = call_args[1]['headers']
        assert headers['Content-Type'] == 'application/json'
        assert headers['x-api-key'] == mock_settings.claude_api_key
        assert headers['anthropic-version'] == '2023-06-01'
        
        # Request body 확인
        request_data = call_args[1]['json']
        assert request_data['model'] == mock_settings.claude_model
        assert request_data['max_tokens'] == mock_settings.claude_max_tokens
        assert len(request_data['messages']) == 1
        assert request_data['messages'][0]['role'] == 'user'
        assert sample_job_context.transcript in request_data['messages'][0]['content']
    
    def test_generate_summary_no_transcript(self, mock_settings, sample_job_context):
        """트랜스크립트 없음 테스트"""
        sample_job_context.transcript = None
        
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            with pytest.raises(ValueError, match="Transcript not found"):
                client.generate_summary(sample_job_context)
    
    @patch('src.llm_client.httpx.Client')
    @patch('time.sleep')
    def test_generate_summary_retry_on_error(self, mock_sleep, mock_httpx_client, mock_settings, sample_job_context):
        """에러 시 재시도 테스트"""
        sample_job_context.transcript = "테스트 트랜스크립트"
        
        # 첫 번째, 두 번째는 실패, 세 번째는 성공
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = [
            httpx.RequestError("Connection failed"),
            httpx.RequestError("Connection failed"),
            Mock(
                json=lambda: {"content": [{"text": "성공한 요약"}]},
                raise_for_status=lambda: None
            )
        ]
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            result = client.generate_summary(sample_job_context)
        
        assert result == "성공한 요약"
        # 3번 호출되었는지 확인
        assert mock_client_instance.post.call_count == 3
    
    @patch('src.llm_client.httpx.Client')
    def test_generate_summary_rate_limit(self, mock_httpx_client, mock_settings, sample_job_context):
        """Rate limit 에러 테스트"""
        sample_job_context.transcript = "테스트 트랜스크립트"
        
        mock_response = Mock()
        mock_response.status_code = 429
        
        http_error = httpx.HTTPStatusError(
            "Rate limit exceeded", request=Mock(), response=mock_response
        )
        
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = http_error
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            with pytest.raises(Exception, match="rate limit"):
                client.generate_summary(sample_job_context)
    
    @patch('src.llm_client.httpx.Client')
    def test_generate_summary_auth_error(self, mock_httpx_client, mock_settings, sample_job_context):
        """인증 에러 테스트"""
        sample_job_context.transcript = "테스트 트랜스크립트"
        
        mock_response = Mock()
        mock_response.status_code = 401
        
        http_error = httpx.HTTPStatusError(
            "Unauthorized", request=Mock(), response=mock_response
        )
        
        mock_client_instance = Mock()
        mock_client_instance.post.side_effect = http_error
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            with pytest.raises(Exception, match="authentication failed"):
                client.generate_summary(sample_job_context)
    
    @patch('src.llm_client.httpx.Client')
    def test_generate_summary_invalid_response_format(self, mock_httpx_client, mock_settings, sample_job_context):
        """잘못된 응답 형식 테스트"""
        sample_job_context.transcript = "테스트 트랜스크립트"
        
        mock_response = Mock()
        mock_response.json.return_value = {"invalid": "format"}  # content 필드 없음
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            with pytest.raises(Exception, match="Invalid response format"):
                client.generate_summary(sample_job_context)
    
    @patch('src.llm_client.httpx.Client')
    def test_generate_summary_empty_content(self, mock_httpx_client, mock_settings, sample_job_context):
        """빈 컨텐츠 응답 테스트"""
        sample_job_context.transcript = "테스트 트랜스크립트"
        
        mock_response = Mock()
        mock_response.json.return_value = {"content": [{"text": ""}]}  # 빈 텍스트
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
        
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            with pytest.raises(Exception, match="Empty summary"):
                client.generate_summary(sample_job_context)
    
    def test_classify_error(self, mock_settings):
        """에러 분류 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            # 타임아웃 에러
            timeout_error = Exception("timeout occurred")
            assert client._classify_error(timeout_error) == "LLM_TIMEOUT"
            
            # Rate limit 에러
            rate_limit_error = Exception("rate limit exceeded")
            assert client._classify_error(rate_limit_error) == "LLM_TIMEOUT"
            
            # 인증 에러
            auth_error = Exception("authentication failed")
            assert client._classify_error(auth_error) == "LLM_BAD_RESPONSE"
            
            # 형식 에러
            format_error = Exception("invalid format")
            assert client._classify_error(format_error) == "LLM_BAD_RESPONSE"
            
            # 기타 에러
            other_error = Exception("unknown error")
            assert client._classify_error(other_error) == "LLM_BAD_RESPONSE"
    
    def test_validate_transcript_valid(self, mock_settings):
        """유효한 트랜스크립트 검증 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            valid_transcript = "이것은 충분히 긴 유효한 트랜스크립트입니다. 최소 길이를 만족합니다."
            assert client.validate_transcript(valid_transcript) is True
    
    def test_validate_transcript_invalid(self, mock_settings):
        """유효하지 않은 트랜스크립트 검증 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            # None
            assert client.validate_transcript(None) is False
            
            # 빈 문자열
            assert client.validate_transcript("") is False
            
            # 너무 짧음
            assert client.validate_transcript("짧음") is False
            
            # 타입 오류
            assert client.validate_transcript(123) is False
            
            # 너무 긴 문자열
            very_long_text = "x" * 100001
            assert client.validate_transcript(very_long_text) is False
    
    def test_truncate_transcript_if_needed_no_truncation(self, mock_settings):
        """트랜스크립트 길이가 충분히 짧을 때 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            short_text = "이것은 짧은 텍스트입니다."
            result = client.truncate_transcript_if_needed(short_text)
            
            assert result == short_text
    
    def test_truncate_transcript_if_needed_with_truncation(self, mock_settings):
        """트랜스크립트 잘라내기 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            # 긴 텍스트 생성 (문장 단위로)
            long_text = ". ".join([f"문장 번호 {i}입니다" for i in range(1000)]) + "."
            
            result = client.truncate_transcript_if_needed(long_text, max_length=100)
            
            assert len(result) <= 100
            assert result.endswith(".")  # 문장이 완전하게 끝나야 함
    
    def test_truncate_transcript_edge_case(self, mock_settings):
        """트랜스크립트 잘라내기 엣지 케이스 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            # 문장 구분자가 없는 긴 텍스트
            long_text_no_periods = "x" * 1000
            
            result = client.truncate_transcript_if_needed(long_text_no_periods, max_length=100)
            
            assert len(result) <= 100
    
    def test_summary_prompt_template(self, mock_settings):
        """프롬프트 템플릿 테스트"""
        with patch('src.llm_client.settings', mock_settings):
            client = ClaudeClient()
            
            test_transcript = "테스트 음성 내용입니다."
            prompt = client.summary_prompt_template.format(transcript=test_transcript)
            
            assert "다음은 동영상에서 추출한 음성 텍스트입니다" in prompt
            assert test_transcript in prompt
            assert "요약:" in prompt
            assert "핵심 내용과 메시지를 파악" in prompt