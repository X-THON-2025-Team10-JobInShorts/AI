import json
import time
import boto3
from typing import Optional, Dict, Any
from urllib.parse import unquote
from botocore.exceptions import ClientError, BotoCoreError

from .config import settings
from .models import SQSMessage, JobContext
from .logger import get_job_logger, LogStage, ErrorCode


class SQSConsumer:
    def __init__(self):
        self.sqs = boto3.client('sqs', region_name=settings.aws_region)
        self.queue_url = settings.sqs_queue_url
        self.wait_time = settings.sqs_wait_time_seconds
        self.visibility_timeout = settings.sqs_visibility_timeout_seconds
        self.logger = get_job_logger("sqs_consumer")
    
    def receive_message(self) -> Optional[Dict[str, Any]]:
        """
        SQS에서 메시지를 수신합니다.
        Long polling을 사용합니다.
        """
        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=self.wait_time,
                VisibilityTimeout=self.visibility_timeout,
                MessageAttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            if not messages:
                return None
            
            message = messages[0]
            self.logger.info("메시지 수신됨!", 
                           message_id=message.get('MessageId'),
                           receipt_handle=message.get('ReceiptHandle')[:20] + "...")
            
            return message
            
        except (ClientError, BotoCoreError) as e:
            self.logger.error("SQS 메시지 수신 실패", error=str(e))
            raise
    
    def delete_message(self, receipt_handle: str) -> bool:
        """
        처리 완료된 메시지를 SQS에서 삭제합니다.
        """
        try:
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            self.logger.info("SQS 메시지 삭제 완료 (처리 끝)", receipt_handle=receipt_handle[:20] + "...")
            return True
            
        except (ClientError, BotoCoreError) as e:
            self.logger.error("SQS 메시지 삭제 실패", error=str(e), receipt_handle=receipt_handle[:20] + "...")
            return False
    
    def parse_s3_event(self, message_body: str) -> Optional[JobContext]:
        """
        S3 Event Notification 메시지를 파싱하여 JobContext를 생성합니다.
        Go 코드 참조: URL 디코딩, 테스트 메시지 처리 포함
        """
        try:
            event_data = json.loads(message_body)
            
            # Records 배열이 없는 경우 처리 (테스트 메시지 등)
            if "Records" not in event_data or not event_data["Records"]:
                self.logger.info("Records가 없는 메시지 수신 (테스트 메시지일 가능성)", 
                               message_body=message_body[:100])
                return None
            
            sqs_message = SQSMessage(**event_data)
            
            # 첫 번째 레코드 사용
            record = sqs_message.first_record
            bucket = record.get_bucket_name()
            raw_key = record.get_object_key()
            
            # Go 코드와 동일하게 URL 디코딩 처리
            try:
                key = unquote(raw_key)
                if key != raw_key:
                    self.logger.info("S3 키 URL 디코딩 수행", raw_key=raw_key, decoded_key=key)
            except Exception as e:
                self.logger.warning("S3 키 URL 디코딩 실패, 원본 사용", 
                                  raw_key=raw_key, error=str(e))
                key = raw_key
            
            self.logger.info("🎯 타겟 발견", bucket=bucket, key=key)
            
            # key에서 job_id와 user_id 추출 (예: "videos/{user_id}/{job_id}.mp4")
            job_id, user_id = self._extract_ids_from_key(key)
            
            return JobContext(
                job_id=job_id,
                user_id=user_id,
                s3_bucket=bucket,
                s3_key=key
            )
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            self.logger.error("S3 Event 파싱 실패", error=str(e), message_body=message_body[:200])
            raise ValueError(f"Invalid S3 event message: {e}")
    
    def _extract_ids_from_key(self, key: str) -> tuple[str, Optional[str]]:
        """
        S3 키에서 job_id와 user_id를 추출합니다.
        job_id는 전체 S3 키를 사용합니다 (예: "videos/user-123/hamzzi.mp4")
        """
        if not key or not isinstance(key, str):
            raise ValueError(f"Invalid S3 key: {key}")
            
        try:
            parts = key.split('/')
            if len(parts) >= 3 and parts[0] == "videos":
                # user_id 추출 (예: "user-123")
                user_id = parts[1]
                
                # job_id는 전체 S3 키 사용
                job_id = key
                
                return job_id, user_id
            else:
                # videos/ 형식이 아닌 경우에도 전체 키를 job_id로 사용
                job_id = key
                return job_id, None
                
        except (IndexError, AttributeError) as e:
            self.logger.error("Key에서 ID 추출 실패", error=str(e), key=key)
            # fallback: 전체 키를 job_id로 사용
            return key, None
    
    def poll_and_process(self, processor_func):
        """
        지속적으로 SQS를 폴링하고 메시지를 처리합니다.
        Go 코드와 동일한 Long Polling 방식 사용
        """
        self.logger.info("🚀 AI Worker 시작! 메시지 대기 중...", queue_url=self.queue_url)
        
        while True:
            try:
                message = self.receive_message()
                if not message:
                    continue
                
                receipt_handle = message['ReceiptHandle']
                message_body = message['Body']
                
                # JobContext 생성 (Go 코드 스타일 적용)
                job_context = self.parse_s3_event(message_body)
                
                # 테스트 메시지이거나 파싱 불가능한 경우 메시지 삭제
                if job_context is None:
                    self.logger.info("테스트 메시지 또는 빈 Records - 삭제 처리")
                    self.delete_message(receipt_handle)
                    continue
                
                job_logger = get_job_logger(job_context.job_id, job_context.user_id)
                
                job_logger.info("Job 처리 시작", stage=LogStage.JOB_START, s3_key=job_context.s3_key)
                
                # 메시지 처리
                success = processor_func(job_context)
                
                if success:
                    # 처리 성공시 메시지 삭제
                    self.delete_message(receipt_handle)
                    job_logger.info("Job 처리 완료", stage=LogStage.JOB_DONE)
                else:
                    job_logger.error("Job 처리 실패 - 메시지 재처리 대기", stage=LogStage.JOB_FAILED)
                    # 메시지를 삭제하지 않으면 visibility timeout 후 재처리됨
                
            except Exception as e:
                self.logger.error("SQS 폴링 오류", error=str(e))
                time.sleep(5)  # 오류 발생시 잠시 대기