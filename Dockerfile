FROM python:3.11-slim

# 시스템 패키지 업데이트 및 FFmpeg 설치
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /app

# Python 패키지 설치를 위한 requirements 복사
COPY requirements.txt .

# Python 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 소스 코드 복사
COPY src/ ./src/

# 환경 변수 설정
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# 임시 디렉토리 생성 및 권한 설정
RUN mkdir -p /tmp && chmod 777 /tmp

# 비루트 사용자 생성 및 전환
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "from src.config import settings; from src.callback_client import BackendCallbackClient; exit(0 if BackendCallbackClient().health_check() else 1)"

# 애플리케이션 시작
CMD ["python", "-m", "src.main"]