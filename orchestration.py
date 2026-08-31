"""
Contratos del ciclo de Orquestación (H2).
Fuente: Espec. Técnica Maestra V2.1 §4 (Orquestador y ciclo de ejecución)
         + Plan de Desarrollo M02 (Orquestador), M03 (Decision & Policy).

Estos modelos NO ejecutan nada; son el "idioma común" entre Intent Router,
Task Planner, Policy Engine y (en H3+) el resto de los módulos de dominio.
"""

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from pydantic import BaseModel, Field

from domain import Offer, PriceResult, RankedOffer, BuyWaitResult


# ---------------------------------------------------------------------------
# Intención (Intent Router) - ver casos de uso CU-01..CU-15 de V1.3
# ---------------------------------------------------------------------------

class IntentType(str, Enum):
    BUSCAR_PRODUCTO = "buscar_producto"          # CU-01, CU-02
    EXPLICAR_RECOMENDACION = "explicar_recomendacion"  # CU-06
    GESTIONAR_MEMORIA_BANCARIA = "gestionar_memoria_bancaria"  # guardar banco/tarjeta
    CONSULTAR_MEMORIA = "consultar_memoria"      # "¿qué tenés guardado?"
    BORRAR_MEMORIA = "borrar_memoria"            # CU-12, CU-13
    CREAR_ALERTA = "crear_alerta"                # CU-14
    DESCONOCIDA = "desconocida"


class ExtractedIntent(BaseModel):
    """
    Salida del Intent Router. En H2 la extracción es determinista/reglas
    (placeholder). El principio de arquitectura dice que esto eventualmente
    lo hace el LLM (comprensión/extracción) - por eso queda detrás de una
    interfaz reemplazable (ver intent_router.py).
    """
    intent_type: IntentType
    entities: dict[str, str] = Field(default_factory=dict)
    missing_critical_fields: list[str] = Field(default_factory=list)
    confidence: float = 1.0  # 0-1; en el stub siempre 1.0 (reglas exactas)


# ---------------------------------------------------------------------------
# Task Planner - ORQ-03 del Plan de Desarrollo
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    ASK_CLARIFICATION = "ask_clarification"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    MEMORY_DELETE = "memory_delete"
    SEARCH = "search"
    NORMALIZE = "normalize"
    EVALUATE_PROMOTIONS = "evaluate_promotions"
    CALCULATE_PRICING = "calculate_pricing"
    RANK_OFFERS = "rank_offers"
    EVALUATE_BUY_WAIT = "evaluate_buy_wait"
    CREATE_ALERT = "create_alert"
    EXPLAIN_LAST_RECOMMENDATION = "explain_last_recommendation"


class TaskPlan(BaseModel):
    tasks: list[TaskType]
    requires_clarification: bool = False
    clarification_question: str | None = None
    requires_user_confirmation: bool = False  # ej: borrado total de memoria


# ---------------------------------------------------------------------------
# Policy Engine - Decision & Policy Layer / Action Authorization Layer
# (V2.1 §3 y CONSOLIDADA §17 - Action Authorization Layer)
# ---------------------------------------------------------------------------

class PolicyDecision(BaseModel):
    allowed_tasks: list[TaskType]
    blocked_tasks: list[TaskType] = Field(default_factory=list)
    block_reasons: dict[str, str] = Field(default_factory=dict)  # task -> motivo
    requires_user_confirmation: bool = False


# ---------------------------------------------------------------------------
# Request / Trace / Result - contrato externo del Orquestador (ORQ-01, ORQ-06)
# ---------------------------------------------------------------------------

class OrchestratorRequest(BaseModel):
    message: str
    user_id: str
    session_id: str
    conversation_id: str | None = None
    # Flags de consentimiento/configuración que en H6 vendrán de Memory real;
    # por ahora se pasan explícitos para poder testear Policy Engine aislado.
    consentimiento_memoria_bancaria: bool = False
    alertas_habilitadas: bool = False


class TraceStep(BaseModel):
    step: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str | None = None


class OrchestrationResult(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    intent: ExtractedIntent
    task_plan: TaskPlan
    policy_decision: PolicyDecision
    trace: list[TraceStep] = Field(default_factory=list)
    # Campos de depuración H3: hasta que exista Response Composer (H7),
    # exponemos esto crudo para poder validar el pipeline end-to-end.
    # NO es la forma final de respuesta al usuario.
    offers_found: list[Offer] = Field(default_factory=list)
    price_results: list[PriceResult] = Field(default_factory=list)  # alineado por índice con offers_found
    ranked_offers: list[RankedOffer] = Field(default_factory=list)
    buy_wait_result: BuyWaitResult | None = None
