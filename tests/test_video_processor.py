import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import ffmpeg

from src.video_processor import VideoProcessor
from src.models import JobContext


class TestVideoProcessor:
    """VideoProcessor 테스트"""
    
    @patch('src.video_processor.boto3')
    def test_video_processor_initialization(self, mock_boto3, mock_settings):
        """VideoProcessor 초기화 테스트"""
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            
            assert processor.temp_dir == Path("/tmp")
            mock_boto3.client.assert_called_with('s3', region_name=mock_settings.aws_region)
    
    @patch('src.video_processor.boto3')
    def test_download_from_s3_success(self, mock_boto3, mock_settings, sample_job_context):
        """S3 다운로드 성공 테스트"""
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.download_file.return_value = None
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            
            # 임시 파일 생성 모킹
            temp_file_path = f"/tmp/{sample_job_context.job_id}.mp4"
            
            with patch('pathlib.Path.stat') as mock_stat:
                mock_stat.return_value.st_size = 1024  # 파일 크기 모킹
                
                with patch('os.path.exists', return_value=True):
                    result = processor.download_from_s3(sample_job_context)
            
            assert result == temp_file_path
            assert sample_job_context.local_video_path == temp_file_path
            mock_s3.download_file.assert_called_once()
    
    @patch('src.video_processor.boto3')
    def test_download_from_s3_failure(self, mock_boto3, mock_settings, sample_job_context):
        """S3 다운로드 실패 테스트"""
        from botocore.exceptions import ClientError
        
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.download_file.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchKey'}}, 'GetObject'
        )
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            
            with pytest.raises(Exception, match="S3 download failed"):
                processor.download_from_s3(sample_job_context)
    
    @patch('src.video_processor.ffmpeg')
    def test_extract_audio_with_ffmpeg_success(self, mock_ffmpeg, mock_settings, sample_job_context, temp_video_file):
        """FFmpeg 오디오 추출 성공 테스트"""
        # JobContext에 비디오 파일 경로 설정
        sample_job_context.local_video_path = temp_video_file
        
        # FFmpeg 체인 모킹
        mock_input = Mock()
        mock_filter1 = Mock()
        mock_filter2 = Mock()
        mock_filter3 = Mock()
        mock_output = Mock()
        mock_overwrite = Mock()
        
        mock_ffmpeg.input.return_value = mock_input
        mock_input.filter.return_value = mock_filter1
        mock_filter1.filter.return_value = mock_filter2
        mock_filter2.filter.return_value = mock_filter3
        mock_filter3.output.return_value = mock_output
        mock_output.overwrite_output.return_value = mock_overwrite
        mock_overwrite.run.return_value = None
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            
            # 출력 파일이 존재한다고 가정
            expected_audio_path = f"/tmp/{sample_job_context.job_id}.wav"
            
            with patch('pathlib.Path.exists', return_value=True):
                with patch('pathlib.Path.stat') as mock_stat:
                    mock_stat.return_value.st_size = 512  # 오디오 파일 크기
                    
                    result = processor.extract_audio_with_ffmpeg(sample_job_context)
            
            assert result == expected_audio_path
            assert sample_job_context.local_audio_path == expected_audio_path
            
            # FFmpeg 체인이 올바르게 호출되었는지 확인
            mock_ffmpeg.input.assert_called_once_with(temp_video_file)
            mock_input.filter.assert_called_with('highpass', f=200)
            mock_overwrite.run.assert_called_once()
    
    @patch('src.video_processor.ffmpeg')
    def test_extract_audio_ffmpeg_failure_with_fallback(self, mock_ffmpeg, mock_settings, sample_job_context, temp_video_file):
        """FFmpeg 실패 시 fallback 테스트"""
        sample_job_context.local_video_path = temp_video_file
        
        # 첫 번째 시도(afftdn)는 실패, 두 번째 시도(anlmdn)는 성공
        mock_input = Mock()
        mock_filter1 = Mock()
        mock_filter2 = Mock()
        mock_filter3 = Mock()
        mock_output = Mock()
        mock_overwrite = Mock()
        
        mock_ffmpeg.input.return_value = mock_input
        mock_input.filter.return_value = mock_filter1
        mock_filter1.filter.return_value = mock_filter2
        mock_filter2.filter.return_value = mock_filter3
        mock_filter3.output.return_value = mock_output
        mock_output.overwrite_output.return_value = mock_overwrite
        
        # 첫 번째 실행은 afftdn 에러, 두 번째는 성공
        # 실제 ffmpeg.Error를 import해서 사용 (모킹 전에)
        from ffmpeg._run import Error as FFmpegError
        error = FFmpegError('ffmpeg', b'', b'afftdn filter not found')
        mock_overwrite.run.side_effect = [error, None]
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            
            expected_audio_path = f"/tmp/{sample_job_context.job_id}.wav"
            
            with patch('pathlib.Path.exists', return_value=True):
                with patch('pathlib.Path.stat') as mock_stat:
                    mock_stat.return_value.st_size = 512
                    
                    result = processor.extract_audio_with_ffmpeg(sample_job_context)
            
            assert result == expected_audio_path
            # run이 두 번 호출되었는지 확인 (첫 번째 실패, 두 번째 성공)
            assert mock_overwrite.run.call_count >= 1
    
    @patch('src.video_processor.ffmpeg')
    def test_extract_audio_no_input_file(self, mock_ffmpeg, mock_settings, sample_job_context):
        """입력 파일이 없을 때 테스트"""
        # local_video_path가 None인 경우
        sample_job_context.local_video_path = None
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            
            with pytest.raises(ValueError, match="Video file path not found"):
                processor.extract_audio_with_ffmpeg(sample_job_context)
    
    def test_cleanup_temp_files(self, mock_settings, sample_job_context, temp_video_file, temp_audio_file):
        """임시 파일 정리 테스트"""
        sample_job_context.local_video_path = temp_video_file
        sample_job_context.local_audio_path = temp_audio_file
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            processor.cleanup_temp_files(sample_job_context)
        
        # 파일이 삭제되었는지 확인
        assert not os.path.exists(temp_video_file)
        assert not os.path.exists(temp_audio_file)
    
    def test_cleanup_temp_files_missing_files(self, mock_settings, sample_job_context):
        """존재하지 않는 파일 정리 테스트 (에러가 발생하지 않아야 함)"""
        sample_job_context.local_video_path = "/tmp/nonexistent_video.mp4"
        sample_job_context.local_audio_path = "/tmp/nonexistent_audio.wav"
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            # 예외가 발생하지 않아야 함
            processor.cleanup_temp_files(sample_job_context)
    
    @patch('src.video_processor.ffmpeg')
    def test_get_video_duration(self, mock_ffmpeg, mock_settings):
        """비디오 재생 시간 가져오기 테스트"""
        mock_ffmpeg.probe.return_value = {
            'streams': [{'duration': '120.5'}]
        }
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            duration = processor.get_video_duration("/tmp/test.mp4")
        
        assert duration == 120.5
        mock_ffmpeg.probe.assert_called_once_with("/tmp/test.mp4")
    
    @patch('src.video_processor.ffmpeg')
    def test_get_video_duration_failure(self, mock_ffmpeg, mock_settings):
        """비디오 재생 시간 가져오기 실패 테스트"""
        mock_ffmpeg.probe.side_effect = Exception("Probe failed")
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            duration = processor.get_video_duration("/tmp/test.mp4")
        
        assert duration is None
    
    @patch('src.video_processor.VideoProcessor.download_from_s3')
    @patch('src.video_processor.VideoProcessor.extract_audio_with_ffmpeg')
    def test_process_video_file_success(self, mock_extract_audio, mock_download_s3, mock_settings, sample_job_context):
        """전체 비디오 파일 처리 성공 테스트"""
        mock_download_s3.return_value = "/tmp/test_video.mp4"
        mock_extract_audio.return_value = "/tmp/test_audio.wav"
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            video_path, audio_path = processor.process_video_file(sample_job_context)
        
        assert video_path == "/tmp/test_video.mp4"
        assert audio_path == "/tmp/test_audio.wav"
        mock_download_s3.assert_called_once_with(sample_job_context)
        mock_extract_audio.assert_called_once_with(sample_job_context)
    
    @patch('src.video_processor.VideoProcessor.download_from_s3')
    @patch('src.video_processor.VideoProcessor.extract_audio_with_ffmpeg')
    @patch('src.video_processor.VideoProcessor.cleanup_temp_files')
    def test_process_video_file_failure_cleanup(self, mock_cleanup, mock_extract_audio, mock_download_s3, mock_settings, sample_job_context):
        """비디오 파일 처리 실패 시 정리 테스트"""
        mock_download_s3.return_value = "/tmp/test_video.mp4"
        mock_extract_audio.side_effect = Exception("Audio extraction failed")
        
        with patch('src.video_processor.settings', mock_settings):
            processor = VideoProcessor()
            
            with pytest.raises(Exception, match="Audio extraction failed"):
                processor.process_video_file(sample_job_context)
        
        # 실패 시에도 정리 함수가 호출되었는지 확인
        mock_cleanup.assert_called_once_with(sample_job_context)