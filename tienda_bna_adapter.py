"""
Adaptador EXPERIMENTAL a Tienda BNA (marketplace del Banco Nación), vía la
API pública de búsqueda de VTEX. Mismo patrón que FravegaAdapter.

Nivel de confianza MÁS BAJO que Frávega: para Frávega encontramos evidencia
directa (un playground de API pública en fravega.com/api/v1) de que corre
sobre VTEX. Para Tienda BNA NO se pudo confirmar esto - es una apuesta
razonable (muchos marketplaces argentinos usan VTEX) pero no verificada.
Si el endpoint no responde o cambia de formato, esta fuente simplemente
falla y el resto de la búsqueda sigue funcionando igual (V2.1 §2).

Por qué vale la pena intentarlo igual: si funciona, es la única fuente que
nos permitiría cruzar promociones de Banco Nación con productos y
comercios REALES (hoy esa promoción vive como "no verificada" justamente
porque no hay forma de confirmar qué comercios participan).
"""

from __future__ import annotations
import httpx

from base import SearchAdapter
from domain import SourceTier
from search import SearchCriteria

_BASE_URL = "https://www.tiendabna.com.ar/api/catalog_system/pub/products/search"


class TiendaBNAAdapter(SearchAdapter):
    source_name = "tienda_bna"
    source_tier = SourceTier.A_OFICIAL  # si funciona, es la fuente oficial del banco

    def __init__(self, limit: int = 5, timeout: float = 8.0):
        self._limit = limit
        self._timeout = timeout

    def search(self, criteria: SearchCriteria) -> list[dict]:
        url = f"{_BASE_URL}/{criteria.query or criteria.categoria}"
        params = {"_from": 0, "_to": max(self._limit - 1, 0)}
        response = httpx.get(url, params=params, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
