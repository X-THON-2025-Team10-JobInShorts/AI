import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from botocore.exceptions import ClientError

from src.sqs_consumer import SQSConsumer
from src.models import JobContext


class TestSQSConsumer:
    """SQS Consumer 테스트"""
    
    @patch('src.sqs_consumer.boto3')
    def test_sqs_consumer_initialization(self, mock_boto3, mock_settings):
        """SQS Consumer 초기화 테스트"""
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            
            assert consumer.queue_url == mock_settings.sqs_queue_url
            assert consumer.wait_time == mock_settings.sqs_wait_time_seconds
            assert consumer.visibility_timeout == mock_settings.sqs_visibility_timeout_seconds
            mock_boto3.client.assert_called_with('sqs', region_name=mock_settings.aws_region)
    
    @patch('src.sqs_consumer.boto3')
    def test_receive_message_success(self, mock_boto3, mock_settings):
        """메시지 수신 성공 테스트"""
        # Mock SQS 클라이언트 설정
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        
        mock_sqs.receive_message.return_value = {
            'Messages': [{
                'MessageId': 'test-msg-id',
                'ReceiptHandle': 'test-receipt-handle',
                'Body': '{"test": "message"}'
            }]
        }
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            message = consumer.receive_message()
            
            assert message is not None
            assert message['MessageId'] == 'test-msg-id'
            assert message['ReceiptHandle'] == 'test-receipt-handle'
    
    @patch('src.sqs_consumer.boto3')
    def test_receive_message_no_messages(self, mock_boto3, mock_settings):
        """메시지 없음 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        mock_sqs.receive_message.return_value = {'Messages': []}
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            message = consumer.receive_message()
            
            assert message is None
    
    @patch('src.sqs_consumer.boto3')
    def test_receive_message_error(self, mock_boto3, mock_settings):
        """메시지 수신 에러 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        mock_sqs.receive_message.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied'}}, 'ReceiveMessage'
        )
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            
            with pytest.raises(ClientError):
                consumer.receive_message()
    
    @patch('src.sqs_consumer.boto3')
    def test_delete_message_success(self, mock_boto3, mock_settings):
        """메시지 삭제 성공 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        mock_sqs.delete_message.return_value = {}
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            result = consumer.delete_message("test-receipt-handle")
            
            assert result is True
            mock_sqs.delete_message.assert_called_once()
    
    @patch('src.sqs_consumer.boto3')
    def test_delete_message_error(self, mock_boto3, mock_settings):
        """메시지 삭제 에러 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        mock_sqs.delete_message.side_effect = ClientError(
            {'Error': {'Code': 'InvalidReceiptHandle'}}, 'DeleteMessage'
        )
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            result = consumer.delete_message("invalid-receipt-handle")
            
            assert result is False
    
    @patch('src.sqs_consumer.boto3')
    def test_parse_s3_event_success(self, mock_boto3, mock_settings, sample_sqs_message):
        """S3 이벤트 파싱 성공 테스트"""
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            message_body = json.dumps(sample_sqs_message)
            
            job_context = consumer.parse_s3_event(message_body)
            
            assert job_context is not None
            assert job_context.job_id == "test_job_123"
            assert job_context.user_id == "test_user_456"
            assert job_context.s3_bucket == "test-video-bucket"
            assert job_context.s3_key == "videos/test_user_456/test_job_123.mp4"
    
    @patch('src.sqs_consumer.boto3')
    def test_parse_s3_event_url_encoded(self, mock_boto3, mock_settings, sample_sqs_message_encoded):
        """URL 인코딩된 S3 이벤트 파싱 테스트"""
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            message_body = json.dumps(sample_sqs_message_encoded)
            
            job_context = consumer.parse_s3_event(message_body)
            
            assert job_context is not None
            # URL 디코딩이 정상적으로 수행되었는지 확인
            assert job_context.s3_key == "videos/test_user_456/test_job_123.mp4"
    
    @patch('src.sqs_consumer.boto3')
    def test_parse_s3_event_empty_records(self, mock_boto3, mock_settings, empty_sqs_message):
        """빈 Records 메시지 파싱 테스트"""
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            message_body = json.dumps(empty_sqs_message)
            
            job_context = consumer.parse_s3_event(message_body)
            
            assert job_context is None  # 테스트 메시지는 None 반환
    
    @patch('src.sqs_consumer.boto3')
    def test_parse_s3_event_invalid_json(self, mock_boto3, mock_settings):
        """잘못된 JSON 파싱 테스트"""
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            
            with pytest.raises(ValueError):
                consumer.parse_s3_event("invalid json content")
    
    @patch('src.sqs_consumer.boto3')
    def test_extract_ids_from_key_standard_format(self, mock_boto3, mock_settings):
        """표준 형식 키에서 ID 추출 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            job_id, user_id = consumer._extract_ids_from_key("videos/user123/job456.mp4")
            
            assert job_id == "job456"
            assert user_id == "user123"
    
    @patch('src.sqs_consumer.boto3')
    def test_extract_ids_from_key_non_standard_format(self, mock_boto3, mock_settings):
        """비표준 형식 키에서 ID 추출 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            job_id, user_id = consumer._extract_ids_from_key("uploads/some_file.mp4")
            
            assert job_id == "some_file"
            assert user_id is None
    
    @patch('src.sqs_consumer.boto3')
    def test_extract_ids_from_key_invalid_format(self, mock_boto3, mock_settings):
        """잘못된 형식 키에서 ID 추출 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            
            with pytest.raises(ValueError):
                consumer._extract_ids_from_key("")  # 빈 키
            
            with pytest.raises(ValueError):
                consumer._extract_ids_from_key(None)  # None 키
    
    @patch('src.sqs_consumer.boto3')
    def test_extract_ids_special_characters(self, mock_boto3, mock_settings):
        """특수문자가 포함된 키 처리 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            
            # 표준 형식에서 특수문자가 포함된 job_id는 ValueError 발생
            with pytest.raises(ValueError, match="Invalid job_id format"):
                consumer._extract_ids_from_key("videos/user-123/job_456!@#.mp4")
            
            # 비표준 형식에서는 특수문자가 필터링됨
            job_id, user_id = consumer._extract_ids_from_key("uploads/job_456!@#.mp4")
            assert job_id == "job_456"  # 특수문자 !@# 필터링됨
            assert user_id is None
    
    @patch('src.sqs_consumer.boto3')
    def test_poll_and_process_success(self, mock_boto3, mock_settings, sample_sqs_message):
        """메시지 폴링 및 처리 성공 테스트"""
        mock_sqs = Mock()
        mock_boto3.client.return_value = mock_sqs
        
        # 프로세서 함수 모킹
        mock_processor = Mock(return_value=True)
        
        call_count = {'count': 0}
        
        def side_effect_receive_message(*args, **kwargs):
            """메시지를 한 번 반환 후 예외를 발생시켜 루프 종료"""
            call_count['count'] += 1
            if call_count['count'] == 1:
                # 첫 번째 호출: 메시지 반환
                return {
                    'Messages': [{
                        'MessageId': 'test-msg-id',
                        'ReceiptHandle': 'test-receipt-handle',
                        'Body': json.dumps(sample_sqs_message)
                    }]
                }
            elif call_count['count'] == 2:
                # 두 번째 호출: 빈 메시지 반환 (루프는 계속됨)
                return {'Messages': []}
            else:
                # 세 번째 호출부터: 테스트를 위해 명시적으로 루프 종료
                # KeyboardInterrupt는 일반적인 종료 시그널로 처리됨
                raise KeyboardInterrupt("Test loop exit")
        
        mock_sqs.receive_message.side_effect = side_effect_receive_message
        mock_sqs.delete_message.return_value = {}
        
        with patch('src.sqs_consumer.settings', mock_settings):
            consumer = SQSConsumer()
            
            # poll_and_process는 무한루프이므로 KeyboardInterrupt로 종료
            try:
                consumer.poll_and_process(mock_processor)
            except KeyboardInterrupt:
                pass  # 테스트에서 의도적으로 발생시킨 종료
            
            # 프로세서가 호출되었는지 확인
            assert mock_processor.called, "프로세서 함수가 호출되지 않았습니다"
            
            # 메시지가 처리되었는지 확인
            assert call_count['count'] >= 1, "receive_message가 호출되지 않았습니다"
            
            # delete_message가 호출되었는지 확인 (성공적으로 처리되었을 경우)
            assert mock_sqs.delete_message.called, "메시지 삭제가 호출되지 않았습니다"