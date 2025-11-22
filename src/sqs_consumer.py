import json
import time
import boto3
from typing import Optional, Dict, Any
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
                VisibilityTimeoutSeconds=self.visibility_timeout,
                MessageAttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            if not messages:
                return None
            
            message = messages[0]
            self.logger.info("SQS 메시지 수신", 
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
            self.logger.info("SQS 메시지 삭제 완료", receipt_handle=receipt_handle[:20] + "...")
            return True
            
        except (ClientError, BotoCoreError) as e:
            self.logger.error("SQS 메시지 삭제 실패", error=str(e), receipt_handle=receipt_handle[:20] + "...")
            return False
    
    def parse_s3_event(self, message_body: str) -> JobContext:
        """
        S3 Event Notification 메시지를 파싱하여 JobContext를 생성합니다.
        """
        try:
            event_data = json.loads(message_body)
            sqs_message = SQSMessage(**event_data)
            
            # 첫 번째 레코드 사용
            record = sqs_message.first_record
            bucket = record.get_bucket_name()
            key = record.get_object_key()
            
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
        예상 형식: "videos/{user_id}/{job_id}.mp4"
        """
        try:
            parts = key.split('/')
            if len(parts) >= 3 and parts[0] == "videos":
                user_id = parts[1]
                filename = parts[2]
                job_id = filename.split('.')[0]  # 확장자 제거
                return job_id, user_id
            else:
                # 다른 형식의 경우 키 전체를 job_id로 사용
                filename = key.split('/')[-1]
                job_id = filename.split('.')[0]
                return job_id, None
                
        except (IndexError, AttributeError) as e:
            self.logger.error("Key에서 ID 추출 실패", error=str(e), key=key)
            # fallback: 전체 키를 job_id로 사용
            return key.replace('/', '_').replace('.', '_'), None
    
    def poll_and_process(self, processor_func):
        """
        지속적으로 SQS를 폴링하고 메시지를 처리합니다.
        """
        self.logger.info("SQS 폴링 시작", queue_url=self.queue_url)
        
        while True:
            try:
                message = self.receive_message()
                if not message:
                    continue
                
                receipt_handle = message['ReceiptHandle']
                message_body = message['Body']
                
                # JobContext 생성
                job_context = self.parse_s3_event(message_body)
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