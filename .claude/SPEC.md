이 Pod는 **SQS → S3 → FFmpeg → 클로바 STT → Claude → 백엔드 콜백** 파이프라인

---

# SPEC: AI Application Pod

## 0. 개요

* 역할:

  * SQS 큐에서 메시지를 폴링
  * S3에서 영상 다운로드
  * FFmpeg로 오디오 추출
  * 클로바 STT로 텍스트 변환
  * Claude API으로 요약/스크립트 생성
  * 결과를 백엔드 API에 콜백
* 책임 범위:

  * **입력:** SQS 메시지 (S3 bucket/key 정보)
  * **출력:** 백엔드 콜백 HTTP 요청
  * DB, Job 테이블, 프론트엔드는 전부 백엔드 영역

---

## 1. 외부 인터페이스

### 1.1 입력: SQS 메시지

* 큐 이름: 예) `video-ingest-queue`
* 메시지 Body: S3 Event Notification 원본 그대로 또는 래핑 JSON
  (Infra에서 S3 → SQS 연결 시 기본 포맷 사용)

Pod에서 사용해야 하는 필드만 정리:

```json
{
  "Records": [
    {
      "eventTime": "2025-11-22T05:01:23.000Z",
      "s3": {
        "bucket": { "name": "shortform-video-bucket" },
        "object": { "key": "videos/123/987654321.mp4", "size": 12345678 }
      }
    }
  ]
}
```

* 사용 필드:

  * `bucket = Records[0].s3.bucket.name`
  * `key = Records[0].s3.object.key`
* `key` 규칙 예: `videos/{user_id}/{job_id}.mp4`

  * `job_id`는 `key` 파싱으로 가져옴 (`split('/')[2].split('.')[0]` 등)

---

### 1.2 출력: Backend 콜백 API

* 엔드포인트 (환경변수로 주입):

  * `BACKEND_BASE_URL`
  * 최종 호출 URL: `POST {BACKEND_BASE_URL}/internal/jobs/{job_id}/complete`
* 인증:

  * 헤더: `X-Internal-Token: <BACKEND_INTERNAL_TOKEN>`

#### 1.2.1 성공 케이스 Request Body

```json
{
  "status": "DONE",
  "s3_bucket": "shortform-video-bucket",
  "s3_key": "videos/123/987654321.mp4",
  "transcript": "STT로 얻은 전체 텍스트 ...",
  "summary": "Claude로 생성한 요약/스크립트 ...",
  "result_s3_key": "results/123/987654321.json",
  "meta": {
    "duration_ms": 25000,
    "model": "claude-3-7-sonnet",
    "stt_engine": "clova"
  }
}
```

* `result_s3_key`:

  * 선택 항목. 결과 JSON, 자막 파일 등을 S3에 저장했다면 그 위치.

#### 1.2.2 실패 케이스 Request Body

```json
{
  "status": "FAILED",
  "s3_bucket": "shortform-video-bucket",
  "s3_key": "videos/123/987654321.mp4",
  "error_code": "STT_TIMEOUT",
  "error_message": "Clova STT request timed out"
}
```

* 실패 시에도 가능하면 콜백을 시도해서 백엔드가 Job을 `FAILED`로 마킹할 수 있게 한다.

---

## 2. 환경 변수 정의

AI Pod는 아래 환경 변수를 기준으로 설정:

```text
# 공통
APP_ENV=dev|prod

# AWS
AWS_REGION=ap-northeast-2
VIDEO_BUCKET_NAME=shortform-video-bucket
RESULT_BUCKET_NAME=shortform-result-bucket (옵션, VIDEO와 동일해도 됨)
SQS_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/123456789012/video-ingest-queue
SQS_WAIT_TIME_SECONDS=10              # Long polling
SQS_VISIBILITY_TIMEOUT_SECONDS=90     # FFmpeg+STT+LLM 예상 처리시간 + 여유

# Backend callback
BACKEND_BASE_URL=https://backend.internal.svc.cluster.local
BACKEND_INTERNAL_TOKEN=xxxxx

# Clova STT
CLOVA_STT_URL=https://naveropenapi.apigw.ntruss.com/recog/v1/stt?lang=Kor
CLOVA_API_KEY_ID=xxx
CLOVA_API_KEY=yyy

# Claude / LLM
CLAUDE_API_URL=https://api.anthropic.com/v1/messages
CLAUDE_API_KEY=zzz
CLAUDE_MODEL=claude-3-7-sonnet
CLAUDE_MAX_TOKENS=2000
```

---

## 3. 내부 모듈 구조

예시: Python/FastAPI + 워커 구조 기준

```text
src/
  main.py              # 엔트리포인트, 워커 루프 시작
  sqs_consumer.py      # SQS Polling 로직
  video_processor.py   # S3 다운로드, FFmpeg 오디오 추출
  stt_client.py        # 클로바 STT 호출
  llm_client.py        # Claude/Bedrock 호출
  callback_client.py   # 백엔드 콜백 HTTP 클라이언트
  config.py            # 환경 변수 로딩
  models.py            # 내부 DTO (JobContext, Result 등)
  logger.py            # 공통 로깅 설정
```

### 3.1 JobContext 구조체 (예시)

```python
class JobContext(BaseModel):
    job_id: str
    user_id: str | None
    s3_bucket: str
    s3_key: str
    local_video_path: str | None = None
    local_audio_path: str | None = None
    transcript: str | None = None
    summary: str | None = None
```

---

## 4. 처리 플로우 (AI Pod 내부)

### 4.1 시퀀스

1. SQS에서 메시지 수신 (Long Polling)
2. 메시지 body를 JSON으로 파싱
3. `bucket`, `key` 추출
4. `key`에서 `job_id` 파싱
5. S3에서 영상 다운로드 → `/tmp/{job_id}.mp4`
6. FFmpeg로 오디오 추출 → `/tmp/{job_id}.wav`  
    1. 스테레오 → 모노
    2. 16kHz 리샘플
    3. highpass(200Hz), lowpass(3.8kHz)
    4. afftdn 또는 anlmdn 기반 노이즈 감소
    5. 출력: /tmp/{job_id}.wa11v
7. 클로바 STT 호출 → `transcript` 텍스트
8. Claude 호출:

   * 프롬프트 템플릿에 transcript 삽입
   * `summary` 생성
9. (옵션) `transcript`, `summary`를 JSON으로 만들어 S3에 업로드:

   * `results/{user_id}/{job_id}.json`
10. 백엔드 콜백:

    * `POST /internal/jobs/{job_id}/complete`
11. 콜백 성공 시 SQS `DeleteMessage` 호출
12. 처리 중 오류 발생 시:

    * 가능하면 실패 콜백 호출
    * 예외 그대로 두면 Visibility Timeout 이후 재시도 또는 DLQ로 이동

---

### 4.2 단일 Job 처리 의사코드

```python
def process_sqs_message(message_body: str):
    event = json.loads(message_body)
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    job_id = extract_job_id_from_key(key)    # 예: "videos/{user}/{job_id}.mp4"

    ctx = JobContext(
        job_id=job_id,
        user_id=extract_user_id_from_key(key),
        s3_bucket=bucket,
        s3_key=key,
    )

    try:
        # 1) S3에서 영상 다운로드
        ctx.local_video_path = download_from_s3(ctx.s3_bucket, ctx.s3_key, job_id)

        # 2) FFmpeg로 오디오 추출
        ctx.local_audio_path = extract_audio_with_ffmpeg(ctx.local_video_path)

        # 3) 클로바 STT
        ctx.transcript = call_clova_stt(ctx.local_audio_path)

        # 4) Claude 요약
        ctx.summary = call_claude_summarize(ctx.transcript)

        # 5) (옵션) 결과 S3 업로드
        result_s3_key = upload_result_json(ctx)

        # 6) 백엔드 콜백 (성공)
        send_backend_callback_success(
            job_id=ctx.job_id,
            s3_bucket=ctx.s3_bucket,
            s3_key=ctx.s3_key,
            transcript=ctx.transcript,
            summary=ctx.summary,
            result_s3_key=result_s3_key,
        )

    except Exception as e:
        # 7) 실패 콜백
        send_backend_callback_failure(
            job_id=ctx.job_id,
            s3_bucket=ctx.s3_bucket,
            s3_key=ctx.s3_key,
            error_code=classify_error(e),
            error_message=str(e),
        )
        # 예외를 다시 던질지, 먹을지는 리트라이 전략에 따라 결정
        raise
```

---

## 5. 에러 및 리트라이 정책

### 5.1 SQS 레벨

* `VisibilityTimeout` (예: 90초)

  * 그 안에 `DeleteMessage` 안 하면 메시지 다시 나타남 → 재처리
* 동일 메시지가 여러 번 처리될 수 있음:

  * 백엔드 콜백은 **idempotent**하게 설계 가정

    * 같은 `job_id`로 `DONE` 여러 번 와도 최종 상태는 `DONE` 유지

### 5.2 외부 서비스 에러

* S3 다운로드 실패:

  * 네트워크/권한 문제 → 재시도 N번 후 실패
* FFmpeg 실패:

  * 지원하지 않는 포맷 등 → 재시도 무의미 → 바로 실패 콜백
* 클로바 STT:

  * 타임아웃, 500 에러 → Exponential backoff로 1~3회 재시도
* Claude:

  * Rate limit 또는 네트워크 에러 → 재시도 1~3회

### 5.3 에러 코드 예시

```text
S3_DOWNLOAD_FAILED
FFMPEG_FAILED
STT_TIMEOUT
STT_BAD_RESPONSE
LLM_TIMEOUT
LLM_BAD_RESPONSE
CALLBACK_FAILED
UNKNOWN_ERROR
```

---

## 6. 로깅 및 모니터링

필수 로그 항목:

* `job_id`, `user_id`, `s3_key`
* 단계별 시작/종료:

  * `DOWNLOAD_START`, `DOWNLOAD_DONE`
  * `FFMPEG_START`, `FFMPEG_DONE`
  * `STT_START`, `STT_DONE`
  * `LLM_START`, `LLM_DONE`
  * `CALLBACK_SUCCESS` / `CALLBACK_FAILED`
* 처리 시간:

  * 전체 처리 시간
  * STT, LLM 각각 소요 시간

예시 로그 포맷(JSON):

```json
{
  "level": "INFO",
  "job_id": "987654321",
  "stage": "LLM_DONE",
  "duration_ms": 1200,
  "model": "claude-3-7-sonnet"
}
```


