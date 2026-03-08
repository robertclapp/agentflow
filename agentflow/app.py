from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agentflow.defaults import load_default_pipeline_yaml
from agentflow.loader import load_pipeline_from_text
from agentflow.orchestrator import Orchestrator
from agentflow.specs import PipelineSpec
from agentflow.store import RunStore


def _parse_pipeline_payload(payload: dict[str, Any]) -> PipelineSpec:
    try:
        if "yaml" in payload:
            return load_pipeline_from_text(payload["yaml"])
        return PipelineSpec.model_validate(payload["pipeline"] if "pipeline" in payload else payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def create_app(*, store: RunStore | None = None, orchestrator: Orchestrator | None = None) -> FastAPI:
    store = store or RunStore(os.getenv("AGENTFLOW_RUNS_DIR", ".agentflow/runs"))
    orchestrator = orchestrator or Orchestrator(
        store=store,
        max_concurrent_runs=int(os.getenv("AGENTFLOW_MAX_CONCURRENT_RUNS", "2")),
    )
    app = FastAPI(title="AgentFlow", version="0.1.0")
    app.state.store = store
    app.state.orchestrator = orchestrator

    base_dir = os.path.join(os.path.dirname(__file__), "web")
    templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))
    app.mount("/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "example": load_default_pipeline_yaml()},
        )

    @app.get("/api/examples/default")
    async def default_example() -> JSONResponse:
        return JSONResponse({"yaml": load_default_pipeline_yaml()})

    @app.post("/api/runs/validate")
    async def validate_run(request: Request) -> JSONResponse:
        payload = await request.json()
        pipeline = _parse_pipeline_payload(payload)
        return JSONResponse({"ok": True, "pipeline": pipeline.model_dump(mode="json")})

    @app.post("/api/runs")
    async def create_run(request: Request) -> JSONResponse:
        payload = await request.json()
        pipeline = _parse_pipeline_payload(payload)
        run = await app.state.orchestrator.submit(pipeline)
        return JSONResponse(run.model_dump(mode="json"))

    @app.get("/api/runs")
    async def list_runs() -> JSONResponse:
        return JSONResponse([run.model_dump(mode="json") for run in app.state.store.list_runs()])

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> JSONResponse:
        try:
            run = app.state.store.get_run(run_id)
        except KeyError as exc:  # pragma: no cover - exercised by API callers only
            raise HTTPException(status_code=404, detail="run not found") from exc
        return JSONResponse(run.model_dump(mode="json"))

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> JSONResponse:
        try:
            run = await app.state.orchestrator.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return JSONResponse(run.model_dump(mode="json"))

    @app.post("/api/runs/{run_id}/rerun")
    async def rerun(run_id: str) -> JSONResponse:
        try:
            run = await app.state.orchestrator.rerun(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return JSONResponse(run.model_dump(mode="json"))

    @app.get("/api/runs/{run_id}/events")
    async def get_events(run_id: str) -> JSONResponse:
        if run_id not in {run.id for run in app.state.store.list_runs()}:
            raise HTTPException(status_code=404, detail="run not found")
        return JSONResponse([event.model_dump(mode="json") for event in app.state.store.get_events(run_id)])

    @app.get("/api/runs/{run_id}/artifacts/{node_id}/{name}")
    async def get_artifact(run_id: str, node_id: str, name: str) -> PlainTextResponse:
        try:
            content = app.state.store.read_artifact_text(run_id, node_id, name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="artifact not found") from exc
        return PlainTextResponse(content)

    @app.get("/api/runs/{run_id}/stream")
    async def stream_run(run_id: str):
        if run_id not in {run.id for run in app.state.store.list_runs()}:
            raise HTTPException(status_code=404, detail="run not found")
        queue = await app.state.store.subscribe(run_id)

        async def event_stream():
            try:
                for cached in app.state.store.get_events(run_id):
                    yield f"data: {cached.model_dump_json()}\n\n"
                while True:
                    event = await asyncio.to_thread(queue.get)
                    yield f"data: {event.model_dump_json()}\n\n"
                    run = app.state.store.get_run(run_id)
                    if run.status.value in {"completed", "failed", "cancelled"} and event.type == "run_completed":
                        break
            finally:
                await app.state.store.unsubscribe(run_id, queue)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/health")
    async def health() -> JSONResponse:
        runs = app.state.store.list_runs()
        return JSONResponse(
            {
                "ok": True,
                "runs": {
                    "total": len(runs),
                    "queued": sum(run.status.value == "queued" for run in runs),
                    "running": sum(run.status.value in {"running", "cancelling"} for run in runs),
                },
            }
        )

    return app
