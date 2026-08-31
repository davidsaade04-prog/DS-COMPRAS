"""
Task Planner (H2). Fuente: Plan de Desarrollo ORQ-03, diagrama Sección 4.

En H2 esto solo devuelve el PLAN (lista ordenada de tareas). La ejecución
real de cada tarea (llamar a Search, Pricing, etc.) se conecta en H3-H6.
"""

from __future__ import annotations

from orchestration import ExtractedIntent, IntentType, TaskPlan, TaskType

# Preguntas de aclaración por campo crítico faltante (V1.3 §15.5: la pregunta
# debe ser mínima y puntual, no un formulario).
CLARIFICATION_QUESTIONS = {
    "categoria": "¿Qué producto estás buscando?",
}

# Plan estándar para una búsqueda completa (V2.1 §4.2 / diagrama Plan Sección 4).
_SEARCH_FLOW = [
    TaskType.MEMORY_READ,
    TaskType.SEARCH,
    TaskType.NORMALIZE,
    TaskType.EVALUATE_PROMOTIONS,
    TaskType.CALCULATE_PRICING,
    TaskType.RANK_OFFERS,
    TaskType.EVALUATE_BUY_WAIT,
]


class TaskPlanner:
    def plan(self, intent: ExtractedIntent) -> TaskPlan:
        if intent.missing_critical_fields:
            field = intent.missing_critical_fields[0]
            question = CLARIFICATION_QUESTIONS.get(
                field, f"Necesito un dato más: {field}."
            )
            return TaskPlan(
                tasks=[TaskType.ASK_CLARIFICATION],
                requires_clarification=True,
                clarification_question=question,
            )

        match intent.intent_type:
            case IntentType.BUSCAR_PRODUCTO:
                return TaskPlan(tasks=list(_SEARCH_FLOW))

            case IntentType.GESTIONAR_MEMORIA_BANCARIA:
                return TaskPlan(tasks=[TaskType.MEMORY_WRITE])

            case IntentType.CONSULTAR_MEMORIA:
                return TaskPlan(tasks=[TaskType.MEMORY_READ])

            case IntentType.BORRAR_MEMORIA:
                return TaskPlan(
                    tasks=[TaskType.MEMORY_DELETE],
                    requires_user_confirmation=True,
                )

            case IntentType.CREAR_ALERTA:
                return TaskPlan(tasks=[TaskType.MEMORY_READ, TaskType.CREATE_ALERT])

            case IntentType.EXPLICAR_RECOMENDACION:
                return TaskPlan(tasks=[TaskType.EXPLAIN_LAST_RECOMMENDATION])

            case _:
                return TaskPlan(
                    tasks=[TaskType.ASK_CLARIFICATION],
                    requires_clarification=True,
                    clarification_question=(
                        "No terminé de entender qué necesitás. "
                        "¿Podés contarme qué producto buscás?"
                    ),
                )
