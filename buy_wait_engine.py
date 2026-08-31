"""
Buy/Wait Engine (H5). Determinista. Fuente: V2.1 §12 + V1.3 §7.7.

Regla no negociable: "No recomendar esperar indefinidamente. Debe existir
fecha límite o condición concreta de revisión" (V2.1 §12). Si la evidencia
es insuficiente, la salida es NEUTRO, nunca "esperar" sin condición.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from domain import (
    BuyWaitResult, BuyWaitRecommendation, RankedOffer, StockStatus,
    PromotionStatus,
)

# Umbral de "vence pronto" para promociones confirmadas (V2.1 §12, tabla de señales).
VENCE_PRONTO_DIAS = 3


class BuyWaitEngine:
    def evaluate(
        self,
        top_offer: RankedOffer,
        urgencia: str | None = None,
        promotion_rules_by_id: dict | None = None,
        evaluation_date: datetime | None = None,
    ) -> BuyWaitResult:
        now = evaluation_date or datetime.now(timezone.utc)
        rules_by_id = promotion_rules_by_id or {}
        offer = top_offer.offer
        price_result = top_offer.price_result

        señales_comprar: list[str] = []
        señales_esperar: list[str] = []

        # Señal: promoción con beneficio alto QUE ADEMÁS vence pronto -> comprar.
        # Bug corregido en pruebas H5: antes se disparaba "comprar" con
        # cualquier promoción de beneficio alto, sin chequear vigencia real,
        # lo que pisaba la urgencia baja explícita del usuario. La tabla de
        # V2.1 §12 exige AMBAS condiciones: vence pronto + beneficio alto.
        for promo in price_result.promotions_aplicadas:
            if promo.status != PromotionStatus.CONFIRMADA:
                continue
            beneficio_alto = (
                price_result.precio_publicado
                and (promo.beneficio_efectivo or Decimal("0")) / price_result.precio_publicado >= Decimal("0.10")
            )
            rule = rules_by_id.get(promo.promotion_id)
            vence_pronto = (
                rule is not None
                and rule.vigencia_hasta is not None
                and (rule.vigencia_hasta - now) <= timedelta(days=VENCE_PRONTO_DIAS)
            )
            if beneficio_alto and vence_pronto:
                señales_comprar.append("promoción con beneficio alto vence pronto")

        # Señal: stock escaso + oferta buena -> aumentar urgencia de comprar.
        if offer.stock_status == StockStatus.LIMITADO:
            señales_comprar.append("stock limitado")

        if offer.stock_status == StockStatus.SIN_STOCK:
            # No tiene sentido "comprar ahora" algo sin stock.
            return BuyWaitResult(
                recommendation=BuyWaitRecommendation.NEUTRO,
                confidence=Decimal("0.3"),
                reason="La mejor oferta no tiene stock confirmado; no se puede recomendar comprar ahora.",
                review_condition="Revisar cuando vuelva a haber stock.",
            )

        # Señal: usuario con urgencia alta -> priorizar disponibilidad/comprar.
        if urgencia == "alta":
            señales_comprar.append("el usuario indicó urgencia")

        # Señal: usuario sin apuro + sin evidencia de vencimiento -> puede
        # sugerir esperar, PERO solo si damos una condición concreta.
        if urgencia == "baja" and not señales_comprar:
            señales_esperar.append("el usuario no tiene apuro y no hay promoción por vencer")

        if señales_comprar:
            return BuyWaitResult(
                recommendation=BuyWaitRecommendation.COMPRAR,
                confidence=Decimal("0.8") if len(señales_comprar) > 1 else Decimal("0.6"),
                reason="; ".join(señales_comprar),
            )

        if señales_esperar:
            # Regla no negociable: SIEMPRE con fecha/condición concreta.
            fecha_revision = (now + timedelta(days=7)).date().isoformat()
            return BuyWaitResult(
                recommendation=BuyWaitRecommendation.ESPERAR,
                confidence=Decimal("0.5"),
                reason="; ".join(señales_esperar),
                review_condition=f"Revisar de nuevo el {fecha_revision} o si aparece una promoción mejor.",
            )

        # Sin evidencia suficiente en ninguna dirección -> NEUTRO, nunca
        # "esperar" sin condición ni "comprar" sin motivo.
        return BuyWaitResult(
            recommendation=BuyWaitRecommendation.NEUTRO,
            confidence=Decimal("0.4"),
            reason="No hay evidencia suficiente para recomendar con confianza.",
        )
