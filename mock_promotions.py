"""
Catálogo mock de promociones bancarias (H4). Sigue siendo simulado porque
los bancos argentinos no publican una API pública de promociones vigentes -
a diferencia de los productos (H con MercadoLibre real), esto no tiene una
fuente real gratuita disponible.

Cambio importante al conectar MercadoLibre real (búsqueda de productos):
antes estas reglas apuntaban a un "comercio" inventado ("Fuente A mock") que
coincidía a propósito con nuestra fuente simulada, dando promociones
"confirmadas". Con vendedores REALES de MercadoLibre, no tenemos forma de
verificar qué comercios participan realmente de una promoción bancaria -
por eso ahora comercio=None en todas: quedan como NO_VERIFICADA en vez de
CONFIRMADA (adenda 10.4.4: "campaña ≠ producto/comercio específico"). Es
menos vistoso para una demo, pero es lo correcto: no inventamos una
verificación que no tenemos.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from domain import PromotionRule, Provenance, SourceTier, VerificationStatus

_PROV_MOCK = Provenance(
    source_name="promos_bna_mock",
    source_tier=SourceTier.A_OFICIAL,
    source_timestamp=datetime.now(timezone.utc),
    verification_status=VerificationStatus.VERIFICADO,
)

_RULES_BY_CATEGORIA: dict[str, list[PromotionRule]] = {
    "aire acondicionado": [
        PromotionRule(
            promotion_id="bna-nativa-electro-20",
            emisor_banco="Banco Nacion",
            medio_pago="Nativa",
            comercio=None,  # honesto: no podemos verificar comercios reales participantes
            categoria_o_producto="aire acondicionado",
            tipo_beneficio="reintegro",
            beneficio_pct=Decimal("20"),
            tope_reintegro=Decimal("100000"),
            acumulable=False,
            provenance=_PROV_MOCK,
        ),
        PromotionRule(
            promotion_id="campana-generica-fin-de-semana",
            emisor_banco="Banco Nacion",
            medio_pago="Nativa",
            comercio=None,  # a propósito: campaña general, no producto-específica
            categoria_o_producto=None,
            tipo_beneficio="reintegro",
            beneficio_pct=Decimal("10"),
            acumulable=True,
            provenance=_PROV_MOCK,
        ),
    ],
    "celular": [
        PromotionRule(
            promotion_id="bna-nativa-celulares-vencida",
            emisor_banco="Banco Nacion",
            medio_pago="Nativa",
            comercio=None,
            categoria_o_producto="celular",
            tipo_beneficio="descuento_inmediato",
            beneficio_pct=Decimal("15"),
            vigencia_hasta=datetime.now(timezone.utc) - timedelta(days=5),
            acumulable=False,
            provenance=_PROV_MOCK,
        ),
    ],
}


class MockPromotionCatalog:
    def get_rules_for(self, categoria: str) -> list[PromotionRule]:
        return _RULES_BY_CATEGORIA.get(categoria, [])
