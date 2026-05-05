#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = APP_ROOT / "static"
VLLM_ROOT = PROJECT_ROOT / "vllm"
RESULTS_ROOT = VLLM_ROOT / "results"
PYTHON = sys.executable


@dataclass
class Job:
    id: str
    experiment_id: str
    command: list[str]
    started_at: float = field(default_factory=time.time)
    status: str = "running"
    returncode: int | None = None
    output: "queue.Queue[str]" = field(default_factory=queue.Queue)
    lines: list[str] = field(default_factory=list)
    process: subprocess.Popen[str] | None = None


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


EXPERIMENTS: dict[str, dict[str, Any]] = {
    "exp02": {
        "title": "Exp02 - LLM-only concurrency sweep",
        "script": VLLM_ROOT / "exp02_llm_concurrency_sweep.py",
        "results_dir": RESULTS_ROOT / "exp02_llm_concurrency_sweep",
        "description": "Đo throughput/latency của vLLM khi tăng concurrency.",
        "defaults": {
            "num_requests": 40,
            "concurrency_list": "1,2,4,8",
            "max_tokens": 512,
            "label": "web_exp02",
        },
    },
    "exp03": {
        "title": "Exp03 - Full pipeline sequential vs async",
        "script": VLLM_ROOT / "exp03_pipeline_sequential_vs_async.py",
        "results_dir": RESULTS_ROOT / "exp03_pipeline_sequential_vs_async",
        "description": "So sánh pipeline thật: tuần tự và async + vLLM.",
        "defaults": {
            "topic_limit": 2,
            "questions_per_topic": 1,
            "concurrency": 2,
            "label": "web_exp03",
        },
    },
    "exp07": {
        "title": "Exp07 - No-batching baseline vs vLLM",
        "script": VLLM_ROOT / "exp07_no_vllm_baselines.py",
        "results_dir": RESULTS_ROOT / "exp07_no_vllm_baselines",
        "description": "Chứng minh baseline không tận dụng batching và so với vLLM concurrent.",
        "defaults": {
            "num_requests": 40,
            "vllm_concurrency": 4,
            "max_tokens": 512,
            "label": "web_exp07",
            "include_direct_transformers": False,
        },
    },
}


app = FastAPI(title="MCQGen vLLM Demo Console")
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


def safe_label(value: str, fallback: str) -> str:
    value = str(value or "").strip()
    if not value:
        return fallback
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value)
    return value[:48] or fallback


def int_value(data: dict[str, Any], key: str, default: int, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        value = int(data.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def str_value(data: dict[str, Any], key: str, default: str) -> str:
    value = str(data.get(key, default)).strip()
    return value or default


def bool_value(data: dict[str, Any], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def http_get(url: str, timeout: float = 5.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status": response.status,
                "latency_s": round(time.perf_counter() - started, 4),
                "body": body,
                "error": "",
            }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_s": round(time.perf_counter() - started, 4),
            "body": "",
            "error": repr(exc),
        }


def build_command(experiment_id: str, payload: dict[str, Any]) -> list[str]:
    if experiment_id not in EXPERIMENTS:
        raise HTTPException(status_code=404, detail="Unknown experiment")
    spec = EXPERIMENTS[experiment_id]
    defaults = spec["defaults"]
    script = str(spec["script"])

    if experiment_id == "exp02":
        num_requests = int_value(payload, "num_requests", defaults["num_requests"], 1, 10000)
        concurrency_list = str_value(payload, "concurrency_list", defaults["concurrency_list"])
        if not re.fullmatch(r"[0-9,\s]+", concurrency_list):
            raise HTTPException(status_code=400, detail="Invalid concurrency list")
        max_tokens = int_value(payload, "max_tokens", defaults["max_tokens"], 1, 8192)
        label = safe_label(payload.get("label"), defaults["label"])
        return [
            PYTHON,
            script,
            "--num-requests",
            str(num_requests),
            "--concurrency-list",
            concurrency_list,
            "--max-tokens",
            str(max_tokens),
            "--label",
            label,
        ]

    if experiment_id == "exp03":
        topic_limit = int_value(payload, "topic_limit", defaults["topic_limit"], 1, 100)
        questions_per_topic = int_value(payload, "questions_per_topic", defaults["questions_per_topic"], 1, 50)
        concurrency = int_value(payload, "concurrency", defaults["concurrency"], 1, 100)
        label = safe_label(payload.get("label"), defaults["label"])
        return [
            PYTHON,
            script,
            "--modes",
            "sequential,async",
            "--topic-limit",
            str(topic_limit),
            "--questions-per-topic",
            str(questions_per_topic),
            "--concurrency",
            str(concurrency),
            "--label",
            label,
        ]

    if experiment_id == "exp07":
        num_requests = int_value(payload, "num_requests", defaults["num_requests"], 1, 10000)
        vllm_concurrency = int_value(payload, "vllm_concurrency", defaults["vllm_concurrency"], 1, 1000)
        max_tokens = int_value(payload, "max_tokens", defaults["max_tokens"], 1, 8192)
        label = safe_label(payload.get("label"), defaults["label"])
        command = [
            PYTHON,
            script,
            "--num-requests",
            str(num_requests),
            "--vllm-concurrency",
            str(vllm_concurrency),
            "--max-tokens",
            str(max_tokens),
            "--label",
            label,
        ]
        if bool_value(payload, "include_direct_transformers", defaults["include_direct_transformers"]):
            command.append("--include-direct-transformers")
        return command

    raise HTTPException(status_code=404, detail="Unknown experiment")


def run_process(job: Job) -> None:
    try:
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        process = subprocess.Popen(
            job.command,
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        job.process = process
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\n")
            job.lines.append(line)
            job.output.put(line)
        job.returncode = process.wait()
        job.status = "completed" if job.returncode == 0 else "failed"
        job.output.put(f"[job:{job.status}] returncode={job.returncode}")
    except Exception as exc:
        job.status = "failed"
        job.returncode = -1
        job.output.put(f"[job:failed] {exc!r}")
    finally:
        job.output.put("__END__")


def safe_artifact_path(raw_path: str) -> Path:
    candidate = (PROJECT_ROOT / raw_path).resolve()
    allowed_roots = [RESULTS_ROOT.resolve(), VLLM_ROOT.resolve()]
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Path outside artifact roots")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return candidate


def latest_artifacts(experiment_id: str) -> dict[str, Any]:
    spec = EXPERIMENTS[experiment_id]
    results_dir: Path = spec["results_dir"]
    results_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [p for p in results_dir.iterdir() if p.suffix.lower() in {".svg", ".md"}],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    svg = next((p for p in files if p.suffix.lower() == ".svg"), None)
    md = next((p for p in files if p.suffix.lower() == ".md"), None)
    markdown = md.read_text(encoding="utf-8", errors="replace") if md else ""
    return {
        "experiment_id": experiment_id,
        "svg": rel_path(svg) if svg else "",
        "markdown": rel_path(md) if md else "",
        "markdown_content": markdown,
        "files": [
            {
                "path": rel_path(path),
                "name": path.name,
                "mtime": path.stat().st_mtime,
                "type": path.suffix.lower().lstrip("."),
            }
            for path in files[:12]
        ],
    }


def rel_path(path: Path | None) -> str:
    if not path:
        return ""
    return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))


def parse_vllm_metrics(metrics: str) -> dict[str, float]:
    values = {
        "running": 0.0,
        "waiting": 0.0,
        "gpu_cache_usage": 0.0,
        "prefix_hit_rate": 0.0,
    }
    for line in metrics.splitlines():
        if line.startswith("#") or "vllm" not in line:
            continue
        match = re.search(r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$", line)
        if not match:
            continue
        try:
            number = float(match.group(1))
        except ValueError:
            continue
        lower = line.lower()
        if "num_requests_running" in lower:
            values["running"] = max(values["running"], number)
        elif "num_requests_waiting" in lower:
            values["waiting"] = max(values["waiting"], number)
        elif "gpu_cache_usage" in lower:
            values["gpu_cache_usage"] = max(values["gpu_cache_usage"], number)
        elif "prefix" in lower and "hit" in lower and "rate" in lower:
            values["prefix_hit_rate"] = max(values["prefix_hit_rate"], number)
    return values


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/api/experiments")
async def experiments() -> JSONResponse:
    return JSONResponse(
        {
            key: {
                "id": key,
                "title": value["title"],
                "description": value["description"],
                "defaults": value["defaults"],
            }
            for key, value in EXPERIMENTS.items()
        }
    )


@app.get("/api/status")
async def status() -> JSONResponse:
    root = "http://localhost:8000"
    health = http_get(f"{root}/health", timeout=2)
    models = http_get(f"{root}/v1/models", timeout=2)
    metrics = http_get(f"{root}/metrics", timeout=2)
    model_name = "unknown"
    max_model_len = ""
    if models["ok"]:
        try:
            data = json.loads(models["body"])
            first = (data.get("data") or [{}])[0]
            model_name = first.get("id") or first.get("root") or "unknown"
            max_model_len = str(first.get("max_model_len") or "")
        except Exception:
            pass
    parsed_metrics = parse_vllm_metrics(metrics["body"]) if metrics["ok"] else {}
    return JSONResponse(
        {
            "vllm_ready": health["ok"],
            "models_ready": models["ok"],
            "metrics_ready": metrics["ok"],
            "model": model_name,
            "max_model_len": max_model_len,
            "metrics": parsed_metrics,
            "active_jobs": sum(1 for job in JOBS.values() if job.status == "running"),
        }
    )


@app.post("/api/run/{experiment_id}")
async def run_experiment(experiment_id: str, request: Request) -> JSONResponse:
    payload = await request.json()
    command = build_command(experiment_id, payload)
    job = Job(id=str(uuid4()), experiment_id=experiment_id, command=command)
    with JOBS_LOCK:
        JOBS[job.id] = job
    thread = threading.Thread(target=run_process, args=(job,), daemon=True)
    thread.start()
    return JSONResponse(
        {
            "job_id": job.id,
            "experiment_id": experiment_id,
            "command": " ".join(command),
        }
    )


@app.get("/api/jobs")
async def jobs() -> JSONResponse:
    with JOBS_LOCK:
        rows = list(JOBS.values())
    rows.sort(key=lambda job: job.started_at, reverse=True)
    return JSONResponse(
        [
            {
                "id": job.id,
                "experiment_id": job.experiment_id,
                "status": job.status,
                "returncode": job.returncode,
                "started_at": job.started_at,
                "command": " ".join(job.command),
                "tail": job.lines[-12:],
            }
            for job in rows[:20]
        ]
    )


@app.get("/api/events/{job_id}")
async def events(job_id: str) -> StreamingResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def generator():
        index = 0
        while True:
            while index < len(job.lines):
                line = job.lines[index]
                index += 1
                yield f"data: {json.dumps({'line': line, 'status': job.status}, ensure_ascii=False)}\n\n"
            if job.status != "running":
                yield f"data: {json.dumps({'done': True, 'status': job.status, 'returncode': job.returncode})}\n\n"
                break
            try:
                item = job.output.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.2)
                continue
            if item == "__END__":
                yield f"data: {json.dumps({'done': True, 'status': job.status, 'returncode': job.returncode})}\n\n"
                break

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/artifacts/{experiment_id}")
async def artifacts(experiment_id: str) -> JSONResponse:
    if experiment_id not in EXPERIMENTS:
        raise HTTPException(status_code=404, detail="Unknown experiment")
    return JSONResponse(latest_artifacts(experiment_id))


@app.get("/api/file")
async def artifact_file(path: str) -> FileResponse:
    target = safe_artifact_path(path)
    media_type = "image/svg+xml" if target.suffix.lower() == ".svg" else "text/plain"
    return FileResponse(target, media_type=media_type)
