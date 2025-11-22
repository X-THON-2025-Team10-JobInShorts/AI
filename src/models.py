from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class S3ObjectInfo(BaseModel):
    name: str
    key: str
    size: Optional[int] = None


class S3EventRecord(BaseModel):
    eventTime: str
    s3: Dict[str, Any]
    
    def get_bucket_name(self) -> str:
        return self.s3["bucket"]["name"]
    
    def get_object_key(self) -> str:
        return self.s3["object"]["key"]


class SQSMessage(BaseModel):
    Records: List[S3EventRecord]
    
    @property
    def first_record(self) -> S3EventRecord:
        return self.Records[0]


class JobContext(BaseModel):
    job_id: str
    user_id: Optional[str] = None
    s3_bucket: str
    s3_key: str
    local_video_path: Optional[str] = None
    local_audio_path: Optional[str] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime = None
    
    def __init__(self, **data):
        if data.get('created_at') is None:
            data['created_at'] = datetime.now()
        super().__init__(**data)


class CallbackRequest(BaseModel):
    status: str
    s3_bucket: str
    s3_key: str
    transcript: Optional[str] = None
    summary: Optional[str] = None
    result_s3_key: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class ProcessingResult(BaseModel):
    job_id: str
    success: bool
    transcript: Optional[str] = None
    summary: Optional[str] = None
    result_s3_key: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None