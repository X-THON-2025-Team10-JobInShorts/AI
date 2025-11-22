import json
import time
import httpx
import boto3
import os
from botocore.exceptions import ClientError
from typing import Optional, Dict, Any

from .config import settings
from .models import JobContext, CallbackRequest, ProcessingResult
from .logger import get_job_logger, LogStage, ErrorCode


class BackendCallbackClient:
    def __init__(self):
        self.base_url = settings.backend_base_url.rstrip('/')
        self.internal_token = settings.backend_internal_token
        self.max_retries = settings.max_retries
        self.retry_delay = settings.retry_delay_seconds
    
    def send_success_callback(self, 
                            job_context: JobContext,
                            result_s3_key: Optional[str] = None,
                            processing_time_ms: Optional[int] = None) -> bool:
        """
        성공 콜백을 백엔드에 전송합니다.
        """
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        
        callback_data = CallbackRequest(
            status="DONE",
            s3_bucket=job_context.s3_bucket,
            s3_key=job_context.s3_key,
            transcript=job_context.transcript,
            summary=job_context.summary,
            result_s3_key=result_s3_key,
            meta={
                "duration_ms": processing_time_ms,
                "model": settings.claude_model,
                "stt_engine": "clova"
            } if processing_time_ms else {
                "model": settings.claude_model,
                "stt_engine": "clova"
            }
        )
        
        return self._send_callback(job_context.job_id, callback_data, logger)
    
    def send_failure_callback(self, 
                            job_context: JobContext,
                            error_code: str,
                            error_message: str) -> bool:
        """
        실패 콜백을 백엔드에 전송합니다.
        """
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        
        callback_data = CallbackRequest(
            status="FAILED",
            s3_bucket=job_context.s3_bucket,
            s3_key=job_context.s3_key,
            error_code=error_code,
            error_message=error_message
        )
        
        return self._send_callback(job_context.job_id, callback_data, logger)
    
    def _send_callback(self, job_id: str, callback_data: CallbackRequest, logger) -> bool:
        """
        실제 콜백 전송 로직
        """
        # URL 인코딩 처리 - job_id에 특수문자가 있을 수 있음
        from urllib.parse import quote
        encoded_job_id = quote(job_id, safe='')
        url = f"{self.base_url}/internal/jobs/{encoded_job_id}/complete"
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'X-Internal-Token': self.internal_token,
            'User-Agent': f'ai-video-processor/{settings.app_env}'
        }
        
        for attempt in range(self.max_retries + 1):
            try:
                logger.info("백엔드 콜백 전송", 
                           url=url, 
                           status=callback_data.status,
                           attempt=attempt + 1)
                
                with httpx.Client(timeout=30.0) as client:
                    # JSON 데이터를 UTF-8로 인코딩하여 전송 (httpx는 자동으로 UTF-8 인코딩)
                    json_data = callback_data.model_dump(exclude_none=True)
                    response = client.post(
                        url,
                        headers=headers,
                        json=json_data
                    )
                    response.raise_for_status()
                    
                    logger.info("백엔드 콜백 성공", 
                               stage=LogStage.CALLBACK_SUCCESS,
                               status_code=response.status_code,
                               status=callback_data.status)
                    
                    return True
                    
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}"
                try:
                    error_detail = e.response.json()
                    error_msg += f": {error_detail.get('message', e.response.text)}"
                except:
                    error_msg += f": {e.response.text}"
                
                logger.warning(f"백엔드 콜백 실패 (시도 {attempt + 1}/{self.max_retries + 1})", 
                              error=error_msg,
                              status_code=e.response.status_code)
                
                # 4xx 에러는 재시도하지 않음
                if 400 <= e.response.status_code < 500:
                    logger.error("백엔드 콜백 최종 실패 (클라이언트 오류)", 
                               stage=LogStage.CALLBACK_FAILED,
                               error_code=ErrorCode.CALLBACK_FAILED,
                               error=error_msg)
                    return False
                
            except Exception as e:
                logger.warning(f"백엔드 콜백 실패 (시도 {attempt + 1}/{self.max_retries + 1})", 
                              error=str(e))
            
            # 재시도 대기
            if attempt < self.max_retries:
                wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                logger.info(f"콜백 재시도 대기", wait_seconds=wait_time)
                time.sleep(wait_time)
        
        logger.error("백엔드 콜백 최종 실패", 
                    stage=LogStage.CALLBACK_FAILED,
                    error_code=ErrorCode.CALLBACK_FAILED)
        return False
    
    def upload_result_to_s3(self, job_context: JobContext) -> Optional[str]:
        """
        처리 결과를 S3에 JSON 파일로 업로드합니다.
        """
        if not job_context.transcript and not job_context.summary:
            return None
        
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        
        try:
            s3_client = boto3.client('s3', region_name=settings.aws_region)
            
            # 결과 데이터 준비
            # 예시 JSON 구조:
            # {
            #     "job_id": "job-12345-abcdef",
            #     "user_id": "user-67890",
            #     "s3_bucket": "shortform-video-bucket",
            #     "s3_key": "videos/user-67890/video-123.mp4",
            #     "transcript": "안녕하세요. 오늘은 비디오 처리에 대해 설명하겠습니다...",
            #     "summary": "이 비디오는 비디오 처리 기술에 대한 개요를 제공합니다...",
            #     "created_at": "2024-01-15T10:30:45.123456",
            #     "metadata": {
            #         "model": "claude-3-7-sonnet-latest",
            #         "stt_engine": "clova"
            #     }
            # }
            result_data = {
                "job_id": job_context.job_id,
                "user_id": job_context.user_id,
                "s3_bucket": job_context.s3_bucket,
                "s3_key": job_context.s3_key,
                "transcript": job_context.transcript,
                "summary": job_context.summary,
                "created_at": job_context.created_at.isoformat() if job_context.created_at else None,
                "metadata": {
                    "model": settings.claude_model,
                    "stt_engine": "clova"
                }
            }
            
            # S3 키에서 비디오 파일명 추출
            # 예: "videos/user-123/hamzzi.mp4" -> "hamzzi.mp4" -> "hamzzi"
            video_filename = os.path.basename(job_context.s3_key)  # "hamzzi.mp4"
            video_name = os.path.splitext(video_filename)[0]  # "hamzzi" (확장자 제거)
            
            # S3 키 생성: summary/summary_{video_name}.json
            # 예: "summary/summary_hamzzi.json"
            result_key = f"summary/summary_{video_name}.json"
            
            # JSON으로 변환 (ensure_ascii=False로 한글 유지)
            json_data = json.dumps(result_data, ensure_ascii=False, indent=2)
            
            # S3에 업로드 (UTF-8 인코딩 명시)
            s3_client.put_object(
                Bucket=settings.result_bucket_name,
                Key=result_key,
                Body=json_data.encode('utf-8'),
                ContentType='application/json; charset=utf-8',
                ContentEncoding='utf-8'
            )
            
            logger.info("결과 파일 S3 업로드 완료", 
                       result_s3_key=result_key,
                       file_size=len(json_data))
            
            return result_key
            
        except ClientError as e:
            logger.warning("결과 파일 S3 업로드 실패", error=str(e))
            return None
        except Exception as e:
            logger.warning("결과 파일 업로드 예상치 못한 오류", error=str(e))
            return None
    
    def health_check(self) -> bool:
        """
        백엔드 서비스 상태를 확인합니다.
        """
        try:
            url = f"{self.base_url}/health"
            headers = {
                'X-Internal-Token': self.internal_token
            }
            
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=headers)
                return response.status_code == 200
                
        except Exception:
            return False