"""
Orquestador Central (H2).
Fuente: V2.1 §4 - Ciclo: interpretar → ... → seleccionar herramientas.

En H2 el ciclo llega hasta "seleccionar herramientas" (task_plan +
policy_decision). Ejecutar las herramientas (Search, Pricing, Ranking...)
se conecta en H3-H6 sin tener que tocar este archivo (Result Merger y
Response Composer se agregan como pasos nuevos del ciclo, no reemplazan
lo que ya existe).
"""

from __future__ import annotations

from domain import Offer
from orchestration import (
    OrchestratorRequest,
    OrchestrationResult,
    TraceStep,
    TaskType,
)
from intent_router import IntentRouter, RuleBasedIntentRouter, CRITICAL_FIELDS_BY_INTENT
from task_planner import TaskPlanner
from policy_engine import PolicyEngine
from search_service import SearchService
from offer_normalizer import OfferNormalizer
from promotion_engine import PromotionEngine
from pricing_engine import PricingEngine
from ranking_engine import RankingEngine
from buy_wait_engine import BuyWaitEngine
from mercadolibre_adapter import MercadoLibreAdapter
from fravega_adapter import FravegaAdapter
from tienda_bna_adapter import TiendaBNAAdapter
from serpapi_adapter import SerpApiShoppingAdapter
from mock_promotions import MockPromotionCatalog
from search import SearchCriteria
from domain import PaymentContext, PriceResult
from orchestration import ExtractedIntent, IntentType, TaskPlan, PolicyDecision
from memory_store import MemoryStore, get_memory_store
from decimal import Decimal, InvalidOperation

# Respuestas cortas para resolver una confirmación pendiente (H6). Se
# interpretan de forma DETERMINISTA a propósito - una decisión de privacidad
# o borrado no la interpreta el LLM (mismo principio que V2.1 §10.3 aplica
# acá: nada crítico queda librado a que el modelo "entienda bien").
_AFIRMATIVO = {"si", "sí", "dale", "confirmo", "ok", "okay", "de acuerdo", "acepto", "aceptar", "claro", "obvio"}
_NEGATIVO = {"no", "cancelar", "cancelo", "mejor no", "paso", "nel"}


def _primera_palabra(text: str) -> str:
    limpio = text.strip().lower().split(" ")[0]
    return limpio.strip(".,!?¡¿")


def _default_intent_router() -> IntentRouter:
    """Usa el LLM si hay ANTHROPIC_API_KEY configurada; si no (o si falla
    la inicialización), cae al router por reglas para no romper el sistema."""
    try:
        from llm_intent_router import LLMIntentRouter
        return LLMIntentRouter()
    except Exception as exc:
        # Bug de diagnóstico H2: antes esto fallaba en silencio y no había
        # forma de saber por qué el LLM no se activaba. Lo dejamos impreso
        # (aparece en Render > Logs) para poder diagnosticarlo.
        print(f"[intent_router] LLMIntentRouter no disponible, usando reglas. Motivo: {exc!r}", flush=True)
        return RuleBasedIntentRouter()


class Orchestrator:
    def __init__(
        self,
        intent_router: IntentRouter | None = None,
        task_planner: TaskPlanner | None = None,
        policy_engine: PolicyEngine | None = None,
        search_service: SearchService | None = None,
        offer_normalizer: OfferNormalizer | None = None,
        promotion_engine: PromotionEngine | None = None,
        pricing_engine: PricingEngine | None = None,
        ranking_engine: RankingEngine | None = None,
        buy_wait_engine: BuyWaitEngine | None = None,
        promotion_catalog: MockPromotionCatalog | None = None,
        memory_store: MemoryStore | None = None,
    ):
        # Inyección de dependencias: permite testear cada pieza aislada y
        # reemplazar cualquier mock por una implementación real sin tocar
        # esta clase.
        self.intent_router = intent_router or _default_intent_router()
        self.task_planner = task_planner or TaskPlanner()
        self.policy_engine = policy_engine or PolicyEngine()
        self.search_service = search_service or SearchService(
            [MercadoLibreAdapter(), FravegaAdapter(), TiendaBNAAdapter(), SerpApiShoppingAdapter()]
        )
        self.offer_normalizer = offer_normalizer or OfferNormalizer()
        self.promotion_engine = promotion_engine or PromotionEngine()
        self.pricing_engine = pricing_engine or PricingEngine()
        self.ranking_engine = ranking_engine or RankingEngine()
        self.buy_wait_engine = buy_wait_engine or BuyWaitEngine()
        # TODO(H8+): reemplazar por catálogo de promociones real. Hoy es un
        # catálogo fijo, igual que las fuentes mock de H3.
        self.promotion_catalog = promotion_catalog or MockPromotionCatalog()
        self.memory_store = memory_store or get_memory_store()

    def run(self, request: OrchestratorRequest) -> OrchestrationResult:
        trace: list[TraceStep] = [TraceStep(
            step="message_received",
            detail=f"router={type(self.intent_router).__name__}",
        )]

        # --- H6: resolver una confirmación pendiente ANTES que nada más
        # (consentimiento de guardar banco/tarjeta, o confirmación de
        # borrado). Se interpreta con reglas fijas, no con el LLM: una
        # decisión de privacidad no debe depender de que el modelo
        # "entienda bien" la respuesta.
        pending = self.memory_store.get_pending_action(request.session_id)
        if pending:
            return self._resolver_pendiente(request, pending, trace)

        intent = self.intent_router.extract(request.message)
        trace.append(TraceStep(step="intent_classified", detail=intent.intent_type.value))

        # --- H6: los 3 intents de memoria se resuelven acá directo, sin
        # pasar por Task Planner/Policy/Search - no tiene sentido "buscar
        # ofertas" para "olvidá mis datos bancarios".
        if intent.intent_type == IntentType.BORRAR_MEMORIA:
            self.memory_store.set_pending_action(request.session_id, {"type": "confirmar_borrado"})
            return self._resultado_directo(
                intent, trace,
                "Esto va a borrar tu banco y tarjeta guardados, de forma permanente. "
                "¿Confirmás? (respondé sí o no)",
            )

        if intent.intent_type == IntentType.GESTIONAR_MEMORIA_BANCARIA:
            banco = intent.entities.get("banco")
            tarjeta = intent.entities.get("tarjeta")
            if not banco and not tarjeta:
                return self._resultado_directo(intent, trace, "¿Qué banco o tarjeta querés que recuerde?")
            self.memory_store.set_pending_action(
                request.session_id, {"type": "consentir_banco", "banco": banco, "tarjeta": tarjeta}
            )
            desc = " y ".join(x for x in [banco, tarjeta] if x)
            return self._resultado_directo(
                intent, trace,
                f"¿Querés que recuerde {desc} para futuras búsquedas? (respondé sí o no)",
            )

        if intent.intent_type == IntentType.CONSULTAR_MEMORIA:
            guardado = self.memory_store.get_payment_context(request.user_id)
            if guardado and (guardado.banco or guardado.tarjeta):
                detalle = " y ".join(x for x in [guardado.banco, guardado.tarjeta] if x)
                msg = f"Tengo guardado: {detalle}."
            else:
                msg = "No tengo ningún dato bancario guardado tuyo."
            return self._resultado_directo(intent, trace, msg)

        # --- H7: explicación bajo demanda (V1.3 §15.4). Usa lo que se
        # guardó en memory_store la última vez que se armó un ranking en
        # ESTA sesión - no vuelve a calcular nada, solo repite el motivo.
        if intent.intent_type == IntentType.EXPLICAR_RECOMENDACION:
            ultima = self.memory_store.get_last_recommendation(request.session_id)
            if not ultima:
                msg = "Todavía no te recomendé nada en esta conversación."
            else:
                partes = []
                for item in ultima:
                    factores = ", ".join(item.get("key_factors") or []) or "sin motivos particulares registrados"
                    etiqueta = f" ({item['label']})" if item.get("label") else ""
                    partes.append(f"#{item['rank']} {item['modelo']}{etiqueta}: {factores}")
                msg = "Por qué recomendé cada opción:\n" + "\n".join(partes)
            return self._resultado_directo(intent, trace, msg)

        # --- Alertas (H9) todavía no están implementadas. Antes esto caía
        # en el flujo general de búsqueda (que no incluye SEARCH para esta
        # intención) y terminaba mostrando "no encontré ofertas" - un
        # mensaje falso y confuso, como si hubiera buscado y fallado,
        # cuando en realidad ni siquiera lo intentó. Mejor ser honestos.
        if intent.intent_type == IntentType.CREAR_ALERTA:
            return self._resultado_directo(
                intent, trace,
                "Todavía no puedo crear alertas de precio (esa función está "
                "planificada para más adelante). Por ahora podés volver a "
                "preguntarme cuando quieras revisar precios de nuevo.",
            )

        # --- H6/H7: continuidad de conversación. Lo dicho en ESTE mensaje
        # siempre pisa lo guardado; lo guardado solo rellena lo que falta.
        # Bug real detectado en pruebas: guardar banco/tarjeta en la memoria
        # de SESIÓN (igual que categoría) hacía que una simple pregunta
        # hipotética ("¿tienen promo con Galicia?") "pisara" para siempre
        # el banco realmente guardado (Banco Nación) en toda la conversación
        # siguiente, sin que el usuario lo haya pedido. Separación correcta:
        #   - memoria de SESIÓN (categoría, urgencia, presupuesto): continúa
        #     de mensaje a mensaje, no requiere consentimiento (V2.1 §7.1).
        #   - banco/tarjeta: SOLO se usan de la sesión si vienen en ESTE
        #     mismo mensaje (uso puntual); para continuidad entre mensajes
        #     se usa exclusivamente lo persistido con consentimiento
        #     explícito - nunca lo que quedó de un mensaje anterior.
        session_entities = self.memory_store.get_session_entities(request.session_id)
        session_entities.pop("banco", None)
        session_entities.pop("tarjeta", None)
        merged_entities = {**session_entities, **intent.entities}

        guardado = self.memory_store.get_payment_context(request.user_id)
        if guardado:
            if "banco" not in merged_entities and guardado.banco:
                merged_entities["banco"] = guardado.banco
            if "tarjeta" not in merged_entities and guardado.tarjeta:
                merged_entities["tarjeta"] = guardado.tarjeta

        intent.entities = merged_entities
        # Se persiste para la sesión SIN banco/tarjeta (ver comentario de
        # arriba) - esos dos campos nunca deben "pegarse" de un mensaje al
        # siguiente, solo vienen de esta consulta puntual o de lo persistido.
        entidades_a_guardar = {k: v for k, v in merged_entities.items() if k not in ("banco", "tarjeta")}
        self.memory_store.save_session_entities(request.session_id, entidades_a_guardar)

        # Bug real detectado en pruebas H6/H7: "¿algo más económico?" o "no
        # tengo apuro, compro igual?" traían la categoría bien heredada de
        # la sesión, pero el Task Planner seguía preguntando "¿qué producto
        # buscás?" - por dos motivos distintos que hay que cubrir juntos:
        # (a) el intent podía haber quedado "desconocida" sin categoría
        #     propia todavía, y (b) aunque ya fuera "buscar_producto",
        #     missing_critical_fields se calculó ANTES del merge de sesión,
        #     con la categoría todavía ausente. Se corrige de una sola vez,
        #     recalculando sobre las entidades ya fusionadas.
        if intent.intent_type == IntentType.DESCONOCIDA and merged_entities.get("categoria"):
            intent.intent_type = IntentType.BUSCAR_PRODUCTO
        intent.missing_critical_fields = [
            f for f in CRITICAL_FIELDS_BY_INTENT.get(intent.intent_type, [])
            if f not in merged_entities
        ]

        plan = self.task_planner.plan(intent)
        trace.append(TraceStep(step="task_plan_created", detail=str([t.value for t in plan.tasks])))

        policy_decision = self.policy_engine.evaluate(request, plan)
        trace.append(TraceStep(
            step="policy_evaluated",
            detail=f"allowed={len(policy_decision.allowed_tasks)} blocked={len(policy_decision.blocked_tasks)}",
        ))

        offers: list[Offer] = []
        if TaskType.SEARCH in policy_decision.allowed_tasks:
            criteria = self._build_search_criteria(intent.entities)
            search_result = self.search_service.search(criteria)
            failed = [o.source_name for o in search_result.outcomes if not o.success]
            trace.append(TraceStep(
                step="search_executed",
                detail=f"raw_offers={search_result.total_raw_offers} fuentes_caidas={failed}",
            ))

            if TaskType.NORMALIZE in policy_decision.allowed_tasks:
                offers = self.offer_normalizer.normalize(search_result)
                trace.append(TraceStep(step="offers_normalized", detail=f"count={len(offers)}"))

        price_results: list[PriceResult] = []
        rules_by_id_per_offer: dict[str, dict] = {}
        if offers and TaskType.EVALUATE_PROMOTIONS in policy_decision.allowed_tasks:
            payment_context = PaymentContext(
                banco=intent.entities.get("banco"),
                tarjeta=intent.entities.get("tarjeta"),
            )
            for offer in offers:
                rules = self.promotion_catalog.get_rules_for(offer.product.categoria)
                rules_by_id = {r.promotion_id: r for r in rules}
                rules_by_id_per_offer[offer.offer_id] = rules_by_id
                promo_results = self.promotion_engine.evaluate(offer, payment_context, rules)

                price_result = None
                if TaskType.CALCULATE_PRICING in policy_decision.allowed_tasks:
                    selected_financing = offer.financing[0] if offer.financing else None
                    price_result = self.pricing_engine.calculate(
                        offer, promo_results, rules_by_id, selected_financing=selected_financing
                    )
                price_results.append(price_result)

            trace.append(TraceStep(
                step="promotions_and_pricing_executed",
                detail=f"payment_context=banco:{payment_context.banco},tarjeta:{payment_context.tarjeta}",
            ))

        ranked_offers = []
        buy_wait_result = None
        valid_pairs = [
            (o, pr) for o, pr in zip(offers, price_results) if pr is not None
        ]
        if valid_pairs and TaskType.RANK_OFFERS in policy_decision.allowed_tasks:
            valid_offers = [o for o, _ in valid_pairs]
            valid_prices = [pr for _, pr in valid_pairs]
            ranked_offers = self.ranking_engine.rank(valid_offers, valid_prices)
            trace.append(TraceStep(step="offers_ranked", detail=f"count={len(ranked_offers)}"))

            # H7: guardar el motivo de esta recomendación por si preguntan
            # "¿por qué esa opción?" más adelante en la misma conversación.
            self.memory_store.save_last_recommendation(request.session_id, [
                {"rank": r.rank, "modelo": r.offer.product.modelo, "label": r.label, "key_factors": r.key_factors}
                for r in ranked_offers
            ])

            if ranked_offers and TaskType.EVALUATE_BUY_WAIT in policy_decision.allowed_tasks:
                top = ranked_offers[0]
                buy_wait_result = self.buy_wait_engine.evaluate(
                    top,
                    urgencia=intent.entities.get("urgencia"),
                    promotion_rules_by_id=rules_by_id_per_offer.get(top.offer.offer_id),
                )
                trace.append(TraceStep(
                    step="buy_wait_evaluated",
                    detail=buy_wait_result.recommendation.value,
                ))

        # H8+ (Mejora Continua, Alertas) todavía no está implementado; esos
        # TaskType siguen en el plan pero no se ejecutan.
        tareas_pendientes = [
            t for t in policy_decision.allowed_tasks
            if t not in {
                TaskType.SEARCH, TaskType.NORMALIZE, TaskType.ASK_CLARIFICATION,
                TaskType.EVALUATE_PROMOTIONS, TaskType.CALCULATE_PRICING,
                TaskType.RANK_OFFERS, TaskType.EVALUATE_BUY_WAIT,
            }
        ]
        if tareas_pendientes:
            trace.append(TraceStep(
                step="pending_not_implemented",
                detail=str([t.value for t in tareas_pendientes]),
            ))

        return OrchestrationResult(
            intent=intent,
            task_plan=plan,
            policy_decision=policy_decision,
            trace=trace,
            offers_found=offers,
            price_results=[pr for pr in price_results if pr is not None],
            ranked_offers=ranked_offers,
            buy_wait_result=buy_wait_result,
            intent_router_name=type(self.intent_router).__name__,
            memory_store_name=type(self.memory_store).__name__,
        )

    @staticmethod
    def _build_search_criteria(entities: dict[str, str]) -> SearchCriteria:
        presupuesto = None
        if "presupuesto" in entities:
            try:
                presupuesto = Decimal(entities["presupuesto"])
            except InvalidOperation:
                presupuesto = None
        categoria = entities.get("categoria", "")
        # Bug real detectado en pruebas: buscar solo por categoria genérica
        # ("celular", "televisor") ignoraba pedidos específicos como
        # "Motorola Edge 70 Pro" o "smart tv de 75 pulgadas" y devolvía
        # siempre lo mismo. Si el usuario dio un detalle más preciso, ESE
        # es el texto que se manda a las fuentes reales.
        query = entities.get("producto_especifico") or categoria
        return SearchCriteria(
            categoria=categoria,
            query=query,
            presupuesto_max=presupuesto,
            urgencia=entities.get("urgencia"),
        )

    def _resultado_directo(self, intent: ExtractedIntent, trace: list[TraceStep], mensaje: str) -> OrchestrationResult:
        """H6: construye una respuesta corta para flujos de memoria, sin
        pasar por Search/Ranking (no aplica en esos casos)."""
        return OrchestrationResult(
            intent=intent,
            task_plan=TaskPlan(tasks=[]),
            policy_decision=PolicyDecision(allowed_tasks=[]),
            trace=trace,
            intent_router_name=type(self.intent_router).__name__,
            memory_store_name=type(self.memory_store).__name__,
            direct_message=mensaje,
        )

    def _resolver_pendiente(
        self, request: OrchestratorRequest, pending: dict, trace: list[TraceStep]
    ) -> OrchestrationResult:
        """H6: interpreta sí/no para una confirmación pendiente (borrado o
        consentimiento bancario). Determinista a propósito - ver comentario
        en run()."""
        palabra = _primera_palabra(request.message)
        confirmado = palabra in _AFIRMATIVO
        negado = palabra in _NEGATIVO
        intent_vacio = ExtractedIntent(intent_type=IntentType.DESCONOCIDA, entities={})

        if pending.get("type") == "confirmar_borrado":
            if confirmado:
                self.memory_store.set_pending_action(request.session_id, None)
                self.memory_store.delete_all_payment_data(request.user_id)
                # Limpiar también banco/tarjeta si habían quedado en la
                # memoria de sesión de esta conversación.
                session_entities = self.memory_store.get_session_entities(request.session_id)
                session_entities.pop("banco", None)
                session_entities.pop("tarjeta", None)
                self.memory_store.save_session_entities(request.session_id, session_entities)
                msg = "Listo, borré todos tus datos bancarios guardados."
            elif negado:
                self.memory_store.set_pending_action(request.session_id, None)
                msg = "No borré nada, seguimos como estábamos."
            else:
                # Ni sí ni no: no asumimos nada tan sensible, volvemos a preguntar.
                msg = "No entendí. ¿Confirmás el borrado de tus datos bancarios? (sí/no)"
            return self._resultado_directo(intent_vacio, trace, msg)

        if pending.get("type") == "consentir_banco":
            if confirmado:
                self.memory_store.set_pending_action(request.session_id, None)
                self.memory_store.save_payment_context(
                    request.user_id, pending.get("banco"), pending.get("tarjeta")
                )
                msg = "Listo, lo guardé para futuras búsquedas."
            elif negado:
                self.memory_store.set_pending_action(request.session_id, None)
                msg = "Sin problema, no lo guardo - lo uso solo para esta conversación."
            else:
                msg = "No entendí. ¿Guardo ese banco/tarjeta para la próxima? (sí/no)"
            return self._resultado_directo(intent_vacio, trace, msg)

        # Tipo de pendiente desconocido (no debería pasar) - limpiar y seguir.
        self.memory_store.set_pending_action(request.session_id, None)
        return self._resultado_directo(intent_vacio, trace, "Listo.")
