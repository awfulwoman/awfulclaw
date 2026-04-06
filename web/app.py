from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8080")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "3000"))

_HERE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: Starlette):
    async with httpx.AsyncClient(base_url=AGENT_URL, timeout=130.0) as client:
        app.state.client = client
        yield


async def index(request: Request) -> FileResponse:
    return FileResponse(_HERE / "pages" / "index.html")


async def info_page(request: Request) -> FileResponse:
    return FileResponse(_HERE / "pages" / "info.html")


async def proxy_chat(request: Request) -> Response:
    body = await request.body()
    r = await request.app.state.client.post(
        "/chat", content=body, headers={"content-type": "application/json"}
    )
    return JSONResponse(r.json(), status_code=r.status_code)


async def proxy_status(request: Request) -> Response:
    r = await request.app.state.client.get("/api/status")
    return JSONResponse(r.json(), status_code=r.status_code)


async def proxy_info(request: Request) -> Response:
    name = request.path_params["name"]
    r = await request.app.state.client.get(f"/api/info/{name}")
    return JSONResponse(r.json(), status_code=r.status_code)


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/", index),
        Route("/info/{name}", info_page),
        Route("/proxy/chat", proxy_chat, methods=["POST"]),
        Route("/proxy/api/status", proxy_status),
        Route("/proxy/api/info/{name}", proxy_info),
        Mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static"),
    ],
)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
