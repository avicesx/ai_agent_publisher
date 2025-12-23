FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python3 /usr/bin/python

WORKDIR /app

RUN pip install --upgrade pip

RUN pip install --no-cache-dir torch torchvision torchaudio

RUN pip install --no-cache-dir openai-whisper

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "import whisper; whisper.load_model('medium')"

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
