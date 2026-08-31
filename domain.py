"""
Modelos de dominio (contratos internos entre módulos).
Fuente: Especificación Técnica Maestra V2.1 - Sección 6 (Modelo de datos)
y Anexos A/B (contrato de oferta y de recomendación).

Regla de diseño: estos modelos son DATOS, no lógica.
Ningún cálculo financiero vive acá (eso es de Pricing/Promotion Engine).
"""

from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums de estado (ver Sección 9 - Source Reliability Layer; Sección 10.1)
# ---------------------------------------------------------------------------

class SourceTier(str, Enum):
    """Nivel de confiabilidad de la fuente. Sección 9."""
    A_OFICIAL = "A"          # fuente oficial del banco/comercio
    B_VERIFICADO = "B"       # comercio o proveedor verificado
    C_AGREGADOR = "C"        # agregador confiable
    D_SECUNDARIA = "D"       # fuente secundaria, solo referencia


class VerificationStatus(str, Enum):
    """Sección 8.2 Espec. Funcional V1.3"""
    VERIFICADO = "verificado"
    PARCIALMENTE_VERIFICADO = "parcialmente_verificado"
    NO_VERIFICABLE = "no_verificable"


class PromotionStatus(str, Enum):
    """Sección 10.1 V2.1 - Correcciones críticas."""
    CONFIRMADA = "confirmada"          # ✅
    NO_VERIFICADA = "no_verificada"    # ⚠️
    NO_APLICABLE = "no_aplicable"      # ❌
    VENCIDA = "vencida"


class StockStatus(str, Enum):
    DISPONIBLE = "disponible"
    LIMITADO = "limitado"
    SIN_STOCK = "sin_stock"
    NO_CONFIRMADO = "no_confirmado"


class BuyWaitRecommendation(str, Enum):
    COMPRAR = "comprar"
    ESPERAR = "esperar"
    NEUTRO = "neutro_sin_evidencia_suficiente"


# ---------------------------------------------------------------------------
# Procedencia (obligatoria en TODO dato comercial - Principio de arquitectura)
# ---------------------------------------------------------------------------

class Provenance(BaseModel):
    """Cada dato comercial debe conservar fuente, timestamp y verificación."""
    source_name: str
    source_tier: SourceTier
    source_timestamp: datetime
    verification_status: VerificationStatus
    canonical_url: Optional[str] = None


class PaymentContext(BaseModel):
    """
    Medio de pago autorizado del usuario, usado por el Promotion Engine.
    En H4 se pasa explícito en el request; en H6 vendrá de Memory & Consent
    real (con el mismo contrato, sin tocar el Promotion Engine).
    """
    banco: Optional[str] = None
    tarjeta: Optional[str] = None


# ---------------------------------------------------------------------------
# Producto / Oferta (Sección 6 modelo de datos + Anexo A)
# ---------------------------------------------------------------------------

class Product(BaseModel):
    product_id: str
    marca: str
    modelo: str
    categoria: str
    atributos: dict[str, str] = Field(default_factory=dict)


class FinancingPlan(BaseModel):
    cuotas: int
    monto_cuota: Optional[Decimal] = None
    tasa_nominal: Optional[Decimal] = None
    cft: Optional[Decimal] = None  # Costo Financiero Total (regla AR)
    sin_interes_declarado: bool = False
    # Si "sin_interes" no es matemáticamente consistente con el precio,
    # PricingEngine debe marcar financing_verified=False (Sección 10.1)
    financing_verified: bool = True
    condiciones: Optional[str] = None


class PromotionRule(BaseModel):
    """Regla estructurada. Sección 28 (V2.0.1) / Sección 10 (V2.1)."""
    promotion_id: str
    emisor_banco: Optional[str] = None
    medio_pago: Optional[str] = None       # ej: "Nativa Mastercard"
    comercio: Optional[str] = None
    categoria_o_producto: Optional[str] = None
    # Distinción obligatoria V1.3 §9.2 / adenda 10.4: un reintegro futuro NO
    # es lo mismo que un descuento inmediato. Default "reintegro" a propósito:
    # es la interpretación más conservadora (no reduce el desembolso inicial).
    tipo_beneficio: Literal["descuento_inmediato", "reintegro"] = "reintegro"
    vigencia_desde: Optional[datetime] = None
    vigencia_hasta: Optional[datetime] = None
    horarios: Optional[str] = None
    beneficio_pct: Optional[Decimal] = None
    beneficio_monto: Optional[Decimal] = None
    tope_reintegro: Optional[Decimal] = None
    compra_minima: Optional[Decimal] = None
    cuotas_aplicables: Optional[list[int]] = None
    acumulable: bool = False
    exclusiones: list[str] = Field(default_factory=list)
    provenance: Provenance


class Offer(BaseModel):
    """Contrato conceptual de oferta normalizada. Anexo A V2.0.1."""
    offer_id: str
    product: Product
    seller: str
    price: Decimal
    currency: str = "ARS"
    stock_status: StockStatus
    shipping_cost: Optional[Decimal] = None
    shipping_eta_days: Optional[int] = None
    financing: list[FinancingPlan] = Field(default_factory=list)
    promotions: list[PromotionRule] = Field(default_factory=list)
    warranty: Optional[str] = None
    rating: Optional[Decimal] = None
    rating_count: Optional[int] = None
    provenance: Provenance


# ---------------------------------------------------------------------------
# Resultados de cálculo (salida de Pricing/Promotion Engine - deterministas)
# ---------------------------------------------------------------------------

class PromotionEvalResult(BaseModel):
    promotion_id: str
    status: PromotionStatus
    beneficio_efectivo: Optional[Decimal] = None
    restricciones_incumplidas: list[str] = Field(default_factory=list)


class PriceResult(BaseModel):
    """Salida determinista del Pricing Engine. Nunca la calcula el LLM."""
    offer_id: str
    precio_publicado: Decimal
    descuento_inmediato: Decimal = Decimal("0")
    reintegro_esperado: Decimal = Decimal("0")
    tope_aplicado: Optional[Decimal] = None
    # None = no confirmado por la fuente (no se asume $0 - adenda 10.4.5).
    envio: Optional[Decimal] = None
    intereses: Decimal = Decimal("0")
    desembolso_inicial: Decimal
    costo_efectivo: Decimal
    costo_total_financiado: Optional[Decimal] = None
    promotions_aplicadas: list[PromotionEvalResult] = Field(default_factory=list)
    # Incertidumbre/decisiones tomadas por el motor que el usuario o el
    # Response Composer (H7) deben poder mostrar (V2.1 §19: no ocultar
    # nada que cambie materialmente la recomendación).
    warnings: list[str] = Field(default_factory=list)


class RankedOffer(BaseModel):
    """Anexo B V2.0.1: contrato conceptual de recomendación."""
    offer: Offer
    rank: int
    internal_score: Decimal
    key_factors: list[str]
    price_result: PriceResult
    verification_status: VerificationStatus
    label: Optional[str] = None  # "Mejor oferta", "Mejor precio", etc.
    optional_explanation: Optional[str] = None


class BuyWaitResult(BaseModel):
    recommendation: BuyWaitRecommendation
    confidence: Decimal  # 0.0 - 1.0
    reason: str
    review_condition: Optional[str] = None  # fecha/condición concreta (obligatorio si ESPERAR)
