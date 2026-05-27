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

# Group 3: Phoenix monitoring
RUN pip install --no-cache-dir \
    "arize-phoenix==14.16.0" \
    "arize-phoenix-otel==0.16.0" \
    "langfuse>=4.0.0,<5.0.0" \
    "openinference-instrumentation==0.1.48" \
    "openinference-instrumentation-openai==0.1.45" \
    "openinference-semantic-conventions==0.1.29"

# Group 4: API stack
RUN pip install --no-cache-dir \
    "fastapi==0.136.1" \
    "uvicorn==0.46.0" \
    "pydantic==2.13.3" \
    "pydantic-settings==2.14.0" \
    "openai==2.32.0" \
    "httpx==0.28.1" \
    "redis==7.4.0" \
    "celery==5.6.3" \
    "flower==2.0.1"

# Group 5: Document + UI
RUN pip install --no-cache-dir \
    "PyMuPDF==1.27.2.3" \
    "pymupdf4llm==1.27.2.3" \
    "reportlab==4.4.10" \
    "streamlit==1.57.0"

COPY . .

EXPOSE 7860 8501 6006 5555
