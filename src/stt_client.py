import time
import httpx
from typing import Optional
from pathlib import Path

from .config import settings
from .models import JobContext
from .logger import get_job_logger, LogStage, ErrorCode


class ClovaSTTClient:
    def __init__(self):
        self.api_url = settings.clova_stt_url
        self.api_key_id = settings.clova_api_key_id
        self.api_key = settings.clova_api_key
        self.max_retries = settings.max_retries
        self.retry_delay = settings.retry_delay_seconds
    
    def transcribe_audio(self, job_context: JobContext) -> str:
        """
        클로바 STT API를 사용하여 오디오를 텍스트로 변환합니다.
        """
        if not job_context.local_audio_path:
            raise ValueError("Audio file path not found")
        
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        audio_path = Path(job_context.local_audio_path)
        
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        logger.info("STT 변환 시작", 
                   stage=LogStage.STT_START,
                   audio_path=str(audio_path),
                   file_size=audio_path.stat().st_size)
        
        for attempt in range(self.max_retries + 1):
            try:
                start_time = time.time()
                transcript = self._call_clova_api(audio_path)
                duration_ms = int((time.time() - start_time) * 1000)
                
                logger.info("STT 변환 완료", 
                           stage=LogStage.STT_DONE,
                           duration_ms=duration_ms,
                           transcript_length=len(transcript),
                           stt_engine="clova")
                
                job_context.transcript = transcript
                return transcript
                
            except Exception as e:
                logger.warning(f"STT 시도 실패 (시도 {attempt + 1}/{self.max_retries + 1})", 
                              error=str(e))
                
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"재시도 대기", wait_seconds=wait_time)
                    time.sleep(wait_time)
                else:
                    logger.error("STT 변환 최종 실패", 
                               stage=LogStage.STT_DONE,
                               error=str(e),
                               error_code=self._classify_error(e))
                    raise
    
    def _call_clova_api(self, audio_path: Path) -> str:
        """
        실제 클로바 API 호출
        """
        headers = {
            'X-NCP-APIGW-API-KEY-ID': self.api_key_id,
            'X-NCP-APIGW-API-KEY': self.api_key,
            'Content-Type': 'application/octet-stream'
        }
        
        try:
            with open(audio_path, 'rb') as audio_file:
                audio_data = audio_file.read()
            
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    self.api_url,
                    headers=headers,
                    content=audio_data
                )
                response.raise_for_status()
                
                result = response.json()
                transcript = result.get('text', '')
                
                if not transcript:
                    raise Exception("Empty transcript received from Clova STT")
                
                return transcript
                
        except httpx.TimeoutException:
            raise Exception("Clova STT API timeout")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise Exception("Clova STT API rate limit exceeded")
            elif e.response.status_code >= 500:
                raise Exception(f"Clova STT server error: {e.response.status_code}")
            else:
                raise Exception(f"Clova STT API error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"Clova STT request failed: {e}")
        except KeyError as e:
            raise Exception(f"Invalid response format from Clova STT: {e}")
        except Exception as e:
            raise Exception(f"Clova STT unexpected error: {e}")
    
    def _classify_error(self, error: Exception) -> str:
        """
        에러를 분류하여 에러 코드를 반환합니다.
        """
        error_str = str(error).lower()
        
        if 'timeout' in error_str:
            return ErrorCode.STT_TIMEOUT
        elif 'rate limit' in error_str:
            return ErrorCode.STT_TIMEOUT  # rate limit도 timeout으로 분류
        elif any(keyword in error_str for keyword in ['empty', 'invalid', 'format']):
            return ErrorCode.STT_BAD_RESPONSE
        else:
            return ErrorCode.STT_BAD_RESPONSE
    
    def validate_audio_file(self, audio_path: str) -> bool:
        """
        오디오 파일의 유효성을 검사합니다.
        """
        try:
            path = Path(audio_path)
            if not path.exists():
                return False
            
            # 파일 크기 확인 (최소 1KB, 최대 100MB)
            file_size = path.stat().st_size
            if file_size < 1024 or file_size > 100 * 1024 * 1024:
                return False
            
            # WAV 파일 헤더 확인
            with open(path, 'rb') as f:
                header = f.read(12)
                if len(header) >= 12:
                    return header[:4] == b'RIFF' and header[8:12] == b'WAVE'
            
            return False
            
        except Exception:
            return False