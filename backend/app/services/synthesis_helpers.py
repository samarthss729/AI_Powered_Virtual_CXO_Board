"""Shared board synthesis logic for demo mode and confidence scoring."""

from __future__ import annotations

import re
from typing import Any

from app.services.contradiction_helpers import (
    board_contradiction_note,
    detect_cfo_financial_contradictions,
    detect_coo_operational_constraints,
    format_contradictory_evidence,
    format_operational_constraint_evidence,
)
from app.services.data_service import CompanyDataProfile, MetricSnapshot, QuestionAnalysis, split_sentences


def _relevant_metric(
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    key: str,
) -> MetricSnapshot | None:
    """Return a profile metric only when it is in the current question relevance set."""
    if not any(m.key == key for m in analysis.relevant_metrics):
        return None
    return profile.get(key)


def top_evidence_lines(
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    *,
    limit: int | None = 4,
) -> list[str]:
    """Pick evidence sentences from the current question's relevant metrics only."""
    lines: list[str] = []
    seen: set[str] = set()
    ordered = list(analysis.primary_metrics) + [
        m for m in analysis.relevant_metrics if m.key not in {p.key for p in analysis.primary_metrics}
    ]
    for metric in ordered:
        sentence = metric.business_compare_sentence() or metric.compare_sentence()
        if sentence and sentence not in seen:
            lines.append(sentence)
            seen.add(sentence)
        if limit is not None and len(lines) >= limit:
            break
    return lines


def primary_evidence_text(analysis: QuestionAnalysis) -> str:
    """All primary-metric evidence for the current question (no arbitrary cap)."""
    lines: list[str] = []
    for metric in analysis.primary_metrics:
        sentence = metric.business_compare_sentence() or metric.compare_sentence()
        if sentence:
            lines.append(sentence)
    return "; ".join(lines)


def compute_synthesis_confidence(
    question: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
) -> str:
    """Score confidence from data availability, direct answerability, and contradictions."""
    if not profile.has_upload:
        return "Low"

    q = question.lower()
    score = 0

    if analysis.relevant_metrics:
        score += 2
    if len(analysis.evidence_lines) >= 3:
        score += 1

    # Penalize when the question asks for a metric that is missing.
    if analysis.missing_metrics:
        score -= 2
    elif any(token in q for token in ("ebitda", "margin", "cac", "ltv", "market share")):
        score += 1

    if analysis.assessment == "mixed":
        score -= 1
    elif analysis.assessment in {"improving", "deteriorating", "stable"}:
        score += 1

    if analysis.assessment == "insufficient":
        score -= 2

    if score >= 4:
        result = "High"
    elif score >= 1:
        result = "Medium"
    else:
        result = "Low"

    # Direct metric missing when explicitly requested → cap confidence.
    if "ebitda" in q and not profile.has_metric("ebitda"):
        return "Low" if result == "High" else result
    if any(token in q for token in ("dso", "working capital", "working-capital")) and not profile.has_metric("dso"):
        return "Low" if result == "High" else result

    return result


def build_direct_recommendation(
    question: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    discussion: list[dict[str, Any]] | None = None,
) -> str:
    """Build a question-specific board recommendation grounded in uploaded metrics."""
    q = question.lower()
    evidence = top_evidence_lines(
        profile,
        analysis,
        limit=max(6, len(analysis.primary_metrics)) if analysis.primary_metrics else 4,
    )
    evidence_text = primary_evidence_text(analysis) or ("; ".join(evidence[:6]) if evidence else "")

    # Missing explicit metric (e.g. EBITDA) — do not hallucinate.
    if analysis.missing_metrics:
        missing_label = analysis.missing_metrics[0]
        caveat = (
            f"The uploaded dataset does not contain an explicit {missing_label} value, "
            "so the board cannot verify that metric's movement from direct data."
        )
        related = [line for line in evidence if missing_label.replace(" ", "_") not in line.lower()]
        if related:
            caveat += f" Related evidence: {'; '.join(related[:3])}."
        answer = _answer_from_question_type(q, profile, analysis, evidence)
        if answer:
            return f"{answer} {caveat}"
        return f"{caveat} {_tradeoff_clause(profile, analysis)}"

    answer = _answer_from_question_type(q, profile, analysis, evidence)
    if not answer:
        answer = _default_answer(profile, analysis)

    parts = [answer]
    if len(analysis.primary_metrics) >= 2:
        tradeoff = ""  # multi-metric assessment is self-contained
    else:
        tradeoff = _tradeoff_clause(profile, analysis)
        if tradeoff and tradeoff.lower() not in answer.lower():
            parts.append(tradeoff)

    if evidence_text and evidence_text.lower() not in answer.lower():
        parts.append(f"Key evidence: {evidence_text}.")

    return " ".join(parts)


def _answer_from_question_type(
    q: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    evidence: list[str],
) -> str:
    """Route to the most appropriate direct-answer template."""
    if len(analysis.primary_metrics) >= 2 and any(
        phrase in q
        for phrase in ("accelerate growth", "consolidating profitability", "growth next period")
    ):
        return _answer_growth_acceleration_decision(profile, analysis)
    if len(analysis.primary_metrics) >= 2:
        return _answer_multi_metric_assessment(profile, analysis)

    if _is_margin_trend_question(q):
        return _answer_margin_trend(profile, analysis)
    if any(
        token in q
        for token in ("working capital", "working-capital", "dso", "days sales outstanding", "cash conversion")
    ):
        return _answer_working_capital(profile, analysis)
    if "ebitda" in q and ("fall" in q or "decreas" in q or "drop" in q or "driver" in q or "cause" in q):
        if not profile.has_metric("ebitda"):
            return ""  # handled by missing-metrics branch in build_direct_recommendation
        return _answer_ebitda_drivers(profile, analysis)
    if ("marketing" in q or "market spend" in q) and any(
        w in q for w in ("increase", "invest", "spend", "more", "further")
    ):
        return _answer_marketing_investment(profile, analysis)
    if ("growth" in q or "aggressive" in q or "expand" in q) and any(
        w in q for w in ("profit", "profitability", "margin", "priorit")
    ):
        return _answer_growth_vs_profitability(profile, analysis)
    if "margin" in q and any(w in q for w in ("improv", "increasing", "better", "trend")):
        return _answer_margin_improving(profile, analysis)
    if "risk" in q:
        return _answer_risks(profile, analysis)
    if analysis.assessment == "mixed":
        return _answer_mixed(profile, analysis)
    if analysis.assessment == "improving":
        return (
            "Based on uploaded metrics, performance is improving on the most relevant indicators. "
            "The board recommends continuing current initiatives while monitoring constraints."
        )
    if analysis.assessment == "deteriorating":
        return (
            "Based on uploaded metrics, several key indicators are deteriorating. "
            "The board recommends corrective action focused on the weakest metrics before expanding spend."
        )
    return ""


def _growth_accelerate_conditions(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    """Decision thresholds for accelerating growth — conditions, not claims."""
    parts = [
        "CAC remains efficient or improves",
        "contribution margin and operating margin do not deteriorate materially",
        "customer growth and market-share gains remain strong",
        "capacity/throughput can absorb incremental demand",
        "LTV/payback remains healthy",
    ]
    cap = _relevant_metric(profile, analysis, "capacity_utilization")
    if cap and cap.current is not None and cap.current >= 75:
        parts[-2] = (
            f"capacity stays below a safe threshold (currently {cap.format_value(cap.current)} utilization)"
        )
    return "; ".join(parts) + "."


def _growth_consolidate_conditions(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    """Decision thresholds for consolidating profitability — conditions, not claims."""
    parts = [
        "CAC deteriorates materially",
        "contribution margin weakens",
        "operating margin declines",
        "capacity approaches a constraint",
        "incremental growth requires disproportionately higher cost",
        "payback/LTV deteriorates",
        "growth stops translating into profitable economics",
    ]
    return "; ".join(parts) + "."


def _answer_growth_acceleration_decision(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    """Board stance when CEO asks to accelerate growth vs consolidate profitability with explicit metrics."""
    observed: list[str] = []
    for metric in analysis.primary_metrics:
        sentence = metric.business_compare_sentence() or metric.compare_sentence()
        if sentence:
            observed.append(f"Observed: {sentence}")

    cap = _relevant_metric(profile, analysis, "capacity_utilization")
    capacity_note = ""
    if cap and cap.current is not None:
        capacity_note = (
            f" Operational capacity utilization at {cap.format_value(cap.current)} should govern the pace."
        )

    evidence_text = primary_evidence_text(analysis)
    accelerate = _growth_accelerate_conditions(profile, analysis)
    consolidate = _growth_consolidate_conditions(profile, analysis)
    contradiction_clause = board_contradiction_note(profile, analysis, analysis.question)

    financial_contradictions = detect_cfo_financial_contradictions(profile, analysis, analysis.question)
    operational_constraints = detect_coo_operational_constraints(profile, analysis, analysis.question)
    contradiction_evidence_parts: list[str] = []
    if financial_contradictions:
        contradiction_evidence_parts.append(format_contradictory_evidence(financial_contradictions))
    if operational_constraints:
        contradiction_evidence_parts.append(format_operational_constraint_evidence(operational_constraints))

    return (
        "Decision: Selective growth acceleration rather than broad consolidation or unchecked speed, "
        "because the metrics explicitly cited in the question improved in the uploaded data."
        f"{capacity_note} "
        + " ".join(observed)
        + (f" {' '.join(contradiction_evidence_parts)}" if contradiction_evidence_parts else "")
        + (f" {contradiction_clause}" if contradiction_clause else "")
        + f" Conditions to accelerate further: {accelerate}"
        + f" Conditions to consolidate profitability: {consolidate}"
        + (f" Key evidence: {evidence_text}." if evidence_text else "")
    )


def _answer_multi_metric_assessment(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    """Direct board answer when the CEO explicitly names multiple metrics."""
    observed: list[str] = []
    for metric in analysis.primary_metrics:
        sentence = metric.business_compare_sentence() or metric.compare_sentence()
        if sentence:
            observed.append(f"Observed: {sentence}")

    if analysis.assessment == "improving":
        verdict = "Overall, the explicitly cited metrics indicate improving performance."
    elif analysis.assessment == "deteriorating":
        verdict = "Overall, the explicitly cited metrics indicate deteriorating performance."
    elif analysis.assessment == "mixed":
        verdict = "Overall, the explicitly cited metrics show a mixed performance picture."
    else:
        verdict = "The board assessment is based solely on the metrics named in the question."

    return " ".join([verdict, *observed])


def _is_margin_trend_question(q: str) -> bool:
    return "margin" in q and any(
        w in q for w in ("increasing", "decreasing", "improving", "worsening", "trend", "going up", "going down")
    )


def _answer_margin_trend(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    op = profile.get("operating_margin")
    gross = profile.get("gross_margin")
    if op and op.available and op.previous is not None:
        direction = op.business_direction
        if direction == "improved":
            base = f"Yes. Operating margin improved from {op.format_value(op.previous)} to {op.format_value(op.current)}."
        elif direction == "deteriorated":
            base = f"No. Operating margin deteriorated from {op.format_value(op.previous)} to {op.format_value(op.current)}."
        else:
            base = f"Operating margin is approximately stable at {op.format_value(op.current)}."
        if gross and gross.available:
            base += f" Gross margin is {gross.format_value(gross.current)}."
        return base
    if gross and gross.available:
        direction = gross.business_direction
        if direction == "improved":
            return f"Gross margin improved from {gross.format_value(gross.previous)} to {gross.format_value(gross.current)}."
        if direction == "deteriorated":
            return f"Gross margin deteriorated from {gross.format_value(gross.previous)} to {gross.format_value(gross.current)}."
    return ""


def _answer_margin_improving(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    return _answer_margin_trend(profile, analysis) or _default_answer(profile, analysis)


def _answer_working_capital(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    dso = profile.get("dso")
    cash = profile.get("free_cash_flow") or profile.get("cash")
    if dso and dso.available and dso.previous is not None:
        if dso.business_direction == "improved":
            return (
                f"Working-capital efficiency appears to be improving. Observed: DSO improved from "
                f"{dso.format_value(dso.previous)} to {dso.format_value(dso.current)}. "
                "The CFO should maintain collections discipline and monitor receivables aging."
            )
        if dso.business_direction == "deteriorated":
            return (
                f"Working-capital efficiency appears to be deteriorating. Observed: DSO deteriorated from "
                f"{dso.format_value(dso.previous)} to {dso.format_value(dso.current)}. "
                "The CFO should tighten collections and investigate receivables aging."
            )
        return (
            f"DSO is approximately stable at {dso.format_value(dso.current)}. "
            "Continue monitoring receivables and cash conversion."
        )
    if cash and cash.available:
        return (
            f"Direct working-capital metrics such as DSO are unavailable. "
            f"Observed cash-related metric: {cash.label} is {cash.format_value(cash.current)}."
        )
    return (
        "Working-capital metrics such as DSO are not available in the uploaded dataset. "
        "The board cannot assess working-capital efficiency from direct evidence."
    )


def _answer_ebitda_drivers(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    ebitda = profile.get("ebitda")
    if ebitda and ebitda.available:
        drivers: list[str] = []
        gross = profile.get("gross_margin")
        marketing = profile.get("marketing_spend")
        if gross and gross.business_direction == "deteriorated":
            drivers.append("gross margin compression")
        if marketing and marketing.trend == "increasing":
            drivers.append("rising marketing spend")
        if ebitda.business_direction == "deteriorated":
            driver_text = ", ".join(drivers) if drivers else "cost or mix pressure not fully offset by revenue"
            return (
                f"EBITDA deteriorated from {ebitda.format_value(ebitda.previous)} to "
                f"{ebitda.format_value(ebitda.current)}. Likely drivers include {driver_text}."
            )
    return ""


def _answer_marketing_investment(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    cac = _relevant_metric(profile, analysis, "cac")
    share = _relevant_metric(profile, analysis, "market_share")
    cap = _relevant_metric(profile, analysis, "capacity_utilization")
    ltv = _relevant_metric(profile, analysis, "ltv")

    cac_improved = cac and cac.business_direction == "improved"
    share_improved = share and share.business_direction == "improved"
    cap_high = cap and cap.current is not None and cap.current >= 75

    if cac_improved and share_improved:
        answer = (
            f"Increase marketing selectively, not broadly. CAC improved from "
            f"{cac.format_value(cac.previous)} to {cac.format_value(cac.current)}"
        )
        if share:
            answer += f" and market share increased from {share.format_value(share.previous)} to {share.format_value(share.current)}"
        answer += "."
        if ltv and ltv.business_direction == "improved":
            answer += f" LTV also rose to {ltv.format_value(ltv.current)}, supporting unit economics."
        if cap_high:
            answer += f" However, capacity utilization at {cap.format_value(cap.current)} limits how aggressively demand can scale."
        return answer

    if cac and cac.business_direction == "deteriorated":
        return (
            f"Do not increase marketing broadly. CAC deteriorated from "
            f"{cac.format_value(cac.previous)} to {cac.format_value(cac.current)}; "
            "audit channel ROI before scaling spend."
        )
    return "Increase marketing only in channels with proven CAC efficiency and acceptable payback."


def _answer_growth_vs_profitability(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    cac = _relevant_metric(profile, analysis, "cac")
    share = _relevant_metric(profile, analysis, "market_share")
    ltv = _relevant_metric(profile, analysis, "ltv")
    op_margin = _relevant_metric(profile, analysis, "operating_margin")
    cap = _relevant_metric(profile, analysis, "capacity_utilization")

    margin_improving = op_margin and op_margin.business_direction == "improved"
    cac_improved = cac and cac.business_direction == "improved"
    share_improved = share and share.business_direction == "improved"
    cap_high = cap and cap.current is not None and cap.current >= 75

    if (margin_improving or cac_improved) and share_improved:
        parts = ["Prioritize selective growth rather than aggressive expansion or broad cost cutting."]
        if share:
            parts.append(
                f"Market share increased from {share.format_value(share.previous)} to {share.format_value(share.current)}."
            )
        if cac:
            parts.append(f"CAC improved from {cac.format_value(cac.previous)} to {cac.format_value(cac.current)}.")
        if ltv and ltv.business_direction == "improved":
            parts.append(f"LTV increased to {ltv.format_value(ltv.current)}.")
        if op_margin and margin_improving:
            parts.append(
                f"Operating margin improved from {op_margin.format_value(op_margin.previous)} to "
                f"{op_margin.format_value(op_margin.current)}."
            )
        if cap_high:
            parts.append(
                f"However, capacity utilization at {cap.format_value(cap.current)} means growth should be "
                "scaled selectively where unit economics remain attractive and operational capacity can support it."
            )
        return " ".join(parts)

    if analysis.assessment == "deteriorating" or (
        op_margin and op_margin.business_direction == "deteriorated"
    ):
        return (
            "Prioritize profitability improvement over aggressive growth. "
            "Key margin and earnings metrics are under pressure in the uploaded data; "
            "stabilize unit economics before scaling demand."
        )

    return (
        "Prioritize selective growth while protecting profitability. "
        "Scale only where uploaded unit-economics and capacity metrics support incremental volume."
    )


def _answer_mixed(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    improved = ", ".join(m.label for m in analysis.improving[:2]) or "some metrics"
    weakened = ", ".join(m.label for m in analysis.deteriorating[:2]) or "other metrics"
    return (
        f"Pursue a targeted plan rather than broad growth or austerity. "
        f"{improved} improved while {weakened} weakened, creating a trade-off that requires selective action."
    )


def _answer_risks(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    risks: list[str] = []
    for metric in analysis.deteriorating[:3]:
        risks.append(f"{metric.label} deterioration")
    cap = _relevant_metric(profile, analysis, "capacity_utilization")
    if cap and cap.current is not None and cap.current >= 80:
        risks.append(f"capacity pressure at {cap.format_value(cap.current)}")
    if risks:
        return f"The primary risks from uploaded data are: {', '.join(risks)}."
    return "Monitor metric trends closely; no single dominant risk stands out in the uploaded data."


def _default_answer(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    if analysis.drivers:
        return f"{analysis.drivers[0]} The board recommends evidence-backed, selective action."
    if analysis.assessment == "mixed":
        return _answer_mixed(profile, analysis)
    return "The board recommends a disciplined, data-grounded plan aligned to the strongest uploaded metrics."


def _tradeoff_clause(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    cap = _relevant_metric(profile, analysis, "capacity_utilization")
    if cap and cap.current is not None and cap.current >= 75:
        return f"Main trade-off: growth opportunity versus capacity constraint at {cap.format_value(cap.current)} utilization."
    if analysis.assessment == "mixed":
        return "Main trade-off: improving demand metrics versus pressure on profitability or efficiency."
    cac = _relevant_metric(profile, analysis, "cac")
    share = _relevant_metric(profile, analysis, "market_share")
    if cac and share and cac.business_direction == "improved" and share.business_direction == "improved":
        return "Main trade-off: capturing share gains versus maintaining acquisition efficiency and margin discipline."
    return ""


def build_synthesis_actions(
    question: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
) -> list[str]:
    """Concrete board actions tied to question topics and available metrics."""
    actions: list[str] = []
    q = question.lower()

    if analysis.missing_metrics or ("ebitda" in q and not profile.has_metric("ebitda")):
        actions.append("Build margin/EBITDA bridge from uploaded period data to isolate profit drivers")
    if "marketing" in q or any(m.key == "cac" for m in analysis.relevant_metrics):
        actions.append("Audit CAC and conversion by channel; scale only profitable cohorts")
    if (
        any(m.key == "ltv" for m in analysis.relevant_metrics)
        and any(m.key == "cac" for m in analysis.relevant_metrics)
    ):
        actions.append("Monitor LTV/CAC ratio and payback before increasing marketing spend")
    if "capacity" in q or any(m.key == "capacity_utilization" for m in analysis.relevant_metrics):
        actions.append("Validate throughput and service capacity before increasing demand generation")
    if "margin" in q or "profit" in q or any(
        m.key in {"operating_margin", "gross_margin"} for m in analysis.relevant_metrics
    ):
        actions.append("Segment margin by product/channel to identify profit leakages")
    if "growth" in q and any(m.key == "market_share" for m in analysis.relevant_metrics):
        actions.append("Define selective growth targets tied to share gain and unit-economics thresholds")
    if any(m.key == "dso" for m in analysis.relevant_metrics):
        actions.append("Review receivables aging and tighten collections where DSO trends worsen")
    if not actions:
        actions.append("Assign metric owners and reconvene within 30 days with updated dashboards")
    return actions[:4]


def _disagreement_is_relevant(content: str, analysis: QuestionAnalysis) -> bool:
    """Keep disagreements tied to metrics relevant to the current question."""
    lower = content.lower()
    relevant_keys = {m.key for m in analysis.relevant_metrics}
    if "cac" not in relevant_keys and any(
        token in lower for token in ("cac", "cost per acquisition", "acquisition efficiency")
    ):
        return False
    if "market_share" not in relevant_keys and "market share" in lower:
        return False
    if "dso" not in relevant_keys and any(
        token in lower for token in ("dso", "days sales outstanding", "working capital", "working-capital")
    ):
        return False
    if "capacity_utilization" not in relevant_keys and "utilization" in lower:
        return False
    return True


def build_synthesis_disagreements(
    discussion: list[dict[str, Any]],
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
) -> list[str]:
    """Extract genuine executive tensions from Round 2 or infer from role perspectives."""
    items: list[str] = []
    round_two = [e for e in discussion if e.get("round") == 2]

    for entry in round_two:
        role = str(entry.get("role", ""))
        content = str(entry.get("content", ""))
        if not _disagreement_is_relevant(content, analysis):
            continue
        lower = content.lower()
        if any(token in lower for token in ("disagree", "however", "would not approve", "push back", "but i")):
            sentence = split_sentences(content)[0][:180]
            if sentence and not sentence.lower().startswith('on "'):
                items.append(f"{role}: {sentence}")

    if items:
        return items[:4]

    # Infer role-based tensions when Round 2 shows alignment but perspectives differ.
    cac = _relevant_metric(profile, analysis, "cac")
    cap = _relevant_metric(profile, analysis, "capacity_utilization")
    inferred: list[str] = []

    if cac and cac.business_direction == "improved":
        inferred.append("CFO: scale marketing only after contribution margin and payback are confirmed.")
        inferred.append("CMO: selective scaling is justified where CAC is falling and LTV is rising.")
    if cap and cap.current is not None and cap.current >= 70:
        inferred.append(
            f"COO: growth is constrained by capacity utilization at {cap.format_value(cap.current)}."
        )
    if analysis.assessment == "mixed":
        inferred.append("CSO: strategic opportunity exists but requires validating whether gains are durable.")

    return inferred[:4] if inferred else []


def extract_peer_claim(peer_text: str) -> str:
    """Pull a short, quotable point from a Round 1 peer response."""
    for prefix in ("Recommendation:", "Interpretation:", "Evidence:"):
        if prefix in peer_text:
            segment = peer_text.split(prefix, 1)[1].strip()
            first = segment.split(".")[0].strip()
            if len(first) > 15 and len(first) < 140:
                return first
    for sentence in split_sentences(peer_text):
        lower = sentence.lower()
        if lower.startswith("perspective"):
            continue
        if lower.startswith("evidence:"):
            claim = sentence.replace("Evidence:", "").strip()
            if len(claim) > 15:
                return claim[:120]
            continue
        if len(sentence) > 20 and "recommendation" not in lower[:20]:
            return sentence[:120]
    return ""


def extract_peer_metric(peer_text: str) -> str | None:
    """Find a numeric metric reference in peer text for natural Round 2 citations."""
    match = re.search(
        r"((?:CAC|LTV|market share|operating margin|capacity|revenue|EBITDA)[^.]{0,60}\d[^.]*)",
        peer_text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()[:100]
    return None
