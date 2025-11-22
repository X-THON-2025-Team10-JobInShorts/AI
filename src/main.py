import time
import signal
import sys
from typing import Optional

from .config import settings, validate_required_settings
from .logger import setup_logger, get_job_logger, LogStage, ErrorCode
from .models import JobContext, ProcessingResult
from .sqs_consumer import SQSConsumer
from .video_processor import VideoProcessor
from .stt_client import ClovaSTTClient
from .llm_client import ClaudeClient
from .callback_client import BackendCallbackClient


class VideoProcessingWorker:
    def __init__(self):
        self.sqs_consumer = SQSConsumer()
        self.video_processor = VideoProcessor()
        self.stt_client = ClovaSTTClient()
        self.llm_client = ClaudeClient()
        self.callback_client = BackendCallbackClient()
        self.logger = get_job_logger("main_worker")
        self.should_stop = False
        
        # 종료 시그널 핸들러 등록
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """
        종료 시그널 처리
        """
        self.logger.info(f"종료 시그널 수신 ({signum}), 안전하게 종료 중...")
        self.should_stop = True
    
    def process_job(self, job_context: JobContext) -> bool:
        """
        단일 Job 처리
        """
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        start_time = time.time()
        
        try:
            logger.info("Job 처리 시작", 
                       stage=LogStage.JOB_START,
                       s3_bucket=job_context.s3_bucket,
                       s3_key=job_context.s3_key)
            
            # 1. S3에서 비디오 다운로드 & 오디오 추출
            self.video_processor.process_video_file(job_context)
            
            # 2. STT 처리
            if not self.stt_client.validate_audio_file(job_context.local_audio_path):
                raise Exception("Invalid audio file format")
            
            self.stt_client.transcribe_audio(job_context)
            
            # 3. 트랜스크립트 검증 및 전처리
            if not self.llm_client.validate_transcript(job_context.transcript):
                raise Exception("Invalid transcript content")
            
            # 트랜스크립트가 너무 길면 잘라냄
            job_context.transcript = self.llm_client.truncate_transcript_if_needed(job_context.transcript)
            
            # 4. LLM 요약 생성
            self.llm_client.generate_summary(job_context)
            
            # 5. (옵션) 결과를 S3에 업로드
            result_s3_key = self.callback_client.upload_result_to_s3(job_context)
            
            # 6. 성공 콜백 전송
            processing_time_ms = int((time.time() - start_time) * 1000)
            success = self.callback_client.send_success_callback(
                job_context, 
                result_s3_key, 
                processing_time_ms
            )
            
            if success:
                logger.info("Job 처리 완료", 
                           stage=LogStage.JOB_DONE,
                           processing_time_ms=processing_time_ms,
                           transcript_length=len(job_context.transcript or ""),
                           summary_length=len(job_context.summary or ""))
            
            return success
            
        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            error_code = self._classify_error(e)
            
            logger.error("Job 처리 실패", 
                        stage=LogStage.JOB_FAILED,
                        error=str(e),
                        error_code=error_code,
                        processing_time_ms=processing_time_ms)
            
            # 실패 콜백 전송
            self.callback_client.send_failure_callback(
                job_context, 
                error_code, 
                str(e)
            )
            
            return False
            
        finally:
            # 임시 파일 정리
            try:
                self.video_processor.cleanup_temp_files(job_context)
            except Exception as e:
                logger.warning("임시 파일 정리 실패", error=str(e))
    
    def _classify_error(self, error: Exception) -> str:
        """
        에러를 분류하여 에러 코드를 반환합니다.
        """
        error_str = str(error).lower()
        
        if 's3' in error_str or 'download' in error_str:
            return ErrorCode.S3_DOWNLOAD_FAILED
        elif 'ffmpeg' in error_str or 'audio' in error_str:
            return ErrorCode.FFMPEG_FAILED
        elif 'clova' in error_str or 'stt' in error_str:
            if 'timeout' in error_str:
                return ErrorCode.STT_TIMEOUT
            else:
                return ErrorCode.STT_BAD_RESPONSE
        elif 'claude' in error_str or 'llm' in error_str or 'summary' in error_str:
            if 'timeout' in error_str:
                return ErrorCode.LLM_TIMEOUT
            else:
                return ErrorCode.LLM_BAD_RESPONSE
        elif 'callback' in error_str:
            return ErrorCode.CALLBACK_FAILED
        else:
            return ErrorCode.UNKNOWN_ERROR
    
    def run(self):
        """
        메인 워커 루프
        """
        self.logger.info("AI 비디오 처리 워커 시작",
                        app_env=settings.app_env,
                        aws_region=settings.aws_region,
                        sqs_queue_url=settings.sqs_queue_url)
        
        # 백엔드 연결 상태 확인
        if not self.callback_client.health_check():
            self.logger.warning("백엔드 서비스 연결 실패 - 계속 진행")
        
        try:
            # SQS 폴링 시작
            self.sqs_consumer.poll_and_process(self.process_job)
            
        except KeyboardInterrupt:
            self.logger.info("사용자 인터럽트 - 종료 중...")
        except Exception as e:
            self.logger.error("워커 실행 오류", error=str(e))
            sys.exit(1)
        finally:
            self.logger.info("AI 비디오 처리 워커 종료")


def main():
    """
    애플리케이션 진입점
    """
    # 로깅 설정
    setup_logger(level="INFO")
    
    # 환경 변수 검증
    try:
        validate_required_settings()
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    
    # 워커 시작
    worker = VideoProcessingWorker()
    worker.run()


if __name__ == "__main__":
    main()