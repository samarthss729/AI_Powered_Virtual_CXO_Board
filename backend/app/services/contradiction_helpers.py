"""Lightweight detection of material metric contradictions for board decisions."""

from __future__ import annotations

from app.services.data_service import CompanyDataProfile, MetricSnapshot, QuestionAnalysis


FINANCIAL_CONTRADICTION_KEYS: tuple[str, ...] = (
    "ebitda",
    "free_cash_flow",
    "gross_margin",
    "profit",
    "net_profit",
    "debt",
    "marketing_spend",
    "cost",
)

FINANCIAL_CONTRADICTION_PRIORITY: dict[str, int] = {
    "ebitda": 0,
    "free_cash_flow": 1,
    "profit": 2,
    "net_profit": 3,
    "gross_margin": 4,
    "debt": 5,
    "marketing_spend": 6,
    "cost": 7,
}


def is_financial_decision_question(question: str, topics: frozenset[str] | None = None) -> bool:
    """True when the CEO question involves profitability, growth, investment, or financial performance."""
    q = question.lower()
    if topics and topics & {
        "profitability",
        "growth",
        "investment",
        "financial",
        "margins",
        "revenue",
        "costs",
        "cash_flow",
        "marketing",
        "acquisition",
    }:
        return True
    return any(
        token in q
        for token in (
            "profitability",
            "profit",
            "growth",
            "invest",
            "financial",
            "margin",
            "revenue",
            "accelerate",
            "consolidat",
            "market share",
            "customer count",
            "cac",
            "unit economics",
            "spend",
            "roi",
            "ebitda",
            "earnings",
        )
    )


def is_growth_scale_decision(question: str, topics: frozenset[str] | None = None) -> bool:
    """True when operational capacity may materially constrain a growth/scale decision."""
    q = question.lower()
    if any(
        phrase in q
        for phrase in (
            "accelerate growth",
            "consolidating profitability",
            "growth next period",
            "scale",
            "capacity",
            "throughput",
        )
    ):
        return True
    if topics and topics & {"growth", "capacity", "operations"}:
        return True
    return "growth" in q and any(token in q for token in ("profit", "margin", "invest", "accelerate"))


def _metric_evidence_line(metric: MetricSnapshot) -> str | None:
    return metric.business_compare_sentence() or metric.compare_sentence()


def _has_positive_financial_story(analysis: QuestionAnalysis) -> bool:
    if not analysis.primary_metrics:
        return analysis.assessment == "improving"
    improved_primaries = [m for m in analysis.primary_metrics if m.business_direction == "improved"]
    if len(improved_primaries) >= 2:
        return True
    financial_improved = any(
        m.key in {"revenue", "operating_margin", "gross_margin", "profit", "market_share", "customer_count", "cac"}
        and m.business_direction == "improved"
        for m in analysis.primary_metrics
    )
    return financial_improved or analysis.assessment == "improving"


def _improved_primary_keys(analysis: QuestionAnalysis) -> set[str]:
    return {m.key for m in analysis.primary_metrics if m.business_direction == "improved"}


def _is_material_financial_contradiction(
    metric: MetricSnapshot,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
) -> bool:
    improved = _improved_primary_keys(analysis)
    if metric.key == "ebitda":
        if "ebitda" in {m.lower() for m in analysis.missing_metrics}:
            return False
        rev = profile.get("revenue")
        op = profile.get("operating_margin")
        return (
            "revenue" in improved
            or "operating_margin" in improved
            or (rev and rev.business_direction == "improved")
            or (op and op.business_direction == "improved")
            or len(improved) >= 2
        )
    if metric.key == "free_cash_flow":
        return bool(
            improved & {"revenue", "operating_margin", "ebitda"}
            or (profile.get("revenue") and profile.get("revenue").business_direction == "improved")
        )
    if metric.key == "gross_margin":
        op = profile.get("operating_margin")
        return bool(op and op.business_direction == "improved")
    if metric.key in {"profit", "net_profit"}:
        return "revenue" in improved or (
            profile.get("revenue") and profile.get("revenue").business_direction == "improved"
        )
    if metric.key == "debt":
        return bool(improved & {"revenue", "operating_margin", "ebitda", "free_cash_flow"})
    if metric.key in {"marketing_spend", "cost"}:
        return bool(improved & {"operating_margin", "revenue"})
    return False


def detect_cfo_financial_contradictions(
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    question: str,
) -> list[MetricSnapshot]:
    """Financial metrics that materially contradict an otherwise positive decision story."""
    if not profile.has_upload or not is_financial_decision_question(question, analysis.topics):
        return []
    if not _has_positive_financial_story(analysis):
        return []

    primary_keys = {m.key for m in analysis.primary_metrics}
    contradictions: list[MetricSnapshot] = []

    for key in FINANCIAL_CONTRADICTION_KEYS:
        if key in primary_keys:
            continue
        metric = profile.get(key)
        if not metric or not metric.available or metric.business_direction != "deteriorated":
            continue
        if not _is_material_financial_contradiction(metric, profile, analysis):
            continue
        contradictions.append(metric)

    contradictions.sort(key=lambda m: FINANCIAL_CONTRADICTION_PRIORITY.get(m.key, 99))
    return contradictions[:2]


def detect_coo_operational_constraints(
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    question: str,
) -> list[MetricSnapshot]:
    """Operational metrics that materially constrain growth/scale decisions."""
    if not profile.has_upload or not is_growth_scale_decision(question, analysis.topics):
        return []

    cap = profile.get("capacity_utilization")
    if not cap or not cap.available:
        return []

    high_level = cap.current is not None and cap.current >= 80
    sharp_increase = (
        cap.previous is not None
        and cap.current is not None
        and cap.current - cap.previous >= 5
        and cap.current >= 75
    )
    if high_level or sharp_increase:
        return [cap]
    return []


def format_contradictory_evidence(
    metrics: list[MetricSnapshot],
    *,
    label: str = "Contradictory financial evidence",
) -> str:
    lines = [_metric_evidence_line(m) for m in metrics]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return f"{label}: {'; '.join(lines)}."


def format_operational_constraint_evidence(metrics: list[MetricSnapshot]) -> str:
    return format_contradictory_evidence(metrics, label="Operational constraint evidence")


def cfo_contradiction_interpretation(
    contradictions: list[MetricSnapshot],
    analysis: QuestionAnalysis,
) -> str:
    if not contradictions:
        return ""
    improved_labels = [m.label for m in analysis.primary_metrics if m.business_direction == "improved"][:3]
    improved_text = ", ".join(improved_labels) if improved_labels else "headline growth and margin metrics"
    lead = contradictions[0]
    if lead.key == "ebitda":
        return (
            f"Interpretation: {improved_text} improved, but {lead.label} declined from "
            f"{lead.format_value(lead.previous)} to {lead.format_value(lead.current)}, "
            "so an EBITDA bridge should be understood before aggressive expansion."
        )
    lead_line = _metric_evidence_line(lead) or lead.label
    return (
        f"Interpretation: {improved_text} improved, but {lead_line}, "
        "which warrants validating the earnings bridge before accelerating spend."
    )


def coo_constraint_interpretation(constraints: list[MetricSnapshot]) -> str:
    if not constraints:
        return ""
    cap = constraints[0]
    if cap.current is not None and cap.current >= 85:
        return (
            f"Interpretation: Capacity utilization at {cap.format_value(cap.current)} is approaching "
            "a constraint; additional demand should be gated on throughput validation."
        )
    line = _metric_evidence_line(cap) or cap.label
    return (
        f"Interpretation: {line} signals tightening operational headroom, so growth plans must "
        "confirm service capacity before scaling demand."
    )


def board_contradiction_note(
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    question: str,
) -> str:
    """Short synthesis clause when contradictions/constraints should gate the board decision."""
    financial = detect_cfo_financial_contradictions(profile, analysis, question)
    operational = detect_coo_operational_constraints(profile, analysis, question)
    parts: list[str] = []
    if financial:
        lead = financial[0]
        if lead.key == "ebitda":
            parts.append(
                f"Aggressive expansion should be gated on understanding the {lead.label} decline "
                f"({lead.format_value(lead.previous)} to {lead.format_value(lead.current)}) and "
                "confirming incremental growth remains profitable."
            )
        else:
            parts.append(
                f"The board should reconcile the positive headline metrics with deteriorating {lead.label} "
                "before committing to aggressive expansion."
            )
    if operational:
        cap = operational[0]
        if cap.current is not None:
            parts.append(
                f"Operational supportability should be confirmed at "
                f"{cap.format_value(cap.current)} capacity utilization before scaling demand."
            )
    return " ".join(parts)
