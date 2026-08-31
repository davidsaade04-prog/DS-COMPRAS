"""
Catálogo mock de promociones (H4, conexión al Orquestador).
Incluye a propósito: una promoción bien confirmable, una "de campaña" sin
comercio especificado (debe dar NO_VERIFICADA - adenda 10.4.4), y una vencida
(debe excluirse - V1.3 §16).
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
            comercio="Fuente A (mock)",
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
            comercio="Fuente A (mock)",
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
