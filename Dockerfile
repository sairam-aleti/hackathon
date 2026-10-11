FROM python:3.11-slim

WORKDIR /app

# Install CBC solver and build dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 8501

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
