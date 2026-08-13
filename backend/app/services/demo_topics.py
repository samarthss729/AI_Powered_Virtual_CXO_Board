"""Lightweight topic detection for DEMO_MODE executive responses."""

from __future__ import annotations

import re
from typing import FrozenSet


Topic = str

# Topics a question may match (multiple allowed).
TOPIC_PATTERNS: dict[Topic, tuple[str, ...]] = {
    "financial_performance": (
        r"financial\s+performance",
        r"p\s*&\s*l",
        r"profit\s+and\s+loss",
        r"balance\s+sheet",
        r"financial\s+health",
        r"financial\s+results",
    ),
    "profitability": (
        r"profit",
        r"profitable",
        r"profitability",
        r"ebitda",
        r"net\s+income",
    ),
    "revenue": (
        r"revenue",
        r"sales",
        r"top[\s-]?line",
        r"turnover",
    ),
    "costs": (
        r"cost",
        r"expense",
        r"opex",
        r"operating\s+expense",
        r"cogs",
        r"spending",
        r"budget",
    ),
    "margins": (
        r"margin",
        r"gross\s+margin",
        r"operating\s+margin",
        r"profit\s+margin",
    ),
    "marketing": (
        r"marketing",
        r"campaign",
        r"advertis",
        r"brand\s+spend",
        r"paid\s+media",
    ),
    "customers": (
        r"customer",
        r"client",
        r"buyer",
        r"user\s+base",
    ),
    "acquisition": (
        r"acquisition",
        r"acquire",
        r"cac",
        r"customer\s+acquisition",
        r"pipeline",
        r"lead",
        r"conversion",
    ),
    "retention": (
        r"retention",
        r"churn",
        r"renewal",
        r"lifetime\s+value",
        r"ltv",
    ),
    "operations": (
        r"operation",
        r"operational",
        r"fulfillment",
        r"delivery",
        r"supply\s+chain",
        r"logistics",
    ),
    "efficiency": (
        r"efficien",
        r"productivity",
        r"throughput",
        r"waste",
        r"utilization",
    ),
    "capacity": (
        r"capacity",
        r"scale",
        r"scaling",
        r"headcount",
        r"hiring",
    ),
    "competition": (
        r"compet",
        r"rival",
        r"competitive",
        r"price\s+war",
        r"undercut",
    ),
    "market_share": (
        r"market\s+share",
        r"share\s+of\s+market",
        r"share\s+gain",
        r"share\s+loss",
    ),
    "strategy": (
        r"strateg",
        r"positioning",
        r"long[\s-]?term",
        r"optionality",
        r"differentiat",
    ),
    "expansion": (
        r"expand",
        r"expansion",
        r"enter\s+(?:the\s+)?\w+\s+market",
        r"new\s+market",
        r"international",
        r"geograph",
        r"european",
        r"europe",
        r"launch\s+in",
    ),
    "growth": (
        r"growth",
        r"grow",
        r"scale\s+up",
        r"accelerat",
    ),
    "csr": (
        r"\bcsr\b",
        r"corporate\s+social",
        r"sustainab",
        r"\besg\b",
        r"social\s+impact",
        r"environmental",
        r"carbon",
        r"climate",
        r"community\s+impact",
        r"responsible\s+business",
    ),
    "risk": (
        r"\brisk",
        r"exposure",
        r"uncertain",
        r"downside",
        r"threat",
    ),
    "investment": (
        r"invest",
        r"capital\s+alloc",
        r"capex",
        r"funding",
        r"allocate",
    ),
    "cash_flow": (
        r"cash\s+flow",
        r"liquidity",
        r"runway",
    ),
    "working_capital": (
        r"working[\s-]?capital",
        r"\bdso\b",
        r"days\s+sales\s+outstanding",
        r"receivable",
        r"payable",
        r"inventory\s+outstanding",
        r"cash\s+conversion",
        r"collection\s+cycle",
    ),
    "pricing": (
        r"pric",
        r"discount",
        r"undercut",
        r"price\s+cut",
    ),
    "margin_trend_query": (
        r"(?:increasing|decreasing|improving|worsening|going\s+up|going\s+down|trend)",
        r"(?:is|are)\s+(?:our|the)\s+(?:profit\s+)?margin",
        r"margin\s+(?:increasing|decreasing|trend)",
    ),
    "cost_reduction": (
        r"reduce\s+(?:operating\s+)?expense",
        r"cut\s+cost",
        r"cost[\s-]?cut",
        r"reduce\s+opex",
        r"reduce\s+spend",
        r"\d+\s*%\s*(?:cut|reduction)",
        r"downsize",
        r"layoff",
    ),
    "acquisition_slowdown": (
        r"acquisition\s+slow",
        r"slow(?:ing|ed)?\s+(?:down\s+)?(?:customer\s+)?acquisition",
        r"acquisition\s+declin",
        r"pipeline\s+slow",
        r"fewer\s+(?:new\s+)?customers",
        r"cac\s+(?:rising|increasing|up)",
    ),
}

# Higher priority categories drive the primary response template.
PRIMARY_CATEGORY_ORDER: tuple[str, ...] = (
    "csr",
    "competitive_pricing",
    "expansion",
    "margin_trend_query",
    "acquisition_slowdown",
    "cost_reduction",
    "market_share_growth",
    "margin_decline",
    "growth",
    "general",
)


def detect_topics(question: str) -> FrozenSet[Topic]:
    """Return all topics matched in the CEO question."""
    normalized = " ".join(question.lower().split())
    matched: set[Topic] = set()
    for topic, patterns in TOPIC_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                matched.add(topic)
                break
    return frozenset(matched)


def primary_category(question: str, topics: FrozenSet[Topic]) -> str:
    """Pick the dominant response template category for a question."""
    normalized = question.lower()

    if topics & {"csr"}:
        return "csr"

    if topics & {"competition", "pricing"} or re.search(
        r"competitor.*(?:price|pric|discount|cut)", normalized
    ):
        return "competitive_pricing"

    if topics & {"expansion"} or re.search(r"enter\s+(?:the\s+)?\w+\s+market", normalized):
        return "expansion"

    if topics & {"margin_trend_query"} or (
        topics & {"margins", "profitability"}
        and re.search(r"(increasing|decreasing|improving|worsening|trend|going\s+up|going\s+down)", normalized)
    ):
        return "margin_trend_query"

    if topics & {"acquisition_slowdown"} or (
        topics & {"acquisition"}
        and re.search(r"slow|declin|weak|fall|drop|stagn", normalized)
    ):
        return "acquisition_slowdown"

    if topics & {"cost_reduction"} or (
        topics & {"costs"}
        and re.search(r"reduce|cut|lower|decrease|\d+\s*%", normalized)
    ):
        return "cost_reduction"

    if topics & {"market_share"} and re.search(r"increase|grow|gain|expand|improve", normalized):
        return "market_share_growth"

    if topics & {"margins"} and re.search(r"drop|declin|fell|down|pressure|lost", normalized):
        return "margin_decline"

    if topics & {"growth", "expansion", "investment"}:
        return "growth"

    return "general"
