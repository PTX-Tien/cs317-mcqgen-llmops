"""Phoenix tracing setup for MCQGen pipeline."""
import os
from urllib.request import urlopen

def init_tracing(project_name: str = "mcqgen"):
    """Enable Phoenix tracing only when explicitly configured and healthy."""
    if os.getenv("ENABLE_TRACING", "0") != "1":
        print("ℹ️ Tracing disabled by ENABLE_TRACING")
        return None

    endpoint = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")
    health_url = os.getenv("PHOENIX_HEALTH_URL", "http://localhost:6006/healthz")

    try:
        with urlopen(health_url, timeout=0.5) as response:
            if response.status >= 400:
                print(f"⚠️  Phoenix not healthy, tracing disabled: HTTP {response.status}")
                return None
    except Exception as e:
        print(f"⚠️  Phoenix not healthy, tracing disabled: {e}")
        return None

    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor
        from phoenix.otel import register

        tracer_provider = register(
            project_name=project_name,
            endpoint=endpoint,
        )
        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        print(f"✅ Phoenix tracing enabled → {endpoint}")
        return tracer_provider
    except Exception as e:
        print(f"⚠️  Failed to initialize tracing, disabled: {e}")
        return None
