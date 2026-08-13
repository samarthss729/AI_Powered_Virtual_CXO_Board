"""Company data normalization, metric analysis, and question-aware reasoning."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.demo_topics import detect_topics
from app.services.metric_semantics import (
    ROLE_METRIC_PRIORITIES,
    compute_business_direction,
    get_semantics,
    normalized_metric_dict,
)


PERIOD_HINTS = ("quarter", "period", "month", "year", "date", "fiscal", "week", "q")
CURRENT_HINTS = ("current", "latest", "actual", "now")
PREVIOUS_HINTS = ("previous", "prior", "last", "prior_period")
TARGET_HINTS = ("target", "goal", "budget", "plan")

METRIC_HINTS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "turnover", "top_line", "topline"),
    "ebitda": ("ebitda",),
    "gross_margin": ("gross_margin", "gross margin", "grossmargin"),
    "operating_margin": ("operating_margin", "operating margin", "op_margin"),
    "free_cash_flow": ("free_cash_flow", "free cash flow", "fcf"),
    "cash": ("cash", "cash_balance"),
    "debt": ("debt", "total_debt"),
    "marketing_spend": ("marketing_spend", "marketing spend", "marketing"),
    "market_share": ("market_share", "market share"),
    "cac": ("cac", "customer_acquisition_cost", "acquisition_cost"),
    "ltv": ("ltv", "lifetime_value", "lifetime value", "clv"),
    "churn": ("churn",),
    "nrr": ("nrr", "net_revenue_retention", "net revenue retention"),
    "customer_count": ("customer_count", "customers", "customer growth", "customer count"),
    "capacity_utilization": ("capacity_utilization", "capacity utilization", "utilization"),
    "on_time_delivery": ("on_time_delivery", "on-time delivery", "otd"),
    "defect_rate": ("defect_rate", "defect rate", "defects"),
    "employee_attrition": ("employee_attrition", "attrition", "turnover_rate"),
    "nps": ("nps", "net_promoter"),
    "profit": ("profit", "net_income", "net income", "operating_income"),
    "cost": ("cost", "expense", "opex", "cogs", "spend"),
    "dso": ("dso", "days_sales_outstanding", "days sales outstanding"),
    "cost_to_serve": ("cost_to_serve", "cost to serve"),
    "retention": ("retention", "retention_rate"),
}

METRIC_CATEGORY: dict[str, str] = {
    "revenue": "financial",
    "ebitda": "financial",
    "gross_margin": "financial",
    "operating_margin": "financial",
    "free_cash_flow": "financial",
    "cash": "financial",
    "debt": "financial",
    "profit": "financial",
    "cost": "financial",
    "marketing_spend": "financial",
    "cac": "customer",
    "ltv": "customer",
    "churn": "customer",
    "nrr": "customer",
    "customer_count": "customer",
    "market_share": "strategic",
    "capacity_utilization": "operational",
    "on_time_delivery": "operational",
    "defect_rate": "operational",
    "employee_attrition": "operational",
    "nps": "customer",
    "dso": "working_capital",
    "cost_to_serve": "operational",
    "retention": "customer",
}

ROLE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "CFO": ("financial",),
    "CMO": ("customer", "strategic"),
    "COO": ("operational", "financial"),
    "CSO": ("strategic", "customer", "financial"),
    "SYNTHESIS": ("financial", "customer", "operational", "strategic"),
}


@dataclass
class MetricSnapshot:
    """One normalized metric with optional current/previous/target and series."""

    key: str
    label: str
    category: str
    unit: str
    current: float | None = None
    previous: float | None = None
    target: float | None = None
    current_label: str | None = None
    previous_label: str | None = None
    change_abs: float | None = None
    change_pct: float | None = None
    target_variance: float | None = None
    trend: str = "insufficient"
    business_direction: str = "insufficient"
    series: list[tuple[str, float]] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.current is not None or len(self.series) >= 2

    def format_value(self, value: float | None) -> str:
        if value is None:
            return "n/a"
        if self.unit == "percent":
            return f"{value:.1f}%"
        if self.unit == "currency":
            return _format_currency(value)
        if self.unit == "ratio":
            return f"{value:.2f}"
        return f"{value:,.2f}"

    def compare_sentence(self) -> str | None:
        if self.current is None:
            return None
        if self.previous is not None and self.change_pct is not None:
            direction = self.trend if self.trend != "insufficient" else _direction(self.previous, self.current)
            prev_label = self.previous_label or "previous period"
            cur_label = self.current_label or "current period"
            return (
                f"{self.label} {direction} from {self.format_value(self.previous)} ({prev_label}) "
                f"to {self.format_value(self.current)} ({cur_label}), "
                f"a {self.change_pct:+.1f}% change"
            )
        if len(self.series) >= 2:
            first_label, first_val = self.series[0]
            last_label, last_val = self.series[-1]
            direction = self.trend
            return (
                f"{self.label} {direction} from {self.format_value(first_val)} ({first_label}) "
                f"to {self.format_value(last_val)} ({last_label})"
            )
        return f"{self.label} is {self.format_value(self.current)}"

    def business_compare_sentence(self) -> str | None:
        """Human-readable sentence using business_direction semantics."""
        if self.current is None or self.previous is None:
            return self.compare_sentence()

        prev = self.format_value(self.previous)
        cur = self.format_value(self.current)
        if self.business_direction == "improved":
            return f"{self.label} improved from {prev} to {cur}"
        if self.business_direction == "deteriorated":
            return f"{self.label} deteriorated from {prev} to {cur}"
        if self.business_direction == "stable":
            return f"{self.label} held steady at {cur}"
        if self.business_direction == "context_dependent":
            return (
                f"{self.label} moved from {prev} to {cur} "
                f"({self.trend}); interpret in operational/strategic context"
            )
        return self.compare_sentence()


@dataclass
class CompanyDataProfile:
    filename: str = ""
    has_upload: bool = False
    layout: str = "none"
    fields: list[str] = field(default_factory=list)
    metrics: dict[str, MetricSnapshot] = field(default_factory=dict)

    def get(self, *keys: str) -> MetricSnapshot | None:
        for key in keys:
            if key in self.metrics:
                return self.metrics[key]
            for metric_key, metric in self.metrics.items():
                if key.replace("_", " ") in metric_key.replace("_", " "):
                    return metric
        return None

    def available_metric_names(self) -> list[str]:
        return [m.label for m in self.metrics.values() if m.available]

    def metrics_for_role(self, role: str, *, include_all: bool = True) -> list[MetricSnapshot]:
        return select_persona_metrics(self, role, question="", include_extras=include_all)

    def has_metric(self, *keys: str) -> bool:
        metric = self.get(*keys)
        return metric is not None and metric.available

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "layout": self.layout,
            "fields": self.fields,
            "metrics": {
                key: {
                    "current": metric.current,
                    "previous": metric.previous,
                    "target": metric.target,
                    "trend": metric.trend,
                    "business_direction": metric.business_direction,
                    "unit": metric.unit,
                }
                for key, metric in self.metrics.items()
                if metric.available
            },
        }


@dataclass
class QuestionAnalysis:
    question: str
    topics: frozenset[str]
    relevant_metrics: list[MetricSnapshot] = field(default_factory=list)
    primary_metrics: list[MetricSnapshot] = field(default_factory=list)
    secondary_metrics: list[MetricSnapshot] = field(default_factory=list)
    improving: list[MetricSnapshot] = field(default_factory=list)
    deteriorating: list[MetricSnapshot] = field(default_factory=list)
    stable: list[MetricSnapshot] = field(default_factory=list)
    assessment: str = "insufficient"
    evidence_lines: list[str] = field(default_factory=list)
    missing_metrics: list[str] = field(default_factory=list)
    drivers: list[str] = field(default_factory=list)


@dataclass
class MetricSelection:
    """Primary = explicitly named in question; secondary = topic-inferred decision context."""

    primary: list[MetricSnapshot] = field(default_factory=list)
    secondary: list[MetricSnapshot] = field(default_factory=list)

    @property
    def merged(self) -> list[MetricSnapshot]:
        seen: set[str] = set()
        ordered: list[MetricSnapshot] = []
        for metric in self.primary + self.secondary:
            if metric.key not in seen:
                ordered.append(metric)
                seen.add(metric.key)
        return ordered


def build_company_profile(
    normalized: dict[str, Any] | None,
    *,
    filename: str = "",
) -> CompanyDataProfile:
    if not normalized:
        return CompanyDataProfile(filename=filename, has_upload=False, layout="none")

    records = normalized.get("records") or []
    fields = [str(f) for f in normalized.get("fields") or []]
    profile = CompanyDataProfile(
        filename=filename or str(normalized.get("filename") or ""),
        has_upload=True,
        fields=fields,
    )

    if _is_current_previous_target_layout(records, fields):
        profile.layout = "current_previous_target"
        _build_cpt_metrics(profile, records)
    elif records and all(isinstance(row, dict) for row in records):
        profile.layout = "timeseries"
        _build_timeseries_metrics(profile, records)
    else:
        profile.layout = "snapshot"
        _build_snapshot_metrics(profile, normalized)

    return profile


def analyze_question(profile: CompanyDataProfile, question: str) -> QuestionAnalysis:
    topics = detect_topics(question)
    analysis = QuestionAnalysis(question=question, topics=topics)
    if not profile.has_upload:
        analysis.assessment = "no_upload"
        return analysis

    selection = _select_relevant_metrics(profile, question, topics)
    analysis.primary_metrics = selection.primary
    analysis.secondary_metrics = selection.secondary
    analysis.relevant_metrics = selection.merged
    # Do not fall back to unrelated metrics — keep the set question-specific.
    if not analysis.relevant_metrics:
        analysis.assessment = "insufficient"
        analysis.missing_metrics = _missing_for_question(question, topics, profile)
        return analysis

    for metric in analysis.relevant_metrics:
        if metric.business_direction == "improved":
            analysis.improving.append(metric)
        elif metric.business_direction == "deteriorated":
            analysis.deteriorating.append(metric)
        elif metric.business_direction == "stable":
            analysis.stable.append(metric)
        sentence = metric.business_compare_sentence() or metric.compare_sentence()
        if sentence:
            analysis.evidence_lines.append(sentence)

    pos, neg = _classify_metric_direction(analysis.relevant_metrics)
    if pos and neg:
        analysis.assessment = "mixed"
    elif pos and not neg:
        analysis.assessment = "improving"
    elif neg and not pos:
        analysis.assessment = "deteriorating"
    elif analysis.stable:
        analysis.assessment = "stable"
    else:
        analysis.assessment = "insufficient"

    # Mixed financial picture when top-line and earnings trends diverge.
    rev = profile.get("revenue")
    ebitda = profile.get("ebitda")
    q_lower = question.lower()
    if (
        rev
        and ebitda
        and rev.available
        and ebitda.available
        and rev.trend not in {"insufficient", "stable"}
        and ebitda.trend not in {"insufficient", "stable"}
        and rev.trend != ebitda.trend
        and any(token in q_lower for token in ("financial performance", "overall", "doing better", "business"))
    ):
        analysis.assessment = "mixed"

    analysis.drivers = _infer_drivers(profile, question, topics, analysis)
    analysis.missing_metrics = _missing_for_question(question, topics, profile)
    return analysis


def build_agent_data_summary(profile: CompanyDataProfile, role: str, analysis: QuestionAnalysis) -> str:
    if not profile.has_upload:
        return "No company data uploaded for this session."

    lines = [f"Uploaded file: {profile.filename}", f"Detected layout: {profile.layout}"]
    primary, secondary = select_persona_metric_groups(
        profile,
        role,
        analysis.question,
        analysis.primary_metrics,
        analysis.secondary_metrics,
        analysis.relevant_metrics,
    )

    def _append_metric_block(header: str, metrics: list[MetricSnapshot]) -> None:
        if not metrics:
            return
        lines.append(header)
        for metric in metrics:
            sentence = metric.business_compare_sentence() or metric.compare_sentence()
            if sentence:
                lines.append(f"- {sentence}")
            elif metric.current is not None:
                lines.append(f"- {metric.label}: {metric.format_value(metric.current)}")

    _append_metric_block(f"{role} — primary question metrics:", primary)
    _append_metric_block(f"{role} — secondary decision metrics:", secondary)

    from app.services.contradiction_helpers import (
        detect_cfo_financial_contradictions,
        detect_coo_operational_constraints,
        format_contradictory_evidence,
        format_operational_constraint_evidence,
    )

    if role == "CFO":
        contradictions = detect_cfo_financial_contradictions(profile, analysis, analysis.question)
        contradiction_text = format_contradictory_evidence(contradictions)
        if contradiction_text:
            lines.append(contradiction_text)
    if role == "COO":
        constraints = detect_coo_operational_constraints(profile, analysis, analysis.question)
        constraint_text = format_operational_constraint_evidence(constraints)
        if constraint_text:
            lines.append(constraint_text)

    if analysis.missing_metrics:
        lines.append("Unavailable metrics for this question: " + ", ".join(analysis.missing_metrics))
    return "\n".join(lines)


def select_persona_metrics(
    profile: CompanyDataProfile,
    role: str,
    question: str,
    question_relevant: list[MetricSnapshot] | None = None,
    *,
    primary_metrics: list[MetricSnapshot] | None = None,
    secondary_metrics: list[MetricSnapshot] | None = None,
    include_extras: bool = False,
    limit: int = 6,
) -> list[MetricSnapshot]:
    """Role-relevant subset from primary question metrics, then secondary decision metrics."""
    primary, secondary = select_persona_metric_groups(
        profile,
        role,
        question,
        primary_metrics,
        secondary_metrics,
        question_relevant,
        limit=limit,
    )
    return primary + secondary


def select_persona_metric_groups(
    profile: CompanyDataProfile,
    role: str,
    question: str,
    primary_metrics: list[MetricSnapshot] | None = None,
    secondary_metrics: list[MetricSnapshot] | None = None,
    question_relevant: list[MetricSnapshot] | None = None,
    *,
    limit: int = 6,
) -> tuple[list[MetricSnapshot], list[MetricSnapshot]]:
    """Split persona metrics into primary (question-named) and secondary (decision context)."""
    if primary_metrics is None and secondary_metrics is None:
        selection = _select_relevant_metrics(profile, question, detect_topics(question))
        primary = selection.primary
        secondary = selection.secondary
    else:
        primary = list(primary_metrics or [])
        secondary = list(secondary_metrics or [])
        if not primary and not secondary and question_relevant:
            primary = list(question_relevant)

    role_order = ROLE_METRIC_PRIORITIES.get(role, ())

    def _order_by_role(candidates: list[MetricSnapshot]) -> list[MetricSnapshot]:
        """Keep only persona-priority metrics from the candidate list."""
        ordered: list[MetricSnapshot] = []
        seen: set[str] = set()
        for key in role_order:
            for metric in candidates:
                if metric.key == key and metric.key not in seen:
                    ordered.append(metric)
                    seen.add(metric.key)
        return ordered

    role_primary = _order_by_role(primary)
    primary_keys = {m.key for m in primary}
    persona_support = _collect_metrics(
        profile,
        _persona_supporting_metric_keys(role, question, primary_keys),
    )
    persona_support = [m for m in persona_support if m.key not in primary_keys]
    combined_secondary = list(secondary) + [m for m in persona_support if m.key not in {s.key for s in secondary}]
    role_secondary = _order_by_role(combined_secondary)

    # Prefer primary metrics; fill remaining slots with role-relevant secondary.
    primary_limit = min(len(role_primary), limit)
    chosen_primary = role_primary[:primary_limit]
    remaining = max(0, limit - len(chosen_primary))
    chosen_secondary = role_secondary[:remaining]
    return chosen_primary, chosen_secondary


def build_question_scoped_context_block(
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
) -> str:
    """Structured data block containing ONLY metrics relevant to the current question."""
    import json

    relevant_keys = {m.key for m in analysis.relevant_metrics}
    primary_keys = {m.key for m in analysis.primary_metrics}
    payload = {
        "filename": profile.filename,
        "layout": profile.layout,
        "current_question": analysis.question,
        "primary_metrics": {
            key: normalized_metric_dict(metric)
            for key, metric in profile.metrics.items()
            if metric.available and key in primary_keys
        },
        "secondary_metrics": {
            key: normalized_metric_dict(metric)
            for key, metric in profile.metrics.items()
            if metric.available and key in relevant_keys and key not in primary_keys
        },
        "metrics": {
            key: normalized_metric_dict(metric)
            for key, metric in profile.metrics.items()
            if metric.available and key in relevant_keys
        },
    }
    if analysis.missing_metrics:
        payload["unavailable_for_question"] = analysis.missing_metrics
    return json.dumps(payload, indent=2, default=str)


def build_structured_context_block(profile: CompanyDataProfile) -> str:
    """Compact JSON-friendly block embedded in LLM prompts."""
    import json

    payload = {
        "filename": profile.filename,
        "layout": profile.layout,
        "fields": profile.fields,
        "metrics": {
            key: normalized_metric_dict(metric)
            for key, metric in profile.metrics.items()
            if metric.available
        },
    }
    return json.dumps(payload, indent=2, default=str)


def profile_from_structured_payload(payload: dict[str, Any]) -> CompanyDataProfile:
    """Rebuild a profile from the structured prompt block (fallback parsing)."""
    profile = CompanyDataProfile(
        filename=str(payload.get("filename") or ""),
        has_upload=bool(payload.get("metrics")),
        layout=str(payload.get("layout") or "structured"),
        fields=[str(f) for f in payload.get("fields") or []],
    )
    for key, raw in (payload.get("metrics") or {}).items():
        if not isinstance(raw, dict):
            continue
        series_raw = raw.get("series") or []
        series: list[tuple[str, float]] = []
        for item in series_raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                series.append((str(item[0]), float(item[1])))
        profile.metrics[str(key)] = MetricSnapshot(
            key=str(key),
            label=str(raw.get("label") or raw.get("metric") or key),
            category=str(raw.get("category") or "financial"),
            unit=str(raw.get("unit") or "count"),
            current=_to_float(raw.get("current")),
            previous=_to_float(raw.get("previous")),
            target=_to_float(raw.get("target")),
            trend=str(raw.get("direction") or raw.get("trend") or "insufficient"),
            business_direction=str(raw.get("business_direction") or "insufficient"),
            change_pct=_to_float(raw.get("change_percent") or raw.get("change_pct")),
            series=series,
        )
    return profile


def _is_current_previous_target_layout(records: list[Any], fields: list[str]) -> bool:
    normalized_fields = {f.lower().replace(" ", "_") for f in fields}
    if {"current", "previous"} <= normalized_fields or {"current", "target"} <= normalized_fields:
        return True
    if not records:
        return False
    first = records[0]
    if not isinstance(first, dict):
        return False
    keys = {str(k).lower().replace(" ", "_") for k in first.keys()}
    return bool(keys & set(CURRENT_HINTS)) and bool(keys & (set(PREVIOUS_HINTS) | set(TARGET_HINTS)))


def _build_cpt_metrics(profile: CompanyDataProfile, records: list[dict[str, Any]]) -> None:
    metric_col = _find_metric_name_column(records[0])
    for row in records:
        metric_name = str(row.get(metric_col, "")).strip() if metric_col else ""
        if not metric_name:
            continue
        canonical = _canonical_metric_key(metric_name)
        current = _pick_value(row, CURRENT_HINTS)
        previous = _pick_value(row, PREVIOUS_HINTS)
        target = _pick_value(row, TARGET_HINTS)
        unit = _infer_unit(metric_name, current if current is not None else previous)
        snapshot = MetricSnapshot(
            key=canonical,
            label=metric_name,
            category=METRIC_CATEGORY.get(canonical, "financial"),
            unit=unit,
            current=current,
            previous=previous,
            target=target,
            current_label="Current",
            previous_label="Previous",
        )
        if current is not None and previous is not None:
            snapshot.change_abs = round(current - previous, 4)
            if previous != 0:
                snapshot.change_pct = round((current - previous) / abs(previous) * 100, 2)
            snapshot.trend = _direction(previous, current)
        if current is not None and target is not None and target != 0:
            snapshot.target_variance = round((current - target) / abs(target) * 100, 2)
        _finalize_metric(snapshot)
        profile.metrics[canonical] = snapshot


def _build_timeseries_metrics(profile: CompanyDataProfile, records: list[dict[str, Any]]) -> None:
    period_key = _find_period_key(records[0])
    ordered = _sort_records(records, period_key)
    numeric_keys = [
        key
        for key in ordered[0].keys()
        if _to_float(ordered[0].get(key)) is not None and key != period_key
    ]
    for field_key in numeric_keys:
        canonical = _canonical_metric_key(str(field_key))
        series: list[tuple[str, float]] = []
        for row in ordered:
            value = _to_float(row.get(field_key))
            if value is None:
                continue
            unit = _infer_unit(str(field_key), value)
            if unit == "percent" and 0 < value <= 1:
                value = round(value * 100, 2)
            label = str(row.get(period_key, "period")) if period_key else "period"
            series.append((label, value))
        if not series:
            continue
        current = series[-1][1]
        previous = series[-2][1] if len(series) >= 2 else None
        snapshot = MetricSnapshot(
            key=canonical,
            label=str(field_key).replace("_", " "),
            category=METRIC_CATEGORY.get(canonical, _guess_category(str(field_key))),
            unit=_infer_unit(str(field_key), current),
            current=current,
            previous=previous,
            current_label=series[-1][0],
            previous_label=series[-2][0] if len(series) >= 2 else None,
            series=series,
        )
        if previous is not None:
            snapshot.change_abs = round(current - previous, 4)
            if previous != 0:
                snapshot.change_pct = round((current - previous) / abs(previous) * 100, 2)
            snapshot.trend = _direction(previous, current)
        elif len(series) >= 2:
            snapshot.trend = _direction(series[0][1], series[-1][1])
        _finalize_metric(snapshot)
        profile.metrics[canonical] = snapshot


def _build_snapshot_metrics(profile: CompanyDataProfile, normalized: dict[str, Any]) -> None:
    summary = normalized.get("summary_stats") or {}
    for field_key, stats in summary.items():
        if not isinstance(stats, dict):
            continue
        latest = _to_float(stats.get("latest"))
        if latest is None:
            continue
        canonical = _canonical_metric_key(str(field_key))
        profile.metrics[canonical] = MetricSnapshot(
            key=canonical,
            label=str(field_key).replace("_", " "),
            category=METRIC_CATEGORY.get(canonical, _guess_category(str(field_key))),
            unit=_infer_unit(str(field_key), latest),
            current=latest,
            current_label="latest",
            trend="insufficient",
        )
        _finalize_metric(profile.metrics[canonical])


def _select_relevant_metrics(
    profile: CompanyDataProfile,
    question: str,
    topics: frozenset[str],
) -> MetricSelection:
    q = question.lower()
    explicit_keys, explicit_order = _detect_explicit_metrics_in_question(question)
    primary = _collect_metrics(profile, explicit_keys, order=explicit_order)

    # Multi-metric explicit questions: all named metrics are primary; skip unrelated topic injection.
    if len(primary) >= 2:
        return MetricSelection(primary=primary, secondary=[])

    secondary_wanted = _topic_inferred_metric_keys(question, topics, explicit_keys)
    secondary = _collect_metrics(profile, secondary_wanted)

    if primary:
        secondary = [m for m in secondary if m.key not in {p.key for p in primary}]
        return MetricSelection(primary=primary, secondary=secondary)

    # Working-capital-only questions without other explicit metrics.
    if topics & {"working_capital"} or _is_working_capital_question(q):
        wc_keys = {"dso", "cash", "free_cash_flow", "debt"}
        if "revenue" in q:
            wc_keys.add("revenue")
        wc_primary = _collect_metrics(profile, wc_keys)
        if wc_primary:
            return MetricSelection(primary=wc_primary, secondary=[])

    # Topic-only selection (no explicit metric names in question).
    topic_primary = _collect_metrics(profile, secondary_wanted)
    return MetricSelection(primary=topic_primary, secondary=[])


def _is_working_capital_question(q: str) -> bool:
    return any(
        token in q
        for token in (
            "working capital",
            "working-capital",
            "dso",
            "days sales outstanding",
            "receivable",
            "cash conversion",
            "collection cycle",
        )
    )


def _detect_explicit_metrics_in_question(question: str) -> tuple[set[str], list[str]]:
    """Detect every metric name/alias explicitly mentioned in the CEO question."""
    q_norm = " ".join(question.lower().replace("-", " ").replace("_", " ").split())
    found: set[str] = set()
    ordered: list[str] = []

    # Longest aliases first so "operating margin" wins over substring overlaps.
    alias_pairs: list[tuple[int, str, str]] = []
    for canonical, hints in METRIC_HINTS.items():
        for hint in hints:
            hint_norm = " ".join(hint.lower().replace("-", " ").replace("_", " ").split())
            alias_pairs.append((len(hint_norm), canonical, hint_norm))
    alias_pairs.sort(key=lambda item: item[0], reverse=True)

    for _length, canonical, hint_norm in alias_pairs:
        if canonical in found:
            continue
        # Word/phrase boundary match.
        pattern = r"(?<!\w)" + re.escape(hint_norm).replace(r"\ ", r"\s+") + r"(?!\w)"
        if re.search(pattern, q_norm):
            found.add(canonical)
            ordered.append(canonical)

    return found, ordered


def _persona_supporting_metric_keys(
    role: str,
    question: str,
    primary_keys: set[str],
) -> set[str]:
    """Role-specific secondary metrics for decision context — never replaces explicit primaries."""
    q = question.lower()
    keys: set[str] = set()
    growth_decision = any(
        phrase in q
        for phrase in (
            "accelerate growth",
            "consolidating profitability",
            "growth next period",
            "growth or",
            "prioritize growth",
            "profitability improvement",
        )
    )
    if role == "COO" and growth_decision and "capacity_utilization" not in primary_keys:
        keys.add("capacity_utilization")
    if (
        role == "CFO"
        and "gross_margin" not in primary_keys
        and primary_keys & {"operating_margin", "revenue"}
        and any(token in q for token in ("margin", "profitability", "profit"))
    ):
        keys.add("gross_margin")
    if role in {"CMO", "CSO"} and "ltv" not in primary_keys and "cac" in primary_keys:
        keys.add("ltv")
    return keys


def _topic_inferred_metric_keys(
    question: str,
    topics: frozenset[str],
    explicit_keys: set[str],
) -> set[str]:
    """Topic-based metric keys used as secondary context (never replaces explicit primaries)."""
    q = question.lower()
    wanted: set[str] = set()

    topic_metric_map = {
        "revenue": ("revenue",),
        "profitability": ("ebitda", "profit", "gross_margin", "operating_margin"),
        "margins": ("gross_margin", "operating_margin", "profit"),
        "costs": ("cost", "marketing_spend"),
        "cash_flow": ("free_cash_flow", "cash"),
        "marketing": ("marketing_spend", "cac", "ltv"),
        "acquisition": ("cac", "customer_count", "ltv"),
        "retention": ("churn", "nrr", "ltv"),
        "customers": ("customer_count", "churn", "nrr", "cac", "ltv"),
        "market_share": ("market_share",),
        "competition": ("market_share",),
        "operations": ("capacity_utilization", "on_time_delivery", "defect_rate"),
        "efficiency": ("capacity_utilization", "defect_rate", "dso"),
        "capacity": ("capacity_utilization",),
        "growth": ("revenue", "market_share", "customer_count", "cac"),
        "risk": ("churn", "debt", "cash"),
        "investment": ("marketing_spend", "cac", "ltv", "market_share"),
        "working_capital": ("dso", "cash", "free_cash_flow", "debt"),
    }
    for topic in topics:
        for key in topic_metric_map.get(topic, ()):
            wanted.add(key)

    if "ebitda" in q:
        wanted.update({"ebitda", "revenue", "gross_margin", "operating_margin", "marketing_spend", "cost"})
    elif "margin" in q or ("profit" in q and "growth" not in q):
        wanted.update({"gross_margin", "operating_margin", "ebitda", "revenue", "profit"})
    if "customer" in q or "cac" in q or "ltv" in q or "marketing" in q:
        wanted.update({"cac", "ltv", "churn", "nrr", "customer_count", "market_share"})
    if ("growth" in q or "aggressive" in q) and ("profit" in q or "margin" in q):
        wanted.update(
            {
                "revenue",
                "operating_margin",
                "gross_margin",
                "ebitda",
                "cac",
                "ltv",
                "market_share",
                "customer_count",
                "capacity_utilization",
            }
        )
    elif "growth" in q and "profit" not in q:
        wanted.update({"revenue", "market_share", "customer_count", "cac"})
    if "capacity" in q or ("operational" in q and "working" not in q):
        wanted.update({"capacity_utilization", "on_time_delivery", "defect_rate"})
    if "market share" in q or ("share" in q and "market" in q):
        wanted.update({"market_share", "cac", "ltv", "customer_count"})
    if "financial performance" in q or ("overall" in q and "performance" in q):
        wanted.update({"revenue", "ebitda", "gross_margin", "operating_margin", "free_cash_flow", "cash"})

    return wanted - explicit_keys


def _collect_metrics(
    profile: CompanyDataProfile,
    wanted: set[str],
    *,
    order: list[str] | None = None,
) -> list[MetricSnapshot]:
    selected: list[MetricSnapshot] = []
    keys = order if order else sorted(wanted)
    for key in keys:
        if key not in wanted:
            continue
        metric = profile.get(key)
        if metric and metric.available and metric not in selected:
            selected.append(metric)
    return selected


def _classify_metric_direction(metrics: list[MetricSnapshot]) -> tuple[list[MetricSnapshot], list[MetricSnapshot]]:
    positive: list[MetricSnapshot] = []
    negative: list[MetricSnapshot] = []
    for metric in metrics:
        if metric.business_direction == "improved":
            positive.append(metric)
        elif metric.business_direction == "deteriorated":
            negative.append(metric)
    return positive, negative


def _finalize_metric(snapshot: MetricSnapshot) -> None:
    semantics = get_semantics(snapshot.key)
    snapshot.label = semantics.label if semantics.label else snapshot.label
    if semantics.category != "unknown":
        snapshot.category = semantics.category
    snapshot.business_direction = compute_business_direction(snapshot.key, snapshot.trend)


def _infer_drivers(
    profile: CompanyDataProfile,
    question: str,
    topics: frozenset[str],
    analysis: QuestionAnalysis,
) -> list[str]:
    drivers: list[str] = []
    q = question.lower()
    revenue = profile.get("revenue")
    ebitda = profile.get("ebitda")
    gross = profile.get("gross_margin")
    marketing = profile.get("marketing_spend")
    cac = profile.get("cac")
    capacity = profile.get("capacity_utilization")

    if "ebitda" in q and revenue and ebitda and revenue.trend == "increasing" and ebitda.trend == "decreasing":
        if gross and gross.trend == "decreasing":
            drivers.append("Gross margin compression may be absorbing revenue growth.")
        if marketing and marketing.trend == "increasing":
            drivers.append("Rising marketing spend may be outpacing incremental gross profit.")
        if cac and cac.trend == "increasing":
            drivers.append("Higher CAC can inflate acquisition cost without proportional EBITDA gain.")
        if not drivers:
            drivers.append("Revenue growth is not translating proportionally into EBITDA based on uploaded trends.")

    if "capacity" in q or "efficien" in q or "operational" in q:
        if capacity and capacity.current is not None:
            if capacity.current >= 85:
                drivers.append(
                    f"Capacity utilization at {capacity.format_value(capacity.current)} suggests limited headroom."
                )
            elif capacity.trend == "increasing":
                drivers.append("Rising utilization may signal approaching constraints even if efficiency improved.")

    if "market share" in q:
        share = profile.get("market_share")
        if share and cac and share.trend == "increasing" and cac.trend == "increasing":
            drivers.append("Share gains may be coming at worsening acquisition economics.")

    if analysis.assessment == "mixed" and not drivers:
        imp = ", ".join(m.label for m in analysis.improving[:3])
        det = ", ".join(m.label for m in analysis.deteriorating[:3])
        if imp and det:
            drivers.append(f"Improvements in {imp} conflict with pressure in {det}.")

    return drivers


def _missing_for_question(question: str, topics: frozenset[str], profile: CompanyDataProfile) -> list[str]:
    q = question.lower()
    required: list[str] = []
    checks = {
        "ebitda": ("ebitda",),
        "margin": ("gross_margin", "operating_margin"),
        "profit margin": ("gross_margin", "profit", "ebitda"),
        "market share": ("market_share",),
        "cac": ("cac",),
        "ltv": ("ltv",),
        "churn": ("churn",),
        "capacity": ("capacity_utilization",),
        "dso": ("dso",),
        "customer economics": ("cac", "ltv", "churn", "nrr"),
    }
    for phrase, keys in checks.items():
        if phrase in q and not any(profile.get(k) and profile.get(k).available for k in keys):
            required.extend(k.replace("_", " ") for k in keys if not profile.get(k))
    return sorted(set(required))


def _find_metric_name_column(row: dict[str, Any]) -> str | None:
    for key in row:
        normalized = str(key).lower().replace(" ", "_")
        if normalized in {"metric", "metrics", "measure", "kpi", "name", "indicator"}:
            return key
    for key in row:
        if _to_float(row.get(key)) is None:
            return key
    return None


def _pick_value(row: dict[str, Any], hints: tuple[str, ...]) -> float | None:
    for key, value in row.items():
        normalized = str(key).lower().replace(" ", "_")
        if any(hint == normalized or hint in normalized for hint in hints):
            num = _to_float(value)
            if num is not None:
                return num
    return None


def _find_period_key(row: dict[str, Any]) -> str | None:
    for key in row:
        normalized = str(key).lower().replace(" ", "_")
        if any(h in normalized for h in PERIOD_HINTS):
            return key
    return None


def _sort_records(records: list[dict[str, Any]], period_key: str | None) -> list[dict[str, Any]]:
    if not period_key:
        return records

    def sort_key(row: dict[str, Any]) -> tuple[int, str]:
        label = str(row.get(period_key, ""))
        match = re.search(r"(\d+)", label)
        number = int(match.group(1)) if match else 0
        return number, label

    return sorted(records, key=sort_key)


def _canonical_metric_key(name: str) -> str:
    normalized = name.lower().replace(" ", "_").replace("-", "_")

    # Exact matches first (avoid "sales" in "days_sales_outstanding" -> revenue).
    for canonical, hints in METRIC_HINTS.items():
        for hint in hints:
            hint_norm = hint.replace(" ", "_")
            if hint_norm == normalized:
                return canonical

    # Then longest substring hint wins.
    best: tuple[int, str] | None = None
    for canonical, hints in METRIC_HINTS.items():
        for hint in hints:
            hint_norm = hint.replace(" ", "_")
            if hint_norm in normalized or normalized in hint_norm:
                score = len(hint_norm)
                if best is None or score > best[0]:
                    best = (score, canonical)
    if best:
        return best[1]
    return normalized


def _guess_category(field_name: str) -> str:
    canonical = _canonical_metric_key(field_name)
    return METRIC_CATEGORY.get(canonical, "financial")


def _infer_unit(field_name: str, value: float | None) -> str:
    lowered = field_name.lower()
    if any(token in lowered for token in ("margin", "share", "churn", "attrition", "utilization", "rate", "nrr")):
        return "percent"
    if any(token in lowered for token in ("revenue", "ebitda", "cash", "debt", "spend", "cost", "profit")):
        return "currency"
    if any(token in lowered for token in ("cac", "ltv", "nps")):
        return "ratio"
    if value is not None and 0 < value <= 1 and "margin" in lowered:
        return "percent"
    return "count"


def _direction(first: float, last: float) -> str:
    threshold = max(abs(first) * 0.01, 0.05)
    if abs(last - first) <= threshold:
        return "stable"
    return "increasing" if last > first else "decreasing"


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("%", "").replace("$", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _format_currency(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
