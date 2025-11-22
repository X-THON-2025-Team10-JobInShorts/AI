import pytest
import signal
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.main import VideoProcessingWorker, main
from src.models import JobContext


class TestVideoProcessingWorker:
    """VideoProcessingWorker 테스트"""
    
    @patch('src.main.SQSConsumer')
    @patch('src.main.VideoProcessor')
    @patch('src.main.ClovaSTTClient')
    @patch('src.main.ClaudeClient')
    @patch('src.main.BackendCallbackClient')
    def test_worker_initialization(self, mock_callback, mock_claude, mock_stt, mock_video, mock_sqs):
        """워커 초기화 테스트"""
        worker = VideoProcessingWorker()
        
        assert worker.sqs_consumer is not None
        assert worker.video_processor is not None
        assert worker.stt_client is not None
        assert worker.llm_client is not None
        assert worker.callback_client is not None
        assert worker.should_stop is False
        
        # 각 컴포넌트가 생성되었는지 확인
        mock_sqs.assert_called_once()
        mock_video.assert_called_once()
        mock_stt.assert_called_once()
        mock_claude.assert_called_once()
        mock_callback.assert_called_once()
    
    def test_signal_handler(self):
        """종료 시그널 처리 테스트"""
        with patch('src.main.SQSConsumer'), \
             patch('src.main.VideoProcessor'), \
             patch('src.main.ClovaSTTClient'), \
             patch('src.main.ClaudeClient'), \
             patch('src.main.BackendCallbackClient'):
            
            worker = VideoProcessingWorker()
            assert worker.should_stop is False
            
            # 시그널 핸들러 호출
            worker._signal_handler(signal.SIGTERM, None)
            assert worker.should_stop is True
    
    def test_process_job_success(self, sample_job_context):
        """Job 처리 성공 테스트"""
        with patch('src.main.SQSConsumer'), \
             patch('src.main.VideoProcessor') as mock_video, \
             patch('src.main.ClovaSTTClient') as mock_stt, \
             patch('src.main.ClaudeClient') as mock_claude, \
             patch('src.main.BackendCallbackClient') as mock_callback:
            
            # Mock 설정
            mock_video_instance = mock_video.return_value
            mock_video_instance.process_video_file.return_value = ("/tmp/video.mp4", "/tmp/audio.wav")
            mock_video_instance.cleanup_temp_files.return_value = None
            
            mock_stt_instance = mock_stt.return_value
            mock_stt_instance.validate_audio_file.return_value = True
            mock_stt_instance.transcribe_audio.return_value = "테스트 음성 변환"
            
            mock_claude_instance = mock_claude.return_value
            mock_claude_instance.validate_transcript.return_value = True
            mock_claude_instance.truncate_transcript_if_needed.return_value = "테스트 음성 변환"
            mock_claude_instance.generate_summary.return_value = "테스트 요약"
            
            mock_callback_instance = mock_callback.return_value
            mock_callback_instance.upload_result_to_s3.return_value = "results/test.json"
            mock_callback_instance.send_success_callback.return_value = True
            
            worker = VideoProcessingWorker()
            result = worker.process_job(sample_job_context)
            
            assert result is True
            
            # 각 단계가 호출되었는지 확인
            mock_video_instance.process_video_file.assert_called_once_with(sample_job_context)
            mock_stt_instance.transcribe_audio.assert_called_once_with(sample_job_context)
            mock_claude_instance.generate_summary.assert_called_once_with(sample_job_context)
            mock_callback_instance.send_success_callback.assert_called_once()
            mock_video_instance.cleanup_temp_files.assert_called_once_with(sample_job_context)
    
    def test_process_job_video_processing_failure(self, sample_job_context):
        """비디오 처리 실패 테스트"""
        with patch('src.main.SQSConsumer'), \
             patch('src.main.VideoProcessor') as mock_video, \
             patch('src.main.ClovaSTTClient'), \
             patch('src.main.ClaudeClient'), \
             patch('src.main.BackendCallbackClient') as mock_callback:
            
            # 비디오 처리 실패 설정
            mock_video_instance = mock_video.return_value
            mock_video_instance.process_video_file.side_effect = Exception("S3 download failed")
            mock_video_instance.cleanup_temp_files.return_value = None
            
            mock_callback_instance = mock_callback.return_value
            mock_callback_instance.send_failure_callback.return_value = True
            
            worker = VideoProcessingWorker()
            result = worker.process_job(sample_job_context)
            
            assert result is False
            
            # 실패 콜백이 호출되었는지 확인
            mock_callback_instance.send_failure_callback.assert_called_once()
            # 정리는 finally에서 호출됨
            mock_video_instance.cleanup_temp_files.assert_called_once_with(sample_job_context)
    
    def test_process_job_stt_failure(self, sample_job_context):
        """STT 처리 실패 테스트"""
        with patch('src.main.SQSConsumer'), \
             patch('src.main.VideoProcessor') as mock_video, \
             patch('src.main.ClovaSTTClient') as mock_stt, \
             patch('src.main.ClaudeClient'), \
             patch('src.main.BackendCallbackClient') as mock_callback:
            
            # 비디오 처리는 성공, STT는 실패
            mock_video_instance = mock_video.return_value
            mock_video_instance.process_video_file.return_value = ("/tmp/video.mp4", "/tmp/audio.wav")
            mock_video_instance.cleanup_temp_files.return_value = None
            
            mock_stt_instance = mock_stt.return_value
            mock_stt_instance.validate_audio_file.return_value = True
            mock_stt_instance.transcribe_audio.side_effect = Exception("Clova STT timeout")
            
            mock_callback_instance = mock_callback.return_value
            mock_callback_instance.send_failure_callback.return_value = True
            
            worker = VideoProcessingWorker()
            result = worker.process_job(sample_job_context)
            
            assert result is False
            
            # STT 실패 콜백 확인
            call_args = mock_callback_instance.send_failure_callback.call_args
            assert call_args[0][0] == sample_job_context
            assert "STT" in call_args[0][1]  # error_code
    
    def test_process_job_invalid_audio_file(self, sample_job_context):
        """유효하지 않은 오디오 파일 테스트"""
        with patch('src.main.SQSConsumer'), \
             patch('src.main.VideoProcessor') as mock_video, \
             patch('src.main.ClovaSTTClient') as mock_stt, \
             patch('src.main.ClaudeClient'), \
             patch('src.main.BackendCallbackClient') as mock_callback:
            
            mock_video_instance = mock_video.return_value
            mock_video_instance.process_video_file.return_value = ("/tmp/video.mp4", "/tmp/audio.wav")
            mock_video_instance.cleanup_temp_files.return_value = None
            
            mock_stt_instance = mock_stt.return_value
            mock_stt_instance.validate_audio_file.return_value = False  # 유효하지 않은 파일
            
            mock_callback_instance = mock_callback.return_value
            mock_callback_instance.send_failure_callback.return_value = True
            
            worker = VideoProcessingWorker()
            result = worker.process_job(sample_job_context)
            
            assert result is False
    
    def test_classify_error(self, sample_job_context):
        """에러 분류 테스트"""
        with patch('src.main.SQSConsumer'), \
             patch('src.main.VideoProcessor'), \
             patch('src.main.ClovaSTTClient'), \
             patch('src.main.ClaudeClient'), \
             patch('src.main.BackendCallbackClient'):
            
            worker = VideoProcessingWorker()
            
            # S3 에러
            s3_error = Exception("S3 download failed")
            assert worker._classify_error(s3_error) == "S3_DOWNLOAD_FAILED"
            
            # FFmpeg 에러
            ffmpeg_error = Exception("ffmpeg audio extraction failed")
            assert worker._classify_error(ffmpeg_error) == "FFMPEG_FAILED"
            
            # STT 에러
            stt_error = Exception("clova stt timeout occurred")
            assert worker._classify_error(stt_error) == "STT_TIMEOUT"
            
            # Claude 에러
            claude_error = Exception("claude llm timeout")
            assert worker._classify_error(claude_error) == "LLM_TIMEOUT"
            
            # 콜백 에러
            callback_error = Exception("callback failed to send")
            assert worker._classify_error(callback_error) == "CALLBACK_FAILED"
            
            # 알 수 없는 에러
            unknown_error = Exception("unexpected error occurred")
            assert worker._classify_error(unknown_error) == "UNKNOWN_ERROR"


class TestMain:
    """main 함수 테스트"""
    
    @patch('src.main.setup_logger')
    @patch('src.main.validate_required_settings')
    @patch('src.main.VideoProcessingWorker')
    def test_main_success(self, mock_worker_class, mock_validate, mock_setup_logger):
        """main 함수 성공 테스트"""
        mock_worker = Mock()
        mock_worker_class.return_value = mock_worker
        
        main()
        
        mock_setup_logger.assert_called_once_with(level="INFO")
        mock_validate.assert_called_once()
        mock_worker_class.assert_called_once()
        mock_worker.run.assert_called_once()
    
    @patch('src.main.setup_logger')
    @patch('src.main.validate_required_settings')
    @patch('src.main.VideoProcessingWorker')
    @patch('builtins.print')
    @patch('sys.exit')
    def test_main_missing_env_vars(self, mock_exit, mock_print, mock_worker_class, mock_validate, mock_setup_logger):
        """필수 환경변수 누락 시 main 함수 테스트"""
        mock_validate.side_effect = ValueError("필수 환경 변수가 누락되었습니다: CLAUDE_API_KEY")
        
        # sys.exit가 SystemExit 예외를 발생시키도록 설정 (실제 동작과 유사하게)
        mock_exit.side_effect = SystemExit(1)
        
        # SystemExit 예외가 발생하므로 테스트에서도 예외를 기대해야 함
        with pytest.raises(SystemExit):
            main()
        
        mock_setup_logger.assert_called_once()
        mock_validate.assert_called_once()
        mock_print.assert_called_once()
        mock_exit.assert_called_once_with(1)
        
        # VideoProcessingWorker가 생성되지 않았는지 확인 (sys.exit로 인해)
        mock_worker_class.assert_not_called()
        
        # 에러 메시지가 출력되었는지 확인
        print_call = mock_print.call_args[0][0]
        assert "ERROR:" in print_call
        assert "누락되었습니다" in print_call


class TestIntegration:
    """통합 테스트"""
    
    @patch('src.main.SQSConsumer')
    @patch('src.main.VideoProcessor')
    @patch('src.main.ClovaSTTClient')
    @patch('src.main.ClaudeClient')
    @patch('src.main.BackendCallbackClient')
    def test_end_to_end_processing(self, mock_callback, mock_claude, mock_stt, mock_video, mock_sqs, sample_job_context):
        """전체 파이프라인 통합 테스트"""
        # 모든 컴포넌트 Mock 설정
        mock_video_instance = mock_video.return_value
        mock_video_instance.process_video_file.return_value = ("/tmp/test.mp4", "/tmp/test.wav")
        mock_video_instance.cleanup_temp_files.return_value = None
        
        mock_stt_instance = mock_stt.return_value
        mock_stt_instance.validate_audio_file.return_value = True
        mock_stt_instance.transcribe_audio.side_effect = lambda ctx: setattr(ctx, 'transcript', '테스트 음성입니다')
        
        mock_claude_instance = mock_claude.return_value
        mock_claude_instance.validate_transcript.return_value = True
        mock_claude_instance.truncate_transcript_if_needed.return_value = '테스트 음성입니다'
        mock_claude_instance.generate_summary.side_effect = lambda ctx: setattr(ctx, 'summary', '테스트 요약입니다')
        
        mock_callback_instance = mock_callback.return_value
        mock_callback_instance.upload_result_to_s3.return_value = "results/user/job.json"
        mock_callback_instance.send_success_callback.return_value = True
        
        # 워커 생성 및 Job 처리
        worker = VideoProcessingWorker()
        result = worker.process_job(sample_job_context)
        
        # 성공적으로 처리되었는지 확인
        assert result is True
        
        # JobContext가 올바르게 업데이트되었는지 확인
        assert sample_job_context.transcript == '테스트 음성입니다'
        assert sample_job_context.summary == '테스트 요약입니다'
        
        # 모든 단계가 순서대로 호출되었는지 확인
        mock_video_instance.process_video_file.assert_called_once()
        mock_stt_instance.transcribe_audio.assert_called_once()
        mock_claude_instance.generate_summary.assert_called_once()
        mock_callback_instance.send_success_callback.assert_called_once()
        mock_video_instance.cleanup_temp_files.assert_called_once()
    
    @patch('time.sleep')  # sleep 모킹으로 테스트 속도 향상
    def test_processing_time_tracking(self, mock_sleep, sample_job_context):
        """처리 시간 추적 테스트"""
        with patch('src.main.VideoProcessor') as mock_video, \
             patch('src.main.ClovaSTTClient') as mock_stt, \
             patch('src.main.ClaudeClient') as mock_claude, \
             patch('src.main.BackendCallbackClient') as mock_callback, \
             patch('src.main.SQSConsumer'):
            
            # Mock 설정
            mock_video.return_value.process_video_file.return_value = ("/tmp/test.mp4", "/tmp/test.wav")
            mock_video.return_value.cleanup_temp_files.return_value = None
            mock_stt.return_value.validate_audio_file.return_value = True
            mock_stt.return_value.transcribe_audio.return_value = "테스트"
            mock_claude.return_value.validate_transcript.return_value = True
            mock_claude.return_value.truncate_transcript_if_needed.return_value = "테스트"
            mock_claude.return_value.generate_summary.return_value = "요약"
            mock_callback.return_value.upload_result_to_s3.return_value = "results/test.json"
            mock_callback.return_value.send_success_callback.return_value = True
            
            start_time = time.time()
            worker = VideoProcessingWorker()
            worker.process_job(sample_job_context)
            end_time = time.time()
            
            # 성공 콜백에서 processing_time_ms가 전달되었는지 확인
            callback_args = mock_callback.return_value.send_success_callback.call_args
            # call_args는 (args, kwargs) 튜플입니다
            # send_success_callback(job_context, result_s3_key, processing_time_ms) 형태로 호출됨
            # 따라서 args[0] = job_context, args[1] = result_s3_key, args[2] = processing_time_ms
            
            # 위치 인수로 전달되었는지 확인
            if len(callback_args.args) >= 3:
                processing_time_ms = callback_args.args[2]
            elif 'processing_time_ms' in callback_args.kwargs:
                processing_time_ms = callback_args.kwargs['processing_time_ms']
            else:
                processing_time_ms = None
            
            # processing_time_ms가 전달되었는지 확인
            assert processing_time_ms is not None, f"processing_time_ms가 전달되지 않았습니다. call_args: {callback_args}"
            assert isinstance(processing_time_ms, int), f"processing_time_ms는 int여야 합니다, got {type(processing_time_ms)}"
            assert processing_time_ms >= 0, f"processing_time_ms는 0 이상이어야 합니다, got {processing_time_ms}"
            assert processing_time_ms < (end_time - start_time) * 1000 + 1000  # 여유있게 체크