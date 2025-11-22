import time
import json
import httpx
from typing import Optional, Dict, Any

from .config import settings
from .models import JobContext
from .logger import get_job_logger, LogStage, ErrorCode


class ClaudeClient:
    def __init__(self):
        self.api_url = settings.claude_api_url
        self.api_key = settings.claude_api_key
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens
        self.max_retries = settings.max_retries
        self.retry_delay = settings.retry_delay_seconds
        
        # 요약 생성을 위한 프롬프트 템플릿
        self.summary_prompt_template = """다음은 동영상에서 추출한 음성 텍스트입니다. 
이 내용을 바탕으로 간결하고 유용한 요약을 생성해 주세요.

주요 포인트:
- 핵심 내용과 메시지를 파악
- 중요한 키워드나 주제 강조
- 시청자가 빠르게 이해할 수 있도록 구조화
- 2-3문단 내외로 정리

음성 텍스트:
{transcript}

요약:"""
    
    def generate_summary(self, job_context: JobContext) -> str:
        """
        Claude API를 사용하여 transcript에서 요약을 생성합니다.
        """
        if not job_context.transcript:
            raise ValueError("Transcript not found")
        
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        logger.info("요약 생성 시작", 
                   stage=LogStage.LLM_START,
                   model=self.model,
                   transcript_length=len(job_context.transcript))
        
        for attempt in range(self.max_retries + 1):
            try:
                start_time = time.time()
                summary = self._call_claude_api(job_context.transcript)
                duration_ms = int((time.time() - start_time) * 1000)
                
                logger.info("요약 생성 완료", 
                           stage=LogStage.LLM_DONE,
                           duration_ms=duration_ms,
                           model=self.model,
                           summary_length=len(summary))
                
                job_context.summary = summary
                return summary
                
            except Exception as e:
                logger.warning(f"요약 생성 시도 실패 (시도 {attempt + 1}/{self.max_retries + 1})", 
                              error=str(e))
                
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"재시도 대기", wait_seconds=wait_time)
                    time.sleep(wait_time)
                else:
                    logger.error("요약 생성 최종 실패", 
                               stage=LogStage.LLM_DONE,
                               error=str(e),
                               error_code=self._classify_error(e))
                    raise
    
    def _call_claude_api(self, transcript: str) -> str:
        """
        실제 Claude API 호출
        """
        prompt = self.summary_prompt_template.format(transcript=transcript)
        
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01'
        }
        
        payload = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'messages': [
                {
                    'role': 'user',
                    'content': prompt
                }
            ]
        }
        
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    self.api_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                content = result.get('content', [])
                
                if not content or not isinstance(content, list):
                    raise Exception("Invalid response format from Claude API")
                
                summary = content[0].get('text', '')
                
                if not summary:
                    raise Exception("Empty summary received from Claude API")
                
                return summary.strip()
                
        except httpx.TimeoutException:
            raise Exception("Claude API timeout")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise Exception("Claude API rate limit exceeded")
            elif e.response.status_code == 401:
                raise Exception("Claude API authentication failed")
            elif e.response.status_code >= 500:
                raise Exception(f"Claude API server error: {e.response.status_code}")
            else:
                error_detail = ""
                try:
                    error_data = e.response.json()
                    error_detail = error_data.get('error', {}).get('message', '')
                except:
                    error_detail = e.response.text
                raise Exception(f"Claude API error: {e.response.status_code} - {error_detail}")
        except httpx.RequestError as e:
            raise Exception(f"Claude API request failed: {e}")
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            raise Exception(f"Invalid response format from Claude API: {e}")
        except Exception as e:
            raise Exception(f"Claude API unexpected error: {e}")
    
    def _classify_error(self, error: Exception) -> str:
        """
        에러를 분류하여 에러 코드를 반환합니다.
        """
        error_str = str(error).lower()
        
        if 'timeout' in error_str:
            return ErrorCode.LLM_TIMEOUT
        elif 'rate limit' in error_str:
            return ErrorCode.LLM_TIMEOUT  # rate limit도 timeout으로 분류
        elif any(keyword in error_str for keyword in ['empty', 'invalid', 'format', 'authentication']):
            return ErrorCode.LLM_BAD_RESPONSE
        else:
            return ErrorCode.LLM_BAD_RESPONSE
    
    def validate_transcript(self, transcript: str) -> bool:
        """
        트랜스크립트의 유효성을 검사합니다.
        """
        if not transcript or not isinstance(transcript, str):
            return False
        
        # 최소/최대 길이 확인
        if len(transcript.strip()) < 10:  # 너무 짧음
            return False
        
        if len(transcript) > 100000:  # 너무 길어서 API 제한에 걸릴 수 있음
            return False
        
        return True
    
    def truncate_transcript_if_needed(self, transcript: str, max_length: int = 50000) -> str:
        """
        트랜스크립트가 너무 길면 앞쪽을 잘라냅니다.
        """
        if len(transcript) <= max_length:
            return transcript
        
        # 문장 단위로 자르기
        sentences = transcript.split('. ')
        truncated = []
        current_length = 0
        
        for sentence in sentences:
            if current_length + len(sentence) + 2 <= max_length:  # '. ' 고려
                truncated.append(sentence)
                current_length += len(sentence) + 2
            else:
                break
        
        result = '. '.join(truncated)
        if result and not result.endswith('.'):
            result += '.'
        
        return result or transcript[:max_length]