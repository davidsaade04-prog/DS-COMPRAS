"""
Response Composer (H7). Fuente: V1.3 §15 (datos primero, breve, explicación
bajo demanda) + Anexo A (formato: imagen+modelo+calificación+precio+
financiación+promoción+entrega+etiqueta).

Esta es la ÚNICA pieza que le habla al usuario. Todo lo anterior (Orchestrator,
Promotion/Pricing/Ranking/Buy-Wait) son datos internos deterministas; acá se
convierten en texto breve, sin exponer scores técnicos (V2.1 §11: "no mostrar
el score técnico salvo que el usuario lo solicite").
"""

from __future__ import annotations
from decimal import Decimal
from pydantic import BaseModel

from domain import RankedOffer, PromotionStatus
from orchestration import OrchestrationResult


class OfferCard(BaseModel):
    rank: int
    label: str | None
    modelo: str
    seller: str
    precio_publicado: str
    costo_efectivo: str
    cuotas_texto: str
    promocion_texto: str
    envio_texto: str
    calificacion_texto: str
    empatado: bool = False
    warnings: list[str] = []


class ComposedResponse(BaseModel):
    message: str
    cards: list[OfferCard] = []
    buy_wait_text: str | None = None
    clarification_question: str | None = None
    requires_confirmation: bool = False
    # Temporal, para diagnosticar el bug reportado en Replit (categoría mal
    # detectada). Sacar cuando H7 esté maduro - no es para el usuario final.
    debug_intent: str | None = None
    debug_entities: dict[str, str] = {}
    debug_router: str | None = None


def _fmt_ars(value: Decimal | None) -> str:
    if value is None:
        return "no confirmado"
    return f"${value:,.0f}".replace(",", ".")


def _cuotas_texto(offer_financing, warnings: list[str]) -> str:
    if not offer_financing:
        return "sin financiación informada"
    plan = offer_financing[0]
    if not plan.financing_verified:
        return "cuotas informadas pero no verificadas (no se garantiza el costo)"
    tipo = "sin interés" if plan.sin_interes_declarado else "con interés"
    return f"{plan.cuotas} cuotas {tipo}"


def _promocion_texto(price_result) -> str:
    confirmadas = [p for p in price_result.promotions_aplicadas if p.status == PromotionStatus.CONFIRMADA]
    if not confirmadas:
        return "sin promoción confirmada"
    total = sum((p.beneficio_efectivo or Decimal("0")) for p in confirmadas)
    tipo = "reintegro" if price_result.reintegro_esperado > 0 else "descuento"
    return f"{tipo} de {_fmt_ars(total)} confirmado"


def _envio_texto(price_result) -> str:
    if price_result.envio is None:
        return "envío no confirmado"
    if price_result.envio == 0:
        return "envío gratis"
    return f"envío {_fmt_ars(price_result.envio)}"


def _calificacion_texto(offer) -> str:
    if offer.rating is None:
        return "sin calificación disponible"
    extra = f" ({offer.rating_count} opiniones)" if offer.rating_count else ""
    return f"{offer.rating}/5{extra}"


class ResponseComposer:
    def compose(self, result: OrchestrationResult) -> ComposedResponse:
        debug_intent = result.intent.intent_type.value
        debug_entities = dict(result.intent.entities)
        debug_router = result.intent_router_name

        # H6: flujos de memoria (consentimiento, borrado, consulta) devuelven
        # su propio mensaje ya armado - no pasan por tarjetas de ofertas.
        if result.direct_message is not None:
            return ComposedResponse(
                message=result.direct_message,
                debug_intent=debug_intent,
                debug_entities=debug_entities,
                debug_router=debug_router,
            )

        if result.task_plan.requires_clarification:
            return ComposedResponse(
                message=result.task_plan.clarification_question or "¿Podés darme más detalles?",
                clarification_question=result.task_plan.clarification_question,
                debug_intent=debug_intent,
                debug_entities=debug_entities,
                debug_router=debug_router,
            )

        if result.task_plan.requires_user_confirmation:
            return ComposedResponse(
                message="Esta acción es irreversible. Confirmá para continuar.",
                requires_confirmation=True,
                debug_intent=debug_intent,
                debug_entities=debug_entities,
                debug_router=debug_router,
            )

        if not result.ranked_offers:
            # V1.3 §16: "Sin resultados: informar y eventualmente proponer
            # ampliar filtros" - nunca inventar una oferta para no dejar
            # la respuesta vacía.
            return ComposedResponse(
                message="No encontré ofertas disponibles para eso ahora mismo. "
                        "¿Querés que pruebe con otra categoría o ampliemos el presupuesto?",
                debug_intent=debug_intent,
                debug_entities=debug_entities,
                debug_router=debug_router,
            )

        cards = [self._build_card(r) for r in result.ranked_offers]
        buy_wait_text = self._buy_wait_text(result)

        palabra = "opción" if len(cards) == 1 else "opciones"
        intro = f"Encontré {len(cards)} {palabra}:"
        return ComposedResponse(
            message=intro, cards=cards, buy_wait_text=buy_wait_text,
            debug_intent=debug_intent, debug_entities=debug_entities,
            debug_router=debug_router,
        )

    def _build_card(self, r: RankedOffer) -> OfferCard:
        pr = r.price_result
        return OfferCard(
            rank=r.rank,
            label=r.label,
            modelo=r.offer.product.modelo,
            seller=r.offer.seller,
            precio_publicado=_fmt_ars(pr.precio_publicado),
            costo_efectivo=_fmt_ars(pr.costo_efectivo),
            cuotas_texto=_cuotas_texto(r.offer.financing, pr.warnings),
            promocion_texto=_promocion_texto(pr),
            envio_texto=_envio_texto(pr),
            calificacion_texto=_calificacion_texto(r.offer),
            empatado=any("empatado" in f for f in r.key_factors),
            warnings=pr.warnings,
        )

    def _buy_wait_text(self, result: OrchestrationResult) -> str | None:
        bw = result.buy_wait_result
        if bw is None:
            return None
        prefix = {
            "comprar": "💡 Comprar ahora",
            "esperar": "💡 Conviene esperar",
            "neutro_sin_evidencia_suficiente": "💡 Sin evidencia suficiente",
        }[bw.recommendation.value]
        # Bug real detectado en pruebas: si bw.reason ya terminaba en punto,
        # quedaba "...confianza.." (doble punto) y además el prefijo NEUTRO
        # repetía casi la misma frase que el motivo ("no hay evidencia para
        # recomendar: no hay evidencia para recomendar con confianza").
        reason = bw.reason.rstrip(".")
        text = f"{prefix}: {reason}."
        if bw.review_condition:
            text += f" {bw.review_condition}"
        return text
