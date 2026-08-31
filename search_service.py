"""
SearchService (H3). Fuente: Plan de Desarrollo M05 (SEA-02..SEA-05) +
V2.1 §9.2 (ejecutar fuentes en paralelo, timeout por fuente, conservar
resultados parciales).

Nota H3: la ejecución es secuencial (no async todavía) porque los mocks son
instantáneos. El contrato (SourceSearchOutcome por fuente) ya deja preparado
el cambio a asyncio.gather en H3+ real sin romper a quien consuma esto.
"""

from __future__ import annotations

from base import SearchAdapter
from search import SearchCriteria, SearchResult, SourceSearchOutcome


class SearchService:
    def __init__(self, adapters: list[SearchAdapter]):
        self._adapters = adapters

    def search(self, criteria: SearchCriteria) -> SearchResult:
        outcomes: list[SourceSearchOutcome] = []

        for adapter in self._adapters:
            try:
                raw_offers = adapter.search(criteria)
                outcomes.append(SourceSearchOutcome(
                    source_name=adapter.source_name,
                    source_tier=adapter.source_tier,
                    success=True,
                    raw_offers=raw_offers,
                ))
            except Exception as exc:  # noqa: BLE001 - a propósito: cualquier
                # falla de UNA fuente no debe frenar a las demás (V2.1 §2).
                outcomes.append(SourceSearchOutcome(
                    source_name=adapter.source_name,
                    source_tier=adapter.source_tier,
                    success=False,
                    error=str(exc),
                ))

        return SearchResult(criteria=criteria, outcomes=outcomes)
