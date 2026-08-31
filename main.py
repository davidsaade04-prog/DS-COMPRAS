"""
DS Compras - punto de entrada único (versión "plana" para deploy fácil).

Esta es la MISMA lógica que la versión modular (carpetas app/models,
app/modules, etc.) - acá vive solo para simplificar la subida manual a
GitHub desde el celular, sin carpetas anidadas. La arquitectura interna
(Orchestrator, Promotion/Pricing/Ranking/Buy-Wait Engines, Response
Composer) es idéntica, solo cambian las rutas de import.
"""

from __future__ import annotations
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from orchestration import OrchestratorRequest, OrchestrationResult
from orchestrator import Orchestrator
from response_composer import ResponseComposer, ComposedResponse
from index_content import HTML_CONTENT

app = FastAPI(
    title="DS Compras - Agente IA de Compras",
    version="0.1.0",
    description="Backend modular. Ver Especificación Técnica Maestra V2.1.",
)

_orchestrator = Orchestrator()
_composer = ResponseComposer()


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_CONTENT


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "ds-compras-api"}


@app.post("/v1/chat", response_model=ComposedResponse)
async def chat(request: OrchestratorRequest) -> ComposedResponse:
    result = _orchestrator.run(request)
    return _composer.compose(result)


@app.post("/v1/chat/debug", response_model=OrchestrationResult)
async def chat_debug(request: OrchestratorRequest) -> OrchestrationResult:
    return _orchestrator.run(request)
