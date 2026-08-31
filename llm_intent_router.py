"""
LLMIntentRouter (reemplaza el stub por reglas de RuleBasedIntentRouter).

Usa el Claude API para comprensión real de lenguaje natural en vez de una
lista fija de palabras clave - resuelve de raíz el problema de "no puedo
agregar sinónimos a mano para siempre" (V2.1 §1: "la IA se utiliza
principalmente para comprensión, extracción y clasificación").

Implementa la misma interfaz IntentRouter, así que Orchestrator no necesita
ningún otro cambio.

Requiere la variable de entorno ANTHROPIC_API_KEY (Render: Environment >
Add Environment Variable). Nunca se hardcodea la key en el código-
"""

from __future__ import annotations
import json
import os

from intent_router import IntentRouter, CRITICAL_FIELDS_BY_INTENT
from orchestration import ExtractedIntent, IntentType

_CATEGORIAS_VALIDAS = [
    "celular", "aire acondicionado", "heladera", "lavarropas", "televisor",
    "notebook", "parlante", "cocina", "sillon", "cama", "mesa", "silla",
]

_SYSTEM_PROMPT = f"""Sos el clasificador de intención de un agente de compras argentino.

Dado un mensaje del usuario, devolvé SOLO un JSON (sin texto adicional, sin \
markdown) con esta forma exacta:

{{
  "intent_type": uno de ["buscar_producto","explicar_recomendacion","gestionar_memoria_bancaria","consultar_memoria","borrar_memoria","crear_alerta","desconocida"],
  "entities": {{
    "categoria": uno de {_CATEGORIAS_VALIDAS} (solo si aplica; omitir si no aplica),
    "presupuesto": string solo con dígitos (opcional),
    "urgencia": "alta" o "baja" (opcional),
    "banco": nombre del banco tal cual lo dijo el usuario (opcional),
    "tarjeta": nombre de la tarjeta/medio de pago tal cual lo dijo el usuario (opcional)
  }}
}}

Normalizá sinónimos y jerga argentina a la categoría más parecida de la \
lista (ej: "split", "equipo de aire" -> "aire acondicionado"; "teléfono", \
"smartphone", "celu" -> "celular"; "compu", "laptop" -> "notebook"). \
Si el mensaje no tiene que ver con ninguna categoría de la lista, omitir \
"categoria" (NO inventar una). No inventes ningún campo que el usuario no \
haya mencionado, ni resolver un intent_type distinto de "desconocida" si \
el mensaje es ambiguo o no encaja en ninguna categoría clara."""


class LLMIntentRouter(IntentRouter):
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        import anthropic  # import local para no romper si falta el paquete

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Falta ANTHROPIC_API_KEY. Configurala en Render > Environment."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def extract(self, message: str) -> ExtractedIntent:
        raw_text = None
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=300,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
            )
            raw_text = response.content[0].text.strip()
            # Defensivo: a veces el modelo envuelve el JSON en un bloque de
            # código markdown (```json ... ```) a pesar de que el prompt
            # pide "sin markdown". Lo despojamos antes de parsear.
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`")
                if raw_text.lower().startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            data = json.loads(raw_text)
            intent_type = IntentType(data.get("intent_type", "desconocida"))
            entities = {
                k: str(v) for k, v in (data.get("entities") or {}).items() if v
            }
        except Exception as exc:
            # Bug de diagnóstico H2 (segunda vuelta): esto fallaba en
            # silencio y no había forma de saber si el problema era de
            # parseo, de la API o de otra cosa. Ahora queda impreso en
            # Render > Logs (buscar "llm_intent_router").
            print(f"[llm_intent_router] Fallo al procesar respuesta del LLM. "
                  f"Motivo: {exc!r}. Texto crudo recibido: {raw_text!r}", flush=True)
            # V2.1 §19: un fallo de herramienta nunca debe convertirse en un
            # dato inventado. Degradamos a "desconocida" en vez de adivinar.
            intent_type = IntentType.DESCONOCIDA
            entities = {}

        missing = [
            f for f in CRITICAL_FIELDS_BY_INTENT.get(intent_type, [])
            if f not in entities
        ]
        return ExtractedIntent(
            intent_type=intent_type, entities=entities, missing_critical_fields=missing
        )
