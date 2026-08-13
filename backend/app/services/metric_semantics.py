"""Configurable business semantics for normalized company metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Polarity = Literal["higher_better", "lower_better", "context_dependent", "unknown"]
BusinessDirection = Literal[
    "improved",
    "deteriorated",
    "stable",
    "context_dependent",
    "insufficient",
]


@dataclass(frozen=True)
class MetricSemantics:
    key: str
    label: str
    category: str
    polarity: Polarity


METRIC_SEMANTICS: dict[str, MetricSemantics] = {
    "revenue": MetricSemantics("revenue", "Revenue", "financial", "higher_better"),
    "ebitda": MetricSemantics("ebitda", "EBITDA", "financial", "higher_better"),
    "ebitda_margin": MetricSemantics("ebitda_margin", "EBITDA Margin", "financial", "higher_better"),
    "operating_profit": MetricSemantics("operating_profit", "Operating Profit", "financial", "higher_better"),
    "operating_margin": MetricSemantics("operating_margin", "Operating Margin", "financial", "higher_better"),
    "gross_profit": MetricSemantics("gross_profit", "Gross Profit", "financial", "higher_better"),
    "gross_margin": MetricSemantics("gross_margin", "Gross Margin", "financial", "higher_better"),
    "net_profit": MetricSemantics("net_profit", "Net Profit", "financial", "higher_better"),
    "net_margin": MetricSemantics("net_margin", "Net Margin", "financial", "higher_better"),
    "profit": MetricSemantics("profit", "Profit", "financial", "higher_better"),
    "market_share": MetricSemantics("market_share", "Market Share", "strategic", "higher_better"),
    "customer_count": MetricSemantics("customer_count", "Customer Count", "customer", "higher_better"),
    "cac": MetricSemantics("cac", "Cost per Acquisition", "customer_acquisition", "lower_better"),
    "ltv": MetricSemantics("ltv", "Lifetime Value", "customer", "higher_better"),
    "retention": MetricSemantics("retention", "Retention", "customer", "higher_better"),
    "nrr": MetricSemantics("nrr", "Net Revenue Retention", "customer", "higher_better"),
    "churn": MetricSemantics("churn", "Churn", "customer", "lower_better"),
    "dso": MetricSemantics("dso", "Days Sales Outstanding", "working_capital", "lower_better"),
    "capacity_utilization": MetricSemantics(
        "capacity_utilization", "Capacity Utilization", "operational", "context_dependent"
    ),
    "cost_to_serve": MetricSemantics("cost_to_serve", "Cost to Serve", "operational", "lower_better"),
    "free_cash_flow": MetricSemantics("free_cash_flow", "Free Cash Flow", "financial", "higher_better"),
    "cash": MetricSemantics("cash", "Cash", "financial", "higher_better"),
    "cash_flow": MetricSemantics("cash_flow", "Cash Flow", "financial", "higher_better"),
    "debt": MetricSemantics("debt", "Debt", "financial", "lower_better"),
    "marketing_spend": MetricSemantics("marketing_spend", "Marketing Spend", "financial", "context_dependent"),
    "cost": MetricSemantics("cost", "Cost", "financial", "lower_better"),
    "on_time_delivery": MetricSemantics("on_time_delivery", "On-Time Delivery", "operational", "higher_better"),
    "defect_rate": MetricSemantics("defect_rate", "Defect Rate", "operational", "lower_better"),
    "employee_attrition": MetricSemantics("employee_attrition", "Employee Attrition", "operational", "lower_better"),
    "nps": MetricSemantics("nps", "NPS", "customer", "higher_better"),
}


ROLE_METRIC_PRIORITIES: dict[str, tuple[str, ...]] = {
    "CFO": (
        "operating_margin",
        "gross_margin",
        "ebitda",
        "revenue",
        "profit",
        "cac",
        "dso",
        "free_cash_flow",
        "cash",
        "debt",
        "marketing_spend",
        "cost",
    ),
    "CMO": (
        "market_share",
        "cac",
        "customer_count",
        "ltv",
        "churn",
        "nrr",
        "retention",
        "marketing_spend",
    ),
    "COO": (
        "capacity_utilization",
        "cost_to_serve",
        "on_time_delivery",
        "defect_rate",
        "employee_attrition",
        "revenue",
    ),
    "CSO": (
        "market_share",
        "revenue",
        "customer_count",
        "cac",
        "ebitda",
        "gross_margin",
    ),
    "SYNTHESIS": (
        "revenue",
        "ebitda",
        "operating_margin",
        "gross_margin",
        "market_share",
        "cac",
        "ltv",
        "capacity_utilization",
    ),
}


def get_semantics(metric_key: str) -> MetricSemantics:
    return METRIC_SEMANTICS.get(
        metric_key,
        MetricSemantics(metric_key, metric_key.replace("_", " ").title(), "unknown", "unknown"),
    )


def compute_business_direction(metric_key: str, trend: str) -> BusinessDirection:
    if trend in {"insufficient", "stable"}:
        return trend  # type: ignore[return-value]

    semantics = get_semantics(metric_key)
    if semantics.polarity == "unknown":
        return "context_dependent"
    if semantics.polarity == "context_dependent":
        return "context_dependent"
    if semantics.polarity == "higher_better":
        return "improved" if trend == "increasing" else "deteriorated"
    if semantics.polarity == "lower_better":
        return "improved" if trend == "decreasing" else "deteriorated"
    return "context_dependent"


def normalized_metric_dict(metric: Any) -> dict[str, Any]:
    return {
        "metric": metric.label,
        "key": metric.key,
        "previous": metric.previous,
        "current": metric.current,
        "target": metric.target,
        "change_absolute": metric.change_abs,
        "change_percent": metric.change_pct,
        "direction": metric.trend,
        "business_direction": metric.business_direction,
        "category": metric.category,
        "unit": metric.unit,
    }
