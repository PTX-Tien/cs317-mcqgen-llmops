"""Test async batch: 5 requests song song → đo throughput thực tế"""
import os, sys

if "pytest" in sys.modules and os.getenv("RUN_LLM_SMOKE_TESTS") != "1":
    import pytest
    pytest.skip("LLM smoke test; set RUN_LLM_SMOKE_TESTS=1 to run", allow_module_level=True)

import asyncio, time, json
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url=os.getenv("VLLM_URL", "http://localhost:7681/v1"), api_key="x")
MODEL_NAME = os.getenv("VLLM_MODEL", "mcqgen")

PROMPT = """Tạo 1 câu MCQ tiếng Việt về topic Python Pandas, độ khó G2.
Output JSON: {"question_text":"...","options":{"A":"...","B":"...","C":"...","D":"..."},"correct_answers":["A"]}
Chỉ JSON, không text khác."""

async def single_call(i):
    t0 = time.time()
    resp = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": PROMPT}],
        temperature=0.7,
        max_tokens=512,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}
    )
    return i, time.time() - t0

async def main():
    print("Gửi 5 requests song song...")
    t0 = time.time()
    results = await asyncio.gather(*[single_call(i) for i in range(5)])
    total = time.time() - t0
    for i, t in results:
        print(f"  Request {i}: {t:.1f}s")
    print(f"Tổng wall-clock (async): {total:.1f}s")
    print(f"→ Estimate 30 MCQs × 5 calls async: ~{total/5*30:.0f}s = {total/5*30/60:.0f} phút")

asyncio.run(main())
