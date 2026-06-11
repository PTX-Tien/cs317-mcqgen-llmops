FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl fonts-dejavu git \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Group 1: Base numerics (không conflict)
RUN pip install --no-cache-dir \
    "numpy==2.2.6" \
    "pyarrow==24.0.0" \
    "scipy==1.15.3" \
    "scikit-learn==1.7.2" \
    "tqdm==4.67.3" \
    "PyYAML==6.0.3"

# Group 2: ML / RAG
RUN pip install --no-cache-dir \
    "tokenizers==0.21.4" \
    "transformers==4.51.3" \
    "sentence-transformers==5.4.1" \
    "rank-bm25==0.2.2" \
    "chromadb==1.5.8"

# Group 3: API stack
RUN pip install --no-cache-dir \
    "fastapi==0.136.1" \
    "uvicorn==0.46.0" \
    "pydantic==2.13.3" \
    "pydantic-settings==2.14.0" \
    "openai==2.32.0" \
    "httpx==0.28.1" \
    "redis==7.4.0" \
    "celery==5.6.3" \
    "pytest==8.4.2"

# Group 4: Document export
RUN pip install --no-cache-dir \
    "PyMuPDF==1.27.2.3" \
    "pymupdf4llm==1.27.2.3" \
    "reportlab==4.4.10"

COPY . .

EXPOSE 7860
