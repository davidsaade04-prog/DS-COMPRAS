"""
Policy Engine / Decision & Policy Layer (H2).
Fuente: V2.1 §3 (Decision & Policy Layer) + CONSOLIDADA §17 (Action
Authorization Layer) + Plan de Desarrollo M03 (POL-01..POL-05).

Regla de diseño no negociable: esto es determinista y NO delega en el LLM.
"La capa puede bloquear una herramienta o acción aunque el Orquestador la
haya planificado" (V2.1 §3).
"""

from __future__ import annotations

from orchestration import (
    OrchestratorRequest,
    TaskPlan,
    TaskType,
    PolicyDecision,
)

# Tareas que SIEMPRE están bloqueadas en el MVP, sin excepción, pase lo que
# pase en el contexto/flags. Hoy no existen como TaskType porque ni siquiera
# se modelan (POL-03: "no compra automática", "no pago automático"), pero
# dejamos el catálogo explícito por si en el futuro alguien agrega
# TaskType.PAY o TaskType.AUTO_PURCHASE sin revisar este archivo.
HARD_BLOCKED_TASK_NAMES = {"pay", "auto_purchase", "checkout_automatico"}

# Tareas que requieren un flag de consentimiento/configuración explícito.
TASKS_REQUIRING_CONSENT = {
    TaskType.MEMORY_WRITE: "consentimiento_memoria_bancaria",
    TaskType.CREATE_ALERT: "alertas_habilitadas",
}

# Tareas irreversibles que siempre requieren confirmación explícita del
# usuario, independientemente de flags previos (V2.1 §17.1).
TASKS_REQUIRING_CONFIRMATION = {TaskType.MEMORY_DELETE}


class PolicyEngine:
    def evaluate(self, request: OrchestratorRequest, plan: TaskPlan) -> PolicyDecision:
        allowed: list[TaskType] = []
        blocked: list[TaskType] = []
        reasons: dict[str, str] = {}
        requires_confirmation = False

        for task in plan.tasks:
            # 1) Bloqueo duro por nombre (defensa en profundidad).
            if task.value in HARD_BLOCKED_TASK_NAMES:
                blocked.append(task)
                reasons[task.value] = "Acción no permitida en el MVP (POL-03)."
                continue

            # 2) Confirmación explícita obligatoria (no bloquea, pero marca flag).
            if task in TASKS_REQUIRING_CONFIRMATION:
                requires_confirmation = True
                allowed.append(task)
                continue

            # 3) Consentimiento/configuración requerida.
            consent_field = TASKS_REQUIRING_CONSENT.get(task)
            if consent_field and not getattr(request, consent_field, False):
                blocked.append(task)
                reasons[task.value] = (
                    f"Requiere '{consent_field}=True' y no fue otorgado."
                )
                continue

            allowed.append(task)

        return PolicyDecision(
            allowed_tasks=allowed,
            blocked_tasks=blocked,
            block_reasons=reasons,
            requires_user_confirmation=requires_confirmation,
        )
