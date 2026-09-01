"""
Ranking Engine (H5). Determinista. Fuente: V2.1 §11 + V1.3 §10.

Reglas no negociables (recordadas de la auditoría de consistencia, hallazgo
#6 - el ejemplo de 4 slots fijos del Plan de Desarrollo es solo ilustrativo,
NO un contrato rígido):
- Mostrar 2-4 opciones "según calidad real", nunca rellenar con productos
  deficientes solo para completar.
- Si dos ofertas están dentro del umbral de empate, no forzar un ganador.
- El score interno NO se muestra al usuario salvo que lo pida (eso es H7).
"""

from __future__ import annotations
from decimal import Decimal

from domain import Offer, PriceResult, RankedOffer, VerificationStatus

# Ponderaciones iniciales orientativas (V2.1 §11, V1.3 §10) - versionadas.
DEFAULT_WEIGHTS = {
    "costo_efectivo": Decimal("0.30"),
    "financiacion": Decimal("0.20"),
    "promociones": Decimal("0.15"),
    "calificacion": Decimal("0.15"),
    "stock": Decimal("0.10"),
    "garantia": Decimal("0.10"),
}

# Umbral de empate: si la diferencia relativa de score es menor a esto,
# se consideran equivalentes (V1.3 §10.2). Valor conservador para H5;
# calibrar con datos reales en H10 (Plan de Desarrollo §17.4).
EMPATE_UMBRAL_RELATIVO = Decimal("0.03")  # 3% de diferencia en el score combinado
# Bug real detectado en pruebas con datos reales de MercadoLibre/Frávega:
# dos ofertas con precios que difieren un 5-10% se marcaban "empatadas"
# porque el score combinado las acercaba (financiación/calificación/stock
# suelen quedar iguales cuando la fuente real no informa esos datos, y el
# precio pesa solo 30%). Ahora el empate exige AMBAS cosas: score parecido
# Y precio parecido - así no se llama "empate" a algo con precios bien
# distintos solo porque el resto de los factores coincide por default.
EMPATE_UMBRAL_PRECIO = Decimal("0.03")  # 3% de diferencia en costo efectivo

MAX_OPCIONES = 4
MIN_OPCIONES_CALIDAD = 2


class RankingEngine:
    def rank(
        self,
        offers: list[Offer],
        price_results: list[PriceResult],
        weights: dict[str, Decimal] | None = None,
    ) -> list[RankedOffer]:
        w = weights or DEFAULT_WEIGHTS
        pairs = list(zip(offers, price_results))

        scored: list[tuple[Offer, PriceResult, Decimal, list[str]]] = []
        max_costo = max((pr.costo_efectivo for _, pr in pairs), default=Decimal("1")) or Decimal("1")

        for offer, price_result in pairs:
            score, factors = self._score(offer, price_result, w, max_costo)
            scored.append((offer, price_result, score, factors))

        # Orden descendente por score (mayor score = mejor oferta).
        scored.sort(key=lambda t: t[2], reverse=True)

        # No rellenar con productos deficientes: cortamos en MAX_OPCIONES,
        # pero si hay menos de MIN_OPCIONES_CALIDAD ofertas reales, mostramos
        # las que haya (puede ser 0 o 1) - nunca inventamos relleno.
        top = scored[:MAX_OPCIONES]

        ranked: list[RankedOffer] = []
        for i, (offer, price_result, score, factors) in enumerate(top, start=1):
            label = self._label_for(i, top, offer, price_result)
            ranked.append(RankedOffer(
                offer=offer,
                rank=i,
                internal_score=score,
                key_factors=factors,
                price_result=price_result,
                verification_status=offer.provenance.verification_status,
                label=label,
            ))

        self._marcar_empates(ranked)
        return ranked

    def _score(
        self,
        offer: Offer,
        pr: PriceResult,
        w: dict[str, Decimal],
        max_costo: Decimal,
    ) -> tuple[Decimal, list[str]]:
        factors: list[str] = []

        # Costo efectivo: menor es mejor -> invertimos normalizando contra el máximo.
        costo_norm = Decimal("1") - (pr.costo_efectivo / max_costo if max_costo else Decimal("0"))
        costo_norm = max(Decimal("0"), min(Decimal("1"), costo_norm))
        if costo_norm >= Decimal("0.7"):
            factors.append("mejor costo efectivo")

        # Financiación: bonus si tiene cuotas sin interés verificadas.
        tiene_financiacion_verificada = any(
            f.sin_interes_declarado and f.financing_verified for f in offer.financing
        )
        financiacion_score = Decimal("1") if tiene_financiacion_verificada else Decimal("0.3")
        if tiene_financiacion_verificada:
            factors.append("cuotas sin interés verificadas")

        # Promociones: bonus proporcional al reintegro/descuento sobre el precio.
        beneficio_total = pr.descuento_inmediato + pr.reintegro_esperado
        promo_score = min(Decimal("1"), beneficio_total / pr.precio_publicado) if pr.precio_publicado else Decimal("0")
        if beneficio_total > 0:
            factors.append("promoción aplicada")

        # Calificación: normalizada sobre 5.
        calif_score = (offer.rating / Decimal("5")) if offer.rating is not None else Decimal("0.5")
        if offer.rating is not None and offer.rating >= Decimal("4.5"):
            factors.append("muy bien calificado")

        # Stock.
        from domain import StockStatus
        stock_score = {
            StockStatus.DISPONIBLE: Decimal("1"),
            StockStatus.LIMITADO: Decimal("0.5"),
            StockStatus.SIN_STOCK: Decimal("0"),
            StockStatus.NO_CONFIRMADO: Decimal("0.4"),
        }[offer.stock_status]
        if offer.stock_status == StockStatus.SIN_STOCK:
            factors.append("sin stock")

        # Garantía: presente o no (no tenemos escala fina en el modelo mock).
        garantia_score = Decimal("1") if offer.warranty else Decimal("0.5")

        score = (
            w["costo_efectivo"] * costo_norm
            + w["financiacion"] * financiacion_score
            + w["promociones"] * promo_score
            + w["calificacion"] * calif_score
            + w["stock"] * stock_score
            + w["garantia"] * garantia_score
        )
        return score, factors

    @staticmethod
    def _label_for(rank: int, top: list, offer: Offer, price_result: PriceResult) -> str | None:
        if rank == 1:
            return "Mejor oferta"
        # Ver si esta es la de menor costo efectivo o mejor financiación entre
        # las mostradas, para dar etiquetas útiles (V1.3 §15.2).
        costos = [pr.costo_efectivo for _, pr, _, _ in top]
        if price_result.costo_efectivo == min(costos):
            return "Mejor precio"
        return None

    @staticmethod
    def _marcar_empates(ranked: list[RankedOffer]) -> None:
        """V1.3 §10.2: si dos opciones son equivalentes, no forzar un ganador
        - se anota en key_factors para que el Response Composer (H7) lo
        muestre como empate en vez de inventar una diferencia. Requiere
        score Y precio parecidos (ver comentario junto a las constantes)."""
        for i in range(len(ranked) - 1):
            a, b = ranked[i], ranked[i + 1]
            if a.internal_score == 0:
                continue
            diff_score = abs(a.internal_score - b.internal_score) / a.internal_score

            precio_a = a.price_result.costo_efectivo
            precio_b = b.price_result.costo_efectivo
            if precio_a == 0:
                continue
            diff_precio = abs(precio_a - precio_b) / precio_a

            if diff_score < EMPATE_UMBRAL_RELATIVO and diff_precio < EMPATE_UMBRAL_PRECIO:
                a.key_factors.append(f"empatado con rank {b.rank}")
                b.key_factors.append(f"empatado con rank {a.rank}")
