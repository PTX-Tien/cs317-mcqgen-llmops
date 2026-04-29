"""
setup_tracing.py — Phoenix tracing cho MCQGen pipeline
Import file này ở đầu pipeline_mcq.py
"""
from openinference.instrumentation.openai import OpenAIInstrumentor
import phoenix as px

def init_tracing(project_name: str = "mcqgen"):
    """Khởi động Phoenix tracing — gọi 1 lần khi start pipeline."""
    try:
        from phoenix.otel import register
        tracer_provider = register(
            project_name=project_name,
            endpoint="http://localhost:6006/v1/traces",
        )
        # Auto-instrument tất cả OpenAI API calls (bao gồm vLLM)
        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        print(f"✅ Phoenix tracing enabled → http://localhost:6006")
        return tracer_provider
    except Exception as e:
        print(f"⚠️  Tracing disabled: {e}")
        return None
