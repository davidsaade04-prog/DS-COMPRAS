"""
Contratos de Search & Connectors (H3).
Fuente: Plan de Desarrollo M05 (SEA-01: SearchRequest/SearchResponse) +
        V2.1 §9 (Búsqueda y fuentes).
"""

from __future__ import annotations
from decimal import Decimal
from pydantic import BaseModel

from domain import Offer, SourceTier


class SearchCriteria(BaseModel):
    """Construido por el Orquestador a partir de ExtractedIntent.entities."""
    categoria: str
    presupuesto_max: Decimal | None = None
    urgencia: str | None = None


class SourceSearchOutcome(BaseModel):
    """
    Resultado de UNA fuente. Un timeout/error acá NO debe tirar abajo toda
    la búsqueda (V2.1 §2: "Los fallos parciales no deben derribar toda la
    búsqueda").
    """
    source_name: str
    source_tier: SourceTier
    success: bool
    raw_offers: list[dict] = []
    error: str | None = None


class SearchResult(BaseModel):
    """Salida consolidada de SearchService.search(), antes de normalizar."""
    criteria: SearchCriteria
    outcomes: list[SourceSearchOutcome]

    @property
    def has_any_success(self) -> bool:
        return any(o.success for o in self.outcomes)

    @property
    def total_raw_offers(self) -> int:
        return sum(len(o.raw_offers) for o in self.outcomes if o.success)
