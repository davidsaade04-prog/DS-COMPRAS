"""
Pricing Engine (H4). Determinista. Fuente: V2.1 §10.2 + adenda 10.4.2.

Conceptos que NUNCA se confunden (V1.3 §9.2):
- desembolso_inicial: lo que el usuario paga DE SU BOLSILLO ahora
  (precio - descuento inmediato + envío). Un reintegro futuro NO lo reduce.
- costo_efectivo: el costo "real" de la operación una vez descontado también
  el reintegro esperado - se usa para comparar ofertas (Ranking), no es lo
  que se paga hoy.
- costo_total_financiado: total nominal a pagar contando intereses de cuotas
  (sin netear el reintegro, que es un evento futuro separado).

Regla crítica (V2.1 §10.1): una financiación con financing_verified=False
NO puede usarse para declarar ahorro/costo confirmado. Si eso pasa, el
Pricing Engine excluye la financiación del cálculo y deja constancia en
`warnings`.

Regla de acumulación (V2.1 §10, "promociones incompatibles no se acumulan"):
si entre las promociones CONFIRMADAS hay alguna marcada `acumulable=False`,
se aplica SOLO la de mayor beneficio (no se mezclan). Si todas son
acumulables entre sí, se suman. Esta es una regla conservadora deliberada
(evita sobreestimar ahorro) — queda anotada como candidata a ADR si el
negocio define reglas de acumulación más finas.
"""

from __future__ import annotations
from decimal import Decimal

from domain import (
    Offer, FinancingPlan, PriceResult, PromotionEvalResult, PromotionRule,
    PromotionStatus,
)


class PricingEngine:
    def calculate(
        self,
        offer: Offer,
        promotion_results: list[PromotionEvalResult],
        promotion_rules_by_id: dict[str, PromotionRule],
        selected_financing: FinancingPlan | None = None,
    ) -> PriceResult:
        warnings: list[str] = []
        precio_publicado = offer.price

        aplicadas = self._resolver_acumulacion(promotion_results, promotion_rules_by_id, warnings)

        descuento_inmediato = Decimal("0")
        reintegro_esperado = Decimal("0")
        tope_aplicado_total = Decimal("0")

        for result in aplicadas:
            rule = promotion_rules_by_id[result.promotion_id]
            beneficio = result.beneficio_efectivo or Decimal("0")
            if rule.tope_reintegro is not None:
                bruto = (precio_publicado * rule.beneficio_pct / Decimal("100")
                         if rule.beneficio_pct is not None
                         else (rule.beneficio_monto or Decimal("0")))
                if bruto > rule.tope_reintegro:
                    tope_aplicado_total += rule.tope_reintegro

            if rule.tipo_beneficio == "descuento_inmediato":
                descuento_inmediato += beneficio
            else:
                reintegro_esperado += beneficio

        # --- Envío (adenda 10.4.5: no inventar $0 si no está confirmado) ---
        envio = offer.shipping_cost
        if envio is None:
            warnings.append(
                "Costo de envío no confirmado por la fuente; excluido del "
                "cálculo (no se asume gratis)."
            )
            envio_para_calculo = Decimal("0")
        else:
            envio_para_calculo = envio

        # --- Financiación / intereses (adenda 10.4.2) ---
        intereses = Decimal("0")
        costo_total_financiado = None
        if selected_financing is not None:
            if not selected_financing.financing_verified:
                warnings.append(
                    "Financiación no verificada (cuotas inconsistentes con el "
                    "precio, V2.1 §10.1): no se usa para costo confirmado."
                )
            elif not selected_financing.sin_interes_declarado:
                if selected_financing.monto_cuota is not None:
                    total_cuotas = selected_financing.monto_cuota * selected_financing.cuotas
                    intereses = max(Decimal("0"), total_cuotas - precio_publicado)
                elif selected_financing.cft is None:
                    warnings.append(
                        "Financiación con interés sin CFT ni monto de cuota: "
                        "no se puede calcular el costo total financiado (adenda 10.4.2)."
                    )

            if selected_financing.financing_verified:
                costo_total_financiado = (
                    precio_publicado - descuento_inmediato + envio_para_calculo + intereses
                )

        desembolso_inicial = precio_publicado - descuento_inmediato + envio_para_calculo
        costo_efectivo = desembolso_inicial - reintegro_esperado + intereses

        return PriceResult(
            offer_id=offer.offer_id,
            precio_publicado=precio_publicado,
            descuento_inmediato=descuento_inmediato,
            reintegro_esperado=reintegro_esperado,
            tope_aplicado=tope_aplicado_total if tope_aplicado_total > 0 else None,
            envio=envio,
            intereses=intereses,
            desembolso_inicial=desembolso_inicial,
            costo_efectivo=costo_efectivo,
            costo_total_financiado=costo_total_financiado,
            promotions_aplicadas=aplicadas,
            warnings=warnings,
        )

    @staticmethod
    def _resolver_acumulacion(
        results: list[PromotionEvalResult],
        rules_by_id: dict[str, PromotionRule],
        warnings: list[str],
    ) -> list[PromotionEvalResult]:
        confirmadas = [r for r in results if r.status == PromotionStatus.CONFIRMADA]
        if len(confirmadas) <= 1:
            # Con 0 o 1 promoción confirmada, el flag `acumulable` es
            # irrelevante (no hay nada con qué acumular). Bug detectado en
            # pruebas H4: antes se evaluaba `all(acumulable...)` incluso con
            # una sola promo, generando un warning engañoso de "no
            # acumulables detectadas" cuando en realidad no había conflicto.
            return confirmadas

        todas_acumulables = all(rules_by_id[r.promotion_id].acumulable for r in confirmadas)
        if todas_acumulables:
            return confirmadas

        warnings.append(
            "Promociones no acumulables detectadas: se aplicó solo la de "
            "mayor beneficio, el resto no se suma (V2.1 §10)."
        )
        mejor = max(confirmadas, key=lambda r: r.beneficio_efectivo or Decimal("0"))
        return [mejor]
