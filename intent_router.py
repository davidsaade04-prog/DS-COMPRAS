"""
Intent Router (H2).

IMPORTANTE: esta implementación es un STUB determinista por palabras clave.
V2.1 §1 dice que "la IA se utiliza principalmente para comprensión, extracción,
clasificación..." - es decir, en producción esto lo va a resolver un LLM.

Por eso el Orquestador depende de la interfaz `IntentRouter`, no de esta clase
concreta. Cuando conectemos el proveedor LLM (pendiente ADR-002), se agrega
`LLMIntentRouter` implementando la misma interfaz y se cambia un import.
"""

from __future__ import annotations
import re
from abc import ABC, abstractmethod

from orchestration import ExtractedIntent, IntentType

# Campos considerados críticos por tipo de intención (V1.3 §15.5:
# "solo preguntar si falta un dato crítico que cambie la recomendación").
CRITICAL_FIELDS_BY_INTENT: dict[IntentType, list[str]] = {
    IntentType.BUSCAR_PRODUCTO: ["categoria"],
}

_BANCOS_CONOCIDOS = ["banco nacion", "banco nación", "bbva", "galicia", "santander", "macro"]
_TARJETAS_CONOCIDAS = ["nativa", "visa", "mastercard", "amex", "cabal"]
_CATEGORIAS_CONOCIDAS = [
    "celular", "aire acondicionado", "heladera", "lavarropas", "televisor",
    "notebook", "parlante", "cocina", "sillon", "cama", "mesa", "silla",
]

# Sinónimos frecuentes en Argentina que deben resolver a una categoría
# conocida del catálogo. Bug real detectado en pruebas: "teléfono" (muy
# común) no estaba mapeado y el agente preguntaba "¿qué producto buscás?"
# aunque el usuario ya lo había dicho con claridad.
_SINONIMOS_CATEGORIA = {
    "telefono": "celular",
    "teléfono": "celular",
    "smartphone": "celular",
    "celu": "celular",
    "heladerita": "heladera",
    "frigorifico": "heladera",
    "frigorífico": "heladera",
    "freezer": "heladera",
    "tv": "televisor",
    "living": "sillon",
    "pc": "notebook",
    "laptop": "notebook",
    "compu": "notebook",
    "computadora": "notebook",
    "split": "aire acondicionado",
    "a/a": "aire acondicionado",
}


def _contains_term(text: str, term: str) -> bool:
    """
    Coincidencia por límite de palabra, NO substring plano.
    Bug detectado en pruebas H2: "avisame" contiene "visa" como substring;
    "parrilla" contiene "silla". `in text` daba falsos positivos.
    """
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


class IntentRouter(ABC):
    @abstractmethod
    def extract(self, message: str) -> ExtractedIntent: ...


class RuleBasedIntentRouter(IntentRouter):
    """Stub determinista para H2. Ver docstring del módulo."""

    def extract(self, message: str) -> ExtractedIntent:
        text = message.lower().strip()
        intent_type = self._classify(text)
        entities = self._extract_entities(text)

        missing = [
            f for f in CRITICAL_FIELDS_BY_INTENT.get(intent_type, [])
            if f not in entities
        ]

        return ExtractedIntent(
            intent_type=intent_type,
            entities=entities,
            missing_critical_fields=missing,
        )

    def _classify(self, text: str) -> IntentType:
        # Orden importa: un mensaje de búsqueda puede MENCIONAR banco/tarjeta
        # ("buscame un celular... tengo Nativa Mastercard") sin que la
        # intención principal sea gestionar memoria bancaria. Por eso los
        # verbos de búsqueda se chequean primero (bug detectado en pruebas
        # H2: este caso clasificaba mal como GESTIONAR_MEMORIA_BANCARIA).
        if any(p in text for p in ["busco", "buscame", "quiero comprar", "necesito un", "necesito una"]):
            return IntentType.BUSCAR_PRODUCTO
        if any(p in text for p in ["olvidá", "olvida", "borrá mis datos", "borrar mis datos", "eliminá mis datos"]):
            return IntentType.BORRAR_MEMORIA
        if any(p in text for p in ["qué tenés guardado", "que tenes guardado", "qué datos tenés", "que datos tenes"]):
            return IntentType.CONSULTAR_MEMORIA
        if any(p in text for p in ["avisame si", "avísame si", "alertame", "creame una alerta"]):
            return IntentType.CREAR_ALERTA
        if any(p in text for p in ["por qué elegiste", "por que elegiste", "por qué me recomendás", "explicame por qué"]):
            return IntentType.EXPLICAR_RECOMENDACION
        if any(p in text for p in ["tengo nativa", "tengo visa", "uso mastercard", "mi banco es", "mi tarjeta es"]):
            return IntentType.GESTIONAR_MEMORIA_BANCARIA
        # fallback: si menciona una categoría conocida o un sinónimo (con
        # límite de palabra), asumimos búsqueda.
        terminos_categoria = list(_CATEGORIAS_CONOCIDAS) + list(_SINONIMOS_CATEGORIA)
        if any(_contains_term(text, term) for term in terminos_categoria):
            return IntentType.BUSCAR_PRODUCTO
        return IntentType.DESCONOCIDA

    def _extract_entities(self, text: str) -> dict[str, str]:
        entities: dict[str, str] = {}

        categoria = next((c for c in _CATEGORIAS_CONOCIDAS if _contains_term(text, c)), None)
        if categoria is None:
            sinonimo = next((s for s in _SINONIMOS_CATEGORIA if _contains_term(text, s)), None)
            if sinonimo:
                categoria = _SINONIMOS_CATEGORIA[sinonimo]
        if categoria:
            entities["categoria"] = categoria

        banco = next((b for b in _BANCOS_CONOCIDOS if _contains_term(text, b)), None)
        if banco:
            entities["banco"] = banco

        tarjeta = next((t for t in _TARJETAS_CONOCIDAS if _contains_term(text, t)), None)
        if tarjeta:
            entities["tarjeta"] = tarjeta

        presupuesto_match = re.search(r"\$\s?([\d\.]+)", text)
        if presupuesto_match:
            entities["presupuesto"] = presupuesto_match.group(1).replace(".", "")

        if any(p in text for p in ["no tengo apuro", "sin apuro", "no urgente"]):
            entities["urgencia"] = "baja"
        elif any(p in text for p in ["urgente", "lo necesito ya", "corriendo"]):
            entities["urgencia"] = "alta"

        return entities
