"""
Adaptadores mock (H3). Simulan 2 fuentes con formatos DISTINTOS a propósito
(igual que el ejemplo del Plan de Desarrollo M06: Fuente A vs Fuente B) para
que el Offer Normalizer tenga que hacer trabajo real de unificación, y no
sea un pasamanos disfrazado.

MockSourceB además simula una falla intermitente para poder probar el
manejo de errores (V2.1 §19: "Timeout externo → reintento limitado + fuente
alternativa; conservar resultados parciales").
"""

from __future__ import annotations
from datetime import datetime, timezone

from base import SearchAdapter
from domain import SourceTier
from search import SearchCriteria


class SourceUnavailableError(Exception):
    pass


# Catálogo mock. Cubre el "caso maestro de demo" (V2.1 §28: aire acondicionado
# 3000 frigorías) y el "Anexo A" (celular hasta $1.600.000 con Nativa).
_CATALOG_SOURCE_A = {
    "aire acondicionado": [
        {
            "nombre_producto": "Split Frío/Calor 3000 frigorías Samsung",
            "precio_ars": 850000,
            "cuotas_cantidad": 12,
            "cuotas_sin_interes": True,
            "stock": "en_stock",
            "envio_dias": 3,
            "rating": 4.6,
            "cantidad_opiniones": 320,
            "url": "https://fuente-a.example.com/aire-samsung-3000",
        },
    ],
    "celular": [
        {
            "nombre_producto": "Samsung Galaxy A55",
            "precio_ars": 1450000,
            "cuotas_cantidad": 18,
            "cuotas_sin_interes": True,
            "stock": "en_stock",
            "envio_dias": 2,
            "rating": 4.7,
            "cantidad_opiniones": 890,
            "url": "https://fuente-a.example.com/galaxy-a55",
        },
    ],
}

# Fuente B: mismos productos pero con NOMBRES DE CAMPO distintos, precio con
# formato distinto, y sin algunos datos (rating no disponible acá).
_CATALOG_SOURCE_B = {
    "aire acondicionado": [
        {
            "titulo": "Aire Acondicionado 3000 Frig. Split F/C - Samsung",
            "price": {"amount": 869900, "currency": "ARS"},
            "installments": {"count": 12, "interest_free": True},
            "availability": "available",
            "shipping": {"eta_business_days": 5, "cost": 0},
            "link": "https://fuente-b.example.com/aire-samsung",
        },
    ],
    "celular": [
        {
            "titulo": "Samsung Galaxy A55 5G 256GB",
            "price": {"amount": 1420000, "currency": "ARS"},
            "installments": {"count": 12, "interest_free": True},
            "availability": "available",
            "shipping": {"eta_business_days": 2, "cost": 0},
            "link": "https://fuente-b.example.com/galaxy-a55",
        },
    ],
}


class MockSourceAAdapter(SearchAdapter):
    source_name = "fuente_a_mock"
    source_tier = SourceTier.B_VERIFICADO

    def search(self, criteria: SearchCriteria) -> list[dict]:
        return _CATALOG_SOURCE_A.get(criteria.categoria, [])


class MockSourceBAdapter(SearchAdapter):
    source_name = "fuente_b_mock"
    source_tier = SourceTier.C_AGREGADOR

    def __init__(self, fail_categories: set[str] | None = None):
        # Permite forzar una falla en pruebas (ej. simular timeout en
        # "heladera" para validar que la búsqueda sigue con fuente_a).
        self._fail_categories = fail_categories or set()

    def search(self, criteria: SearchCriteria) -> list[dict]:
        if criteria.categoria in self._fail_categories:
            raise SourceUnavailableError(
                f"Timeout simulado en {self.source_name} para '{criteria.categoria}'"
            )
        return _CATALOG_SOURCE_B.get(criteria.categoria, [])
