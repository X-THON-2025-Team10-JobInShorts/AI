import os
import re
import boto3
import ffmpeg
from ffmpeg._run import Error as FFmpegError
from pathlib import Path
from typing import Optional
from botocore.exceptions import ClientError, BotoCoreError

from .config import settings
from .models import JobContext
from .logger import get_job_logger, LogStage, ErrorCode


class VideoProcessor:
    def __init__(self):
        self.s3 = boto3.client('s3', region_name=settings.aws_region)
        self.temp_dir = Path("/tmp")
        self.temp_dir.mkdir(exist_ok=True)
    
    def download_from_s3(self, job_context: JobContext) -> str:
        """
        S3에서 비디오 파일을 다운로드합니다.
        """
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        logger.info("S3 다운로드 시작", 
                   stage=LogStage.DOWNLOAD_START,
                   bucket=job_context.s3_bucket,
                   key=job_context.s3_key)
        
        try:
            # 비디오 파일 형식 검증 (FFmpeg가 지원하는 주요 형식)
            video_extensions = {
                '.mp4', '.m4v', '.mov', '.qt',      # MPEG-4, QuickTime
                '.avi', '.divx',                     # AVI
                '.mkv', '.webm',                     # Matroska, WebM
                '.flv', '.f4v',                      # Flash Video
                '.wmv', '.asf',                      # Windows Media
                '.mpg', '.mpeg', '.m2v',             # MPEG
                '.3gp', '.3g2',                      # 3GPP
                '.ts', '.mts', '.m2ts',              # MPEG Transport Stream
                '.vob',                              # DVD Video
                '.ogv', '.ogg'                       # Ogg Video
            }
            file_ext = os.path.splitext(job_context.s3_key)[1].lower()
            
            if file_ext not in video_extensions:
                error_msg = f"비디오 파일이 아닙니다: {file_ext} (지원 형식: {', '.join(video_extensions)})"
                logger.error("파일 형식 검증 실패", 
                           stage=LogStage.DOWNLOAD_DONE,
                           error=error_msg,
                           error_code=ErrorCode.S3_DOWNLOAD_FAILED,
                           file_extension=file_ext)
                raise ValueError(error_msg)
            
            # 로컬 파일 경로 생성 - S3 키에서 파일명만 추출하여 사용
            # 원본 파일 확장자 유지 (mp4, mov, avi 등)
            filename = os.path.basename(job_context.s3_key)
            name_without_ext, original_ext = os.path.splitext(filename)
            
            # 파일명이 너무 길면 잘라내기 (최대 200자)
            if len(name_without_ext) > 200:
                name_without_ext = name_without_ext[:200]
            
            # 안전한 파일명 생성 (특수문자 제거, 확장자는 유지)
            safe_name = re.sub(r'[^\w\-_\.]', '_', name_without_ext)
            # 원본 확장자 유지 (소문자로 정규화)
            local_path = self.temp_dir / f"{safe_name}{original_ext.lower()}"
            
            # 디렉토리가 없으면 생성 (이미 존재하지만 안전을 위해)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # S3에서 파일 다운로드
            self.s3.download_file(
                job_context.s3_bucket,
                job_context.s3_key,
                str(local_path)
            )
            
            # 파일 크기 확인
            file_size = local_path.stat().st_size
            logger.info("S3 다운로드 완료", 
                       stage=LogStage.DOWNLOAD_DONE,
                       local_path=str(local_path),
                       file_size=file_size)
            
            job_context.local_video_path = str(local_path)
            return str(local_path)
            
        except (ClientError, BotoCoreError) as e:
            logger.error("S3 다운로드 실패", 
                        stage=LogStage.DOWNLOAD_DONE,
                        error=str(e),
                        error_code=ErrorCode.S3_DOWNLOAD_FAILED)
            raise Exception(f"S3 download failed: {e}")
        except Exception as e:
            logger.error("S3 다운로드 예상치 못한 오류", 
                        error=str(e),
                        error_code=ErrorCode.S3_DOWNLOAD_FAILED)
            raise
    
    def extract_audio_with_ffmpeg(self, job_context: JobContext) -> str:
        """
        FFmpeg를 사용하여 비디오에서 오디오를 추출합니다.
        """
        if not job_context.local_video_path:
            raise ValueError("Video file path not found")
        
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        logger.info("오디오 추출 시작", 
                   stage=LogStage.FFMPEG_START,
                   input_path=job_context.local_video_path)
        
        try:
            # 출력 파일 경로 - 비디오 파일명과 동일한 베이스명 사용
            # 안전한 파일명 생성
            filename = os.path.basename(job_context.s3_key)
            name_without_ext = os.path.splitext(filename)[0]
            
            # 파일명이 너무 길면 잘라내기
            if len(name_without_ext) > 200:
                name_without_ext = name_without_ext[:200]
            
            # 안전한 파일명 생성 (특수문자 제거)
            safe_name = re.sub(r'[^\w\-_\.]', '_', name_without_ext)
            audio_path = self.temp_dir / f"{safe_name}.wav"
            
            # FFmpeg로 오디오 추출 (SPEC 6단계 적용)
            # 1. 스테레오 → 모노, 2. 16kHz 리샘플, 3. highpass(200Hz), 4. lowpass(3.8kHz), 5. 노이즈 감소
            (
                ffmpeg
                .input(job_context.local_video_path)
                .filter('highpass', f=200)      # 3. highpass 200Hz
                .filter('lowpass', f=3800)      # 4. lowpass 3.8kHz  
                .filter('afftdn')               # 5. 노이즈 감소 (adaptive)
                .output(
                    str(audio_path),
                    acodec='pcm_s16le',         # WAV 형식
                    ac=1,                       # 1. 스테레오 → 모노
                    ar=16000                    # 2. 16kHz 리샘플링
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            
            # 출력 파일 확인
            if not audio_path.exists():
                raise Exception("Audio extraction failed - output file not found")
            
            file_size = audio_path.stat().st_size
            logger.info("오디오 추출 완료", 
                       stage=LogStage.FFMPEG_DONE,
                       output_path=str(audio_path),
                       file_size=file_size)
            
            job_context.local_audio_path = str(audio_path)
            return str(audio_path)
            
        except FFmpegError as e:
            error_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
            
            # afftdn 필터 실패시 anlmdn으로 fallback 시도
            if 'afftdn' in error_msg:
                logger.warning("afftdn 필터 실패, anlmdn으로 재시도", error=error_msg)
                try:
                    (
                        ffmpeg
                        .input(job_context.local_video_path)
                        .filter('highpass', f=200)      # highpass 200Hz
                        .filter('lowpass', f=3800)      # lowpass 3.8kHz  
                        .filter('anlmdn')               # 노이즈 감소 (alternative)
                        .output(
                            str(audio_path),
                            acodec='pcm_s16le',         # WAV 형식
                            ac=1,                       # 스테레오 → 모노
                            ar=16000                    # 16kHz 리샘플링
                        )
                        .overwrite_output()
                        .run(capture_stdout=True, capture_stderr=True)
                    )
                    
                    if audio_path.exists():
                        file_size = audio_path.stat().st_size
                        logger.info("오디오 추출 완료 (anlmdn 사용)", 
                                   stage=LogStage.FFMPEG_DONE,
                                   output_path=str(audio_path),
                                   file_size=file_size)
                        job_context.local_audio_path = str(audio_path)
                        return str(audio_path)
                        
                except ffmpeg.Error as fallback_e:
                    fallback_msg = fallback_e.stderr.decode('utf-8') if fallback_e.stderr else str(fallback_e)
                    logger.warning("anlmdn 필터도 실패, 기본 필터링으로 재시도", error=fallback_msg)
                    
                    # 최종 fallback: 필터 없이 기본 변환만
                    try:
                        (
                            ffmpeg
                            .input(job_context.local_video_path)
                            .output(
                                str(audio_path),
                                acodec='pcm_s16le',     # WAV 형식
                                ac=1,                   # 스테레오 → 모노
                                ar=16000               # 16kHz 리샘플링
                            )
                            .overwrite_output()
                            .run(capture_stdout=True, capture_stderr=True)
                        )
                        
                        if audio_path.exists():
                            file_size = audio_path.stat().st_size
                            logger.info("오디오 추출 완료 (기본 변환)", 
                                       stage=LogStage.FFMPEG_DONE,
                                       output_path=str(audio_path),
                                       file_size=file_size)
                            job_context.local_audio_path = str(audio_path)
                            return str(audio_path)
                    except ffmpeg.Error:
                        pass
            
            logger.error("FFmpeg 오류", 
                        stage=LogStage.FFMPEG_DONE,
                        error=error_msg,
                        error_code=ErrorCode.FFMPEG_FAILED)
            raise Exception(f"FFmpeg failed: {error_msg}")
        except Exception as e:
            logger.error("오디오 추출 예상치 못한 오류", 
                        error=str(e),
                        error_code=ErrorCode.FFMPEG_FAILED)
            raise
    
    def cleanup_temp_files(self, job_context: JobContext):
        """
        임시 파일들을 정리합니다.
        """
        logger = get_job_logger(job_context.job_id, job_context.user_id)
        
        files_to_remove = [
            job_context.local_video_path,
            job_context.local_audio_path
        ]
        
        for file_path in files_to_remove:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info("임시 파일 삭제", file_path=file_path)
                except Exception as e:
                    logger.warning("임시 파일 삭제 실패", file_path=file_path, error=str(e))
    
    def get_video_duration(self, video_path: str) -> Optional[float]:
        """
        비디오 파일의 재생 시간을 반환합니다 (초 단위).
        """
        try:
            probe = ffmpeg.probe(video_path)
            duration = float(probe['streams'][0]['duration'])
            return duration
        except Exception:
            return None
    
    def process_video_file(self, job_context: JobContext) -> tuple[str, str]:
        """
        비디오 파일 전체 처리 (다운로드 + 오디오 추출)
        """
        try:
            # S3에서 비디오 다운로드
            video_path = self.download_from_s3(job_context)
            
            # 오디오 추출
            audio_path = self.extract_audio_with_ffmpeg(job_context)
            
            return video_path, audio_path
            
        except Exception as e:
            # 실패시 정리
            self.cleanup_temp_files(job_context)
            raise