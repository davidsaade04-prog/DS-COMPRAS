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


def _map_stock_mercadolibre(raw: dict) -> StockStatus:
    qty = raw.get("available_quantity")
    if qty is None:
        return StockStatus.NO_CONFIRMADO
    if qty <= 0:
        return StockStatus.SIN_STOCK
    if qty <= 3:
        return StockStatus.LIMITADO
    return StockStatus.DISPONIBLE


def _normalize_mercadolibre(raw: dict, categoria: str, tier: SourceTier) -> Offer:
    precio = Decimal(str(raw["price"]))

    financing = []
    installments = raw.get("installments") or {}
    if installments.get("quantity"):
        cuotas = installments["quantity"]
        monto_cuota = Decimal(str(installments["amount"])) if installments.get("amount") else None
        rate = installments.get("rate")
        sin_interes = not rate or float(rate) == 0
        financing.append(FinancingPlan(
            cuotas=cuotas,
            monto_cuota=monto_cuota,
            sin_interes_declarado=sin_interes,
            # Viene calculado por MercadoLibre, no lo derivamos nosotros -
            # lo tratamos como confiable pero queda anotado el origen.
            financing_verified=True,
        ))

    seller = raw.get("seller") or {}
    # La búsqueda pública sin autenticación a veces no trae el nombre del
    # vendedor, solo su ID - no inventamos un nombre, usamos un identificador.
    seller_label = seller.get("nickname") or f"Vendedor MercadoLibre #{seller.get('id', '?')}"

    shipping = raw.get("shipping") or {}
    # free_shipping=False no significa que sepamos el costo real - solo
    # confirmamos cuando es explícitamente gratis; si no, no confirmado
    # (adenda 10.4.5: no inventar un costo de envío).
    shipping_cost = Decimal("0") if shipping.get("free_shipping") else None

    titulo = raw.get("title") or "Producto sin nombre"
    item_id = str(raw.get("id") or uuid4())

    return Offer(
        offer_id=item_id,
        product=Product(
            product_id=item_id,
            marca=titulo.split()[0] if titulo else "",
            modelo=titulo,
            categoria=categoria,
        ),
        seller=seller_label,
        price=precio,
        currency=raw.get("currency_id", "ARS"),
        stock_status=_map_stock_mercadolibre(raw),
        shipping_cost=shipping_cost,
        shipping_eta_days=None,  # no viene en la búsqueda, solo en el detalle del item
        financing=financing,
        rating=None,  # la búsqueda pública no trae calificación - no se inventa
        rating_count=None,
        provenance=Provenance(
            source_name="mercadolibre",
            source_tier=tier,
            source_timestamp=datetime.now(timezone.utc),
            verification_status=VerificationStatus.VERIFICADO,
            canonical_url=raw.get("permalink"),
        ),
    )


def _map_stock_vtex(oferta: dict) -> StockStatus:
    qty = oferta.get("AvailableQuantity")
    if qty is None:
        return StockStatus.NO_CONFIRMADO
    if qty <= 0:
        return StockStatus.SIN_STOCK
    if qty <= 3:
        return StockStatus.LIMITADO
    return StockStatus.DISPONIBLE


def _normalize_fravega(raw: dict, categoria: str, tier: SourceTier) -> Offer:
    """
    Formato VTEX: producto -> items[] (SKUs) -> sellers[] -> commertialOffer.
    Tomamos el primer item/vendedor disponible - una tienda VTEX puede tener
    más de un vendedor marketplace por producto, pero para el MVP simplificamos
    al primero (documentado como limitación conocida).
    """
    item = (raw.get("items") or [{}])[0]
    seller = (item.get("sellers") or [{}])[0]
    oferta = seller.get("commertialOffer") or {}

    precio = Decimal(str(oferta.get("Price", 0)))

    financing = []
    for plan in oferta.get("Installments") or []:
        cuotas = plan.get("NumberOfInstallments")
        if not cuotas:
            continue
        monto_cuota = Decimal(str(plan["Value"])) if plan.get("Value") else None
        sin_interes = not plan.get("InterestRate") or float(plan["InterestRate"]) == 0
        financing.append(FinancingPlan(
            cuotas=cuotas, monto_cuota=monto_cuota,
            sin_interes_declarado=sin_interes, financing_verified=True,
        ))
        break  # solo el primer plan de cuotas, para no saturar la respuesta

    modelo = raw.get("productName", "Producto sin nombre")
    seller_label = seller.get("sellerName") or "Frávega"

    return Offer(
        offer_id=str(raw.get("productId", uuid4())),
        product=Product(
            product_id=str(raw.get("productId", uuid4())),
            marca=raw.get("brand", ""),
            modelo=modelo,
            categoria=categoria,
        ),
        seller=seller_label,
        price=precio,
        currency="ARS",
        stock_status=_map_stock_vtex(oferta),
        shipping_cost=None,  # VTEX no siempre trae costo de envío en la búsqueda
        shipping_eta_days=None,
        financing=financing,
        rating=None,
        rating_count=None,
        provenance=Provenance(
            source_name="fravega",
            source_tier=tier,
            source_timestamp=datetime.now(timezone.utc),
            verification_status=VerificationStatus.VERIFICADO,
            canonical_url=raw.get("link") or (
                f"https://www.fravega.com/p/{raw.get('linkText')}" if raw.get("linkText") else None
            ),
        ),
    )


_MAPPERS = {
    "fuente_a_mock": _normalize_source_a,
    "fuente_b_mock": _normalize_source_b,
    "mercadolibre": _normalize_mercadolibre,
    "fravega": _normalize_fravega,
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
