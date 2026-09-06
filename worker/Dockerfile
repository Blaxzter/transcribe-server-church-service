# cuDNN 9 is required by CTranslate2 (faster-whisper); the -cudnn- variant of the
# CUDA image ships it, which avoids the usual libcudnn_ops.so.9 hunt.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/cache/hf \
    TORCH_HOME=/cache/torch

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip ffmpeg libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY worker ./worker

# max_jobs=1 is enforced in WorkerSettings: with 8 GB of VRAM the pipeline must
# never run two jobs concurrently.
CMD ["arq", "worker.main.WorkerSettings"]
