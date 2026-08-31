"""
Promotion Engine (H4). Determinista, 100% — el LLM nunca decide esto
(V2.1 §10.3: "Un modelo de IA nunca debe decidir por sí solo el resultado
numérico final de una promoción").

Fuente: V2.1 §10, §10.1 (correcciones) + adenda 10.4 (reglas Argentina).
"""

from __future__ import annotations
from datetime import datetime, timezone
import unicodedata
from decimal import Decimal

from domain import (
    Offer, PromotionRule, PromotionEvalResult, PromotionStatus, PaymentContext,
)

try:
    from zoneinfo import ZoneInfo
    _AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:  # pragma: no cover - fallback si falta tzdata en el sistema
    _AR_TZ = timezone.utc


def now_ar() -> datetime:
    """Adenda 10.4.6: evaluar vigencias contra hora local AR, no UTC crudo."""
    return datetime.now(_AR_TZ)


def _normalize(text: str) -> str:
    """
    Compara texto en español ignorando may/min y tildes.
    Bug real detectado en pruebas: la regla mock decía 'Banco Nacion' (sin
    tilde) y el usuario escribió 'Banco Nación' (con tilde, como corresponde),
    y la comparación fallaba SIEMPRE por eso - ninguna promoción bancaria
    argentina se confirmaba nunca con esos datos, algo que iba a pasar con
    cualquier usuario real que escriba bien el español.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().strip()


def _coincide_parcial(a: str, b: str) -> bool:
    """True si, normalizados, uno contiene al otro. Permite que "Nativa"
    (regla) matchee con "Nativa Mastercard" (como lo dice el usuario real) en
    cualquiera de los dos sentidos, sin exigir coincidencia exacta."""
    na, nb = _normalize(a), _normalize(b)
    return na in nb or nb in na


class PromotionEngine:
    def evaluate(
        self,
        offer: Offer,
        payment_context: PaymentContext,
        rules: list[PromotionRule],
        evaluation_date: datetime | None = None,
    ) -> list[PromotionEvalResult]:
        eval_date = evaluation_date or now_ar()
        return [self._evaluate_one(offer, payment_context, rule, eval_date) for rule in rules]

    def _evaluate_one(
        self,
        offer: Offer,
        ctx: PaymentContext,
        rule: PromotionRule,
        eval_date: datetime,
    ) -> PromotionEvalResult:
        incumplidas: list[str] = []
        no_verificables: list[str] = []

        # --- Vigencia ---
        if rule.vigencia_hasta and eval_date > rule.vigencia_hasta:
            return PromotionEvalResult(
                promotion_id=rule.promotion_id,
                status=PromotionStatus.VENCIDA,
                restricciones_incumplidas=["promoción vencida"],
            )
        if rule.vigencia_desde and eval_date < rule.vigencia_desde:
            incumplidas.append("todavía no empezó la vigencia")

        # --- Banco / medio de pago ---
        # Comparación por "contiene", no exacta: el usuario puede decir
        # "Nativa Mastercard" (nombre completo, correcto) y la regla decir
        # solo "Nativa" (abreviado) - bug real detectado en pruebas: con
        # comparación exacta, "nativa" != "nativa mastercard" y la promoción
        # nunca confirmaba con el nombre completo de la tarjeta.
        if rule.emisor_banco:
            if not ctx.banco:
                no_verificables.append("no se conoce el banco del usuario")
            elif not _coincide_parcial(rule.emisor_banco, ctx.banco):
                incumplidas.append("banco no coincide")

        if rule.medio_pago:
            if not ctx.tarjeta:
                no_verificables.append("no se conoce la tarjeta del usuario")
            elif not _coincide_parcial(rule.medio_pago, ctx.tarjeta):
                incumplidas.append("medio de pago no coincide")

        # --- Comercio (adenda 10.4.4: campaña ≠ producto/comercio) ---
        # Si la regla no especifica comercio, NO asumimos que aplica a
        # cualquiera: queda como no verificable, nunca como confirmada.
        if rule.comercio is None:
            no_verificables.append("la regla no especifica comercio aplicable")
        elif _normalize(rule.comercio) != _normalize(offer.seller):
            incumplidas.append("comercio no participante")

        # --- Categoría / producto (misma lógica que comercio) ---
        if rule.categoria_o_producto is None:
            no_verificables.append("la regla no especifica categoría/producto aplicable")
        elif _normalize(rule.categoria_o_producto) not in _normalize(offer.product.categoria):
            incumplidas.append("categoría/producto no coincide")

        # --- Monto mínimo ---
        if rule.compra_minima and offer.price < rule.compra_minima:
            incumplidas.append(f"no alcanza el monto mínimo (${rule.compra_minima})")

        # --- Cuotas aplicables ---
        if rule.cuotas_aplicables:
            cuotas_ofrecidas = {f.cuotas for f in offer.financing}
            if not cuotas_ofrecidas & set(rule.cuotas_aplicables):
                incumplidas.append("la oferta no tiene una cuota compatible con la promo")

        if incumplidas:
            return PromotionEvalResult(
                promotion_id=rule.promotion_id,
                status=PromotionStatus.NO_APLICABLE,
                restricciones_incumplidas=incumplidas,
            )

        if no_verificables:
            return PromotionEvalResult(
                promotion_id=rule.promotion_id,
                status=PromotionStatus.NO_VERIFICADA,
                restricciones_incumplidas=no_verificables,
            )

        beneficio = self._calcular_beneficio(offer.price, rule)
        return PromotionEvalResult(
            promotion_id=rule.promotion_id,
            status=PromotionStatus.CONFIRMADA,
            beneficio_efectivo=beneficio,
        )

    @staticmethod
    def _calcular_beneficio(precio: Decimal, rule: PromotionRule) -> Decimal:
        """Adenda 10.4.3: el tope SIEMPRE se respeta, nunca se aplica el
        porcentaje 'libre' si hay tope declarado."""
        if rule.beneficio_pct is not None:
            bruto = precio * rule.beneficio_pct / Decimal("100")
        elif rule.beneficio_monto is not None:
            bruto = rule.beneficio_monto
        else:
            return Decimal("0")

        if rule.tope_reintegro is not None:
            return min(bruto, rule.tope_reintegro)
        return bruto
