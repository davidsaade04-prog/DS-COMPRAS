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
from intent_router import IntentRouter, RuleBasedIntentRouter
from task_planner import TaskPlanner
from policy_engine import PolicyEngine
from search_service import SearchService
from offer_normalizer import OfferNormalizer
from promotion_engine import PromotionEngine
from pricing_engine import PricingEngine
from ranking_engine import RankingEngine
from buy_wait_engine import BuyWaitEngine
from mock_adapters import MockSourceAAdapter, MockSourceBAdapter
from mock_promotions import MockPromotionCatalog
from search import SearchCriteria
from domain import PaymentContext, PriceResult
from decimal import Decimal, InvalidOperation


def _default_intent_router() -> IntentRouter:
    """Usa el LLM si hay ANTHROPIC_API_KEY configurada; si no (o si falla
    la inicialización), cae al router por reglas para no romper el sistema."""
    try:
        from llm_intent_router import LLMIntentRouter
        return LLMIntentRouter()
    except Exception:
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
    ):
        # Inyección de dependencias: permite testear cada pieza aislada y
        # reemplazar cualquier mock por una implementación real sin tocar
        # esta clase.
        self.intent_router = intent_router or _default_intent_router()
        self.task_planner = task_planner or TaskPlanner()
        self.policy_engine = policy_engine or PolicyEngine()
        self.search_service = search_service or SearchService(
            [MockSourceAAdapter(), MockSourceBAdapter()]
        )
        self.offer_normalizer = offer_normalizer or OfferNormalizer()
        self.promotion_engine = promotion_engine or PromotionEngine()
        self.pricing_engine = pricing_engine or PricingEngine()
        self.ranking_engine = ranking_engine or RankingEngine()
        self.buy_wait_engine = buy_wait_engine or BuyWaitEngine()
        # TODO(H6): reemplazar por Memory & Consent real. Hoy es un catálogo
        # fijo, igual que las fuentes mock de H3.
        self.promotion_catalog = promotion_catalog or MockPromotionCatalog()

    def run(self, request: OrchestratorRequest) -> OrchestrationResult:
        trace: list[TraceStep] = [TraceStep(step="message_received")]

        intent = self.intent_router.extract(request.message)
        trace.append(TraceStep(step="intent_classified", detail=intent.intent_type.value))

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

        # H6+ (Memory persistente real, Response Composer) todavía no está
        # implementado; esos TaskType siguen en el plan pero no se ejecutan.
        pending = [
            t for t in policy_decision.allowed_tasks
            if t not in {
                TaskType.SEARCH, TaskType.NORMALIZE, TaskType.ASK_CLARIFICATION,
                TaskType.EVALUATE_PROMOTIONS, TaskType.CALCULATE_PRICING,
                TaskType.RANK_OFFERS, TaskType.EVALUATE_BUY_WAIT,
            }
        ]
        if pending:
            trace.append(TraceStep(
                step="pending_not_implemented",
                detail=str([t.value for t in pending]),
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
        )

    @staticmethod
    def _build_search_criteria(entities: dict[str, str]) -> SearchCriteria:
        presupuesto = None
        if "presupuesto" in entities:
            try:
                presupuesto = Decimal(entities["presupuesto"])
            except InvalidOperation:
                presupuesto = None
        return SearchCriteria(
            categoria=entities.get("categoria", ""),
            presupuesto_max=presupuesto,
            urgencia=entities.get("urgencia"),
        )
