FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir torch torchvision torchaudio

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# RUN python -c "from transformers import AutoModel, AutoTokenizer; AutoModel.from_pretrained('./models/cointegrated_rubert_tiny2'); AutoTokenizer.from_pretrained('./models/cointegrated_rubert_tiny2')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
