"""
Offer Normalizer (H3). Fuente: Plan de Desarrollo M06 + V2.1 §9.1
(normalización mínima: producto canónico, vendedor, precio/moneda, stock,
envío, financiación, promociones, fuente/timestamp, nivel de verificación).

Principio clave (V1.3 §4, "Verificación"): si un dato no vino en la fuente,
NO se inventa. Se deja en None / estado no confirmado, nunca se asume un
valor por default silencioso (ej.: no asumimos envío gratis si la fuente no
lo especifica).

Cada fuente tiene su propio mapper porque cada una trae un esquema distinto.
Agregar una fuente real (H3+) significa agregar UNA función acá, sin tocar
SearchService ni el resto del sistema.
"""

from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from domain import (
    Offer, Product, FinancingPlan, Provenance,
    StockStatus, VerificationStatus, SourceTier,
)
from search import SearchCriteria, SearchResult


def _slugify(text: str) -> str:
    return "-".join(text.lower().split())[:40]


def _map_stock_source_a(value: str) -> StockStatus:
    return {
        "en_stock": StockStatus.DISPONIBLE,
        "stock_limitado": StockStatus.LIMITADO,
        "sin_stock": StockStatus.SIN_STOCK,
    }.get(value, StockStatus.NO_CONFIRMADO)


def _map_stock_source_b(value: str) -> StockStatus:
    return {
        "available": StockStatus.DISPONIBLE,
        "limited": StockStatus.LIMITADO,
        "out_of_stock": StockStatus.SIN_STOCK,
    }.get(value, StockStatus.NO_CONFIRMADO)


def _normalize_source_a(raw: dict, categoria: str, tier: SourceTier) -> Offer:
    precio = Decimal(str(raw["precio_ars"]))
    cuotas = raw.get("cuotas_cantidad")
    financing = []
    if cuotas:
        sin_interes = bool(raw.get("cuotas_sin_interes"))
        monto_cuota = (precio / cuotas).quantize(Decimal("1"))
        financing.append(FinancingPlan(
            cuotas=cuotas,
            monto_cuota=monto_cuota,
            sin_interes_declarado=sin_interes,
            # Consistente porque lo derivamos nosotros mismos del precio;
            # una fuente real puede declarar un monto_cuota que NO cierre
            # matemáticamente, ahí es donde financing_verified pasaría a False.
            financing_verified=True,
        ))

    return Offer(
        offer_id=str(uuid4()),
        product=Product(
            product_id=f"{_slugify(categoria)}-{_slugify(raw['nombre_producto'])}",
            marca=raw["nombre_producto"].split()[0],
            modelo=raw["nombre_producto"],
            categoria=categoria,
        ),
        seller="Fuente A (mock)",
        price=precio,
        stock_status=_map_stock_source_a(raw.get("stock", "")),
        # La fuente A no informa costo de envío, solo días de entrega.
        # NO asumimos $0 - eso sería inventar un dato (V1.3 §4 "Verificación").
        shipping_cost=None,
        shipping_eta_days=raw.get("envio_dias"),
        financing=financing,
        rating=Decimal(str(raw["rating"])) if raw.get("rating") is not None else None,
        rating_count=raw.get("cantidad_opiniones"),
        provenance=Provenance(
            source_name="fuente_a_mock",
            source_tier=tier,
            source_timestamp=datetime.now(timezone.utc),
            verification_status=VerificationStatus.VERIFICADO,
            canonical_url=raw.get("url"),
        ),
    )


def _normalize_source_b(raw: dict, categoria: str, tier: SourceTier) -> Offer:
    precio = Decimal(str(raw["price"]["amount"]))
    installments = raw.get("installments") or {}
    cuotas = installments.get("count")
    financing = []
    if cuotas:
        sin_interes = bool(installments.get("interest_free"))
        monto_cuota = (precio / cuotas).quantize(Decimal("1"))
        financing.append(FinancingPlan(
            cuotas=cuotas,
            monto_cuota=monto_cuota,
            sin_interes_declarado=sin_interes,
            financing_verified=True,
        ))

    shipping = raw.get("shipping") or {}

    return Offer(
        offer_id=str(uuid4()),
        product=Product(
            product_id=f"{_slugify(categoria)}-{_slugify(raw['titulo'])}",
            marca=raw["titulo"].split()[0],
            modelo=raw["titulo"],
            categoria=categoria,
        ),
        seller="Fuente B (mock)",
        price=precio,
        currency=raw["price"].get("currency", "ARS"),
        stock_status=_map_stock_source_b(raw.get("availability", "")),
        shipping_cost=Decimal(str(shipping["cost"])) if "cost" in shipping else None,
        shipping_eta_days=shipping.get("eta_business_days"),
        financing=financing,
        rating=None,  # Fuente B no informa calificación - no se inventa.
        rating_count=None,
        provenance=Provenance(
            source_name="fuente_b_mock",
            source_tier=tier,
            source_timestamp=datetime.now(timezone.utc),
            # Le falta rating respecto a lo esperado -> parcialmente verificado.
            verification_status=VerificationStatus.PARCIALMENTE_VERIFICADO,
            canonical_url=raw.get("link"),
        ),
    )


_MAPPERS = {
    "fuente_a_mock": _normalize_source_a,
    "fuente_b_mock": _normalize_source_b,
}


class OfferNormalizer:
    def normalize(self, result: SearchResult) -> list[Offer]:
        offers: list[Offer] = []
        for outcome in result.outcomes:
            if not outcome.success:
                continue  # ya quedó registrado el error en el SearchResult
            mapper = _MAPPERS.get(outcome.source_name)
            if mapper is None:
                continue  # fuente sin mapper todavía - no rompe la búsqueda
            for raw in outcome.raw_offers:
                offers.append(mapper(raw, result.criteria.categoria, outcome.source_tier))
        return offers
