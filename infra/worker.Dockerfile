FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*
COPY packages/agent_core /workspace/packages/agent_core
RUN pip install --index-url https://pypi.org/simple "/workspace/packages/agent_core[rag]"
COPY apps/worker/requirements.txt /workspace/apps/worker/requirements.txt
RUN pip install --index-url https://pypi.org/simple -r /workspace/apps/worker/requirements.txt
COPY apps/worker /workspace/apps/worker
CMD ["python", "/workspace/apps/worker/main.py"]
