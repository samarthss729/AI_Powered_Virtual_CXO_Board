"""Deterministic, data-aware executive mock responses for DEMO_MODE."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.board_context import get_board_turn
from app.services.data_service import (
    CompanyDataProfile,
    MetricSnapshot,
    QuestionAnalysis,
    analyze_question,
    build_company_profile,
    profile_from_structured_payload,
    select_persona_metric_groups,
    select_persona_metrics,
    split_sentences,
)
from app.services.contradiction_helpers import (
    board_contradiction_note,
    cfo_contradiction_interpretation,
    coo_constraint_interpretation,
    detect_cfo_financial_contradictions,
    detect_coo_operational_constraints,
    format_contradictory_evidence,
    format_operational_constraint_evidence,
)
from app.services.synthesis_helpers import (
    build_direct_recommendation,
    build_synthesis_actions,
    build_synthesis_disagreements,
    compute_synthesis_confidence,
    extract_peer_claim,
    extract_peer_metric,
)


ROLES = ("CFO", "CMO", "COO", "CSO")
PERSONA_LENS = {
    "CFO": "profitability, margins, cash, working capital, ROI, and financial risk",
    "CMO": "market share, acquisition, retention, LTV/CAC, demand, and brand",
    "COO": "capacity, throughput, cost-to-serve, execution feasibility, and operational risk",
    "CSO": "competitive positioning, market structure, and long-term strategic trade-offs",
}


def detect_role(system_prompt: str, user_prompt: str) -> str | None:
    combined = f"{system_prompt}\n{user_prompt}"
    if "Boardroom Synthesizer" in system_prompt:
        return "SYNTHESIS"
    for marker, role in (
        ("You are the CFO", "CFO"),
        ("You are the CMO", "CMO"),
        ("You are the COO", "COO"),
        ("Chief Strategy Officer", "CSO"),
    ):
        if marker in combined:
            return role
    for role in ROLES:
        if f"as the {role}" in user_prompt or f"Respond as the {role}" in user_prompt:
            return role
    return None


def detect_round(user_prompt: str) -> int:
    return 2 if "This is Round 2" in user_prompt else 1


def extract_question(user_prompt: str) -> str:
    match = re.search(
        r"CEO question:\s*\n(.*?)\n\nCompany data context:",
        user_prompt,
        flags=re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    turn = get_board_turn()
    return turn.question if turn and turn.question else user_prompt.strip()[:500]


def extract_peer_opinions(user_prompt: str) -> dict[str, str]:
    turn = get_board_turn()
    if turn and turn.peer_round_one:
        return dict(turn.peer_round_one)
    match = re.search(
        r"peers' Round 1 opinions:\s*\n\n(.*?)\n\nYour Round 1 response:",
        user_prompt,
        flags=re.DOTALL,
    )
    if not match:
        return {}
    block = match.group(1).strip()
    opinions: dict[str, str] = {}
    pattern = re.compile(
        rf"({'|'.join(ROLES)}):\s*\n(.*?)(?=\n\n(?:{'|'.join(ROLES)}):|\Z)",
        flags=re.DOTALL,
    )
    for role_match in pattern.finditer(block):
        opinions[role_match.group(1)] = role_match.group(2).strip()
    return opinions


def mock_chat(*, system_prompt: str, user_prompt: str) -> str:
    question, role, round_number, profile, analysis = _resolve_context(user_prompt)
    if role == "SYNTHESIS":
        return json.dumps(mock_synthesis_json(user_prompt=user_prompt))
    if round_number == 1:
        return _round_one(role, question, profile, analysis)
    return _round_two(role, question, profile, analysis, extract_peer_opinions(user_prompt))


def _resolve_context(user_prompt: str) -> tuple[str, str, int, CompanyDataProfile, QuestionAnalysis]:
    turn = get_board_turn()
    question = extract_question(user_prompt)
    role = (turn.role if turn else None) or detect_role("", user_prompt) or "CFO"
    round_number = turn.round_number if turn else detect_round(user_prompt)
    profile = turn.company_profile if turn and turn.company_profile else _profile_from_prompt(user_prompt)
    analysis = turn.question_analysis if turn and turn.question_analysis else analyze_question(profile, question)
    return question, role, round_number, profile, analysis


def _profile_from_prompt(user_prompt: str) -> CompanyDataProfile:
    marker = "STRUCTURED_COMPANY_DATA:"
    if marker not in user_prompt:
        return CompanyDataProfile(has_upload=False)
    start = user_prompt.index(marker) + len(marker)
    json_start = user_prompt.find("{", start)
    if json_start < 0:
        return CompanyDataProfile(has_upload=False)
    depth = 0
    for index, char in enumerate(user_prompt[json_start:], start=json_start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return profile_from_structured_payload(json.loads(user_prompt[json_start : index + 1]))
                except json.JSONDecodeError:
                    break
    return CompanyDataProfile(has_upload=False)


def _round_one(role: str, question: str, profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    if not profile.has_upload:
        return (
            f"Perspective ({role}): No company data is uploaded for this session, so I cannot cite internal metrics. "
            f"Recommendation: upload CSV/JSON before expecting a quantitative board answer."
        )

    primary, secondary = select_persona_metric_groups(
        profile,
        role,
        question,
        analysis.primary_metrics,
        analysis.secondary_metrics,
        analysis.relevant_metrics,
        limit=6,
    )
    perspective = f"Perspective ({role}): Assessing through {PERSONA_LENS[role]}."
    evidence = _evidence_block(primary, secondary, question, profile, analysis, role=role)
    interpretation = _interpretation(role, question, profile, analysis, primary + secondary)
    recommendation = _recommendation(role, question, profile, analysis)
    risks = _risks(role, profile, analysis)
    return " ".join(part for part in (perspective, evidence, interpretation, recommendation, risks) if part)


def _metric_evidence_line(metric: MetricSnapshot) -> str | None:
    return metric.business_compare_sentence() or metric.compare_sentence()


def _evidence_block(
    primary: list[MetricSnapshot],
    secondary: list[MetricSnapshot],
    question: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    *,
    role: str | None = None,
) -> str:
    q = question.lower()
    multi_explicit = len(analysis.primary_metrics) >= 2

    if not multi_explicit and "ebitda" in q and not profile.has_metric("ebitda"):
        supporting = []
        for key in ("operating_margin", "gross_margin", "revenue", "marketing_spend"):
            metric = profile.get(key)
            if metric and metric.available:
                line = _metric_evidence_line(metric)
                if line:
                    supporting.append(line)
        if supporting:
            return (
                "Evidence: The uploaded dataset does not contain an explicit EBITDA value, so I cannot state "
                f"whether EBITDA changed. Related evidence: {'; '.join(supporting[:3])}."
            )
        return (
            "Evidence: The uploaded dataset does not contain an explicit EBITDA value, so I cannot determine "
            "EBITDA movement from direct data."
        )

    if not multi_explicit and ("dso" in q or "days sales outstanding" in q) and profile.has_metric("dso"):
        dso = profile.get("dso")
        if dso:
            return f"Evidence: {_metric_evidence_line(dso)}."

    primary_lines = [_metric_evidence_line(m) for m in primary]
    primary_lines = [line for line in primary_lines if line]
    secondary_lines = [_metric_evidence_line(m) for m in secondary]
    secondary_lines = [line for line in secondary_lines if line]

    if not primary_lines and not secondary_lines:
        return "Evidence: Limited quantitative fields are available for this question."

    parts: list[str] = []
    if primary_lines:
        parts.append("Evidence: " + "; ".join(primary_lines) + ".")
    if secondary_lines:
        parts.append("Supporting evidence: " + "; ".join(secondary_lines) + ".")
    if role == "CFO":
        contradictions = detect_cfo_financial_contradictions(profile, analysis, question)
        contradiction_text = format_contradictory_evidence(contradictions)
        if contradiction_text:
            parts.append(contradiction_text)
    if role == "COO":
        constraints = detect_coo_operational_constraints(profile, analysis, question)
        constraint_text = format_operational_constraint_evidence(constraints)
        if constraint_text:
            parts.append(constraint_text)
    return " ".join(parts)


def _interpretation(
    role: str,
    question: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    metrics: list[MetricSnapshot],
) -> str:
    q = question.lower()

    if "csr" in q or "corporate social responsibility" in q or "sustainability" in q:
        texts = {
            "CFO": "CSR must remain budget-bound with measurable ROI and limited margin impact.",
            "CMO": "Authentic CSR can strengthen customer trust and brand preference.",
            "COO": "Operational levers such as waste reduction can support CSR with measurable efficiency gains.",
            "CSO": "CSR can differentiate us if competitors treat it as superficial marketing.",
        }
        return f"Interpretation: {texts[role]}"

    if analysis.assessment == "mixed":
        improved = ", ".join(m.label for m in analysis.improving[:2]) or "some metrics"
        weakened = ", ".join(m.label for m in analysis.deteriorating[:2]) or "other metrics"
        if role == "CFO":
            return (
                f"Interpretation: Performance is mixed — {improved} improved while {weakened} weakened, "
                "so top-line progress is not fully converting to earnings."
            )
        if role == "CMO":
            return (
                f"Interpretation: Mixed signals suggest we should scale only the demand levers with proven efficiency."
            )
        if role == "COO":
            return "Interpretation: Mixed metrics require validating whether operations can support any growth push."
        return "Interpretation: Mixed performance may still create a strategic window if share gains are durable."

    if role == "CFO" and analysis.drivers:
        return f"Interpretation: {analysis.drivers[0]}"
    if role == "CMO":
        cac = next((m for m in metrics if m.key == "cac"), None) or profile.get("cac")
        share = next((m for m in metrics if m.key == "market_share"), None) or profile.get("market_share")
        if cac and share and cac.business_direction == "improved" and share.business_direction == "improved":
            return "Interpretation: The company gained share while improving acquisition efficiency."
        if cac and cac.business_direction == "deteriorated":
            return "Interpretation: Acquisition efficiency is weakening, which limits unfocused spend increases."
    if role == "COO":
        cap = next((m for m in metrics if m.key == "capacity_utilization"), None)
        if cap and cap.current is not None:
            if cap.current >= 85:
                return f"Interpretation: Utilization at {cap.format_value(cap.current)} suggests limited headroom for additional demand."
            return f"Interpretation: Utilization at {cap.format_value(cap.current)} suggests some capacity remains, but throughput must be validated."
    if role == "CSO":
        share = next((m for m in metrics if m.key == "market_share"), None) or profile.get("market_share")
        if share and share.business_direction == "improved":
            return "Interpretation: Share gains may indicate a competitively defensible position if economics hold."

    if analysis.assessment in {"improving", "deteriorating", "stable"}:
        if role == "CFO":
            contradictions = detect_cfo_financial_contradictions(profile, analysis, question)
            if contradictions:
                return cfo_contradiction_interpretation(contradictions, analysis)
            margin = next((m for m in metrics if m.key == "operating_margin"), None) or profile.get("operating_margin")
            cac = next((m for m in metrics if m.key == "cac"), None) or profile.get("cac")
            if margin and cac and margin.available and cac.available:
                return (
                    f"Interpretation: Profitability and acquisition efficiency both moved favorably — "
                    f"operating margin is {margin.format_value(margin.current)} and CAC is "
                    f"{cac.format_value(cac.current)} — so selective growth is financeable if payback holds."
                )
        if role == "CMO":
            share = next((m for m in metrics if m.key == "market_share"), None) or profile.get("market_share")
            customers = next((m for m in metrics if m.key == "customer_count"), None) or profile.get("customer_count")
            if share and customers and share.available:
                return (
                    f"Interpretation: Demand momentum is real — market share reached "
                    f"{share.format_value(share.current)} with customer count at "
                    f"{customers.format_value(customers.current) if customers else 'the current level'}."
                )
        if role == "COO":
            constraints = detect_coo_operational_constraints(profile, analysis, question)
            if constraints:
                return coo_constraint_interpretation(constraints)
            cap = next((m for m in metrics if m.key == "capacity_utilization"), None) or profile.get("capacity_utilization")
            if cap and cap.current is not None:
                return (
                    f"Interpretation: Operations can absorb some incremental volume at "
                    f"{cap.format_value(cap.current)} utilization, but throughput must be validated before a broad push."
                )
        if role == "CSO":
            share = next((m for m in metrics if m.key == "market_share"), None) or profile.get("market_share")
            if share and share.business_direction == "improved":
                return (
                    f"Interpretation: Share gains to {share.format_value(share.current)} may signal durable "
                    "competitive momentum if unit economics and retention hold."
                )
        return f"Interpretation: Uploaded evidence on the question-relevant metrics appears {analysis.assessment}."
    return "Interpretation: Available evidence supports a directional view, but some requested fields may be missing."


def _recommendation(role: str, question: str, profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    q = question.lower()
    if any(
        token in q
        for token in ("working capital", "working-capital", "dso", "days sales outstanding", "cash conversion")
    ):
        dso = profile.get("dso")
        if dso and dso.available:
            direction = dso.business_direction
            if role == "CFO":
                if direction == "improved":
                    return (
                        "Recommendation: maintain collections discipline, validate sustainability of the DSO improvement, "
                        "and monitor receivables aging and cash conversion."
                    )
                return (
                    "Recommendation: tighten collections, segment receivables by aging, and build a working-capital bridge."
                )
            if role == "COO":
                return "Recommendation: ensure billing and fulfillment processes support timely invoicing and collections."
            if role == "CMO":
                return "Recommendation: avoid growth programs that lengthen payment cycles unless unit economics justify it."
            return "Recommendation: treat working-capital efficiency as a strategic enabler of financial flexibility."
    if "marketing" in q and ("increase" in q or "invest" in q or "spend" in q):
        recs = {
            "CFO": "Recommendation: increase marketing only where incremental contribution margin and CAC efficiency are proven.",
            "CMO": "Recommendation: protect and selectively scale high-performing acquisition channels.",
            "COO": "Recommendation: validate throughput and service capacity before increasing demand.",
            "CSO": "Recommendation: invest selectively if share gains appear competitively durable.",
        }
        return recs[role]
    if any(
        phrase in q
        for phrase in ("accelerate growth", "consolidating profitability", "growth next period")
    ) and len(analysis.primary_metrics) >= 2:
        recs = {
            "CFO": (
                "Recommendation: accelerate growth selectively while operating margin and CAC trends remain favorable; "
                "do not pursue consolidation that sacrifices proven unit economics."
            ),
            "CMO": (
                "Recommendation: support measured growth acceleration where market share, customer count, and CAC all improved."
            ),
            "COO": (
                "Recommendation: accelerate growth only if operational capacity can absorb incremental volume; "
                "validate throughput before committing."
            ),
            "CSO": (
                "Recommendation: lean toward selective growth acceleration while share and customer gains appear durable, "
                "subject to margin and acquisition efficiency holding."
            ),
        }
        return recs.get(role, "Recommendation: pursue selective growth acceleration over blanket consolidation.")
    if "profitability" in q and "growth" in q:
        recs = {
            "CFO": "Recommendation: prioritize profitability improvement until EBITDA/margin bridge is understood.",
            "CMO": "Recommendation: pursue selective growth where unit economics are proven.",
            "COO": "Recommendation: resolve operational bottlenecks before accepting aggressive volume targets.",
            "CSO": "Recommendation: choose the path that preserves strategic optionality rather than forcing a binary cut/grow decision.",
        }
        return recs[role]
    if role == "CFO" and analysis.assessment == "mixed":
        return "Recommendation: run a margin/EBITDA bridge before approving broad incremental spend."
    if role == "CMO":
        return "Recommendation: protect high-LTV acquisition and retention while trimming weak campaigns."
    if role == "COO":
        return "Recommendation: improve throughput and cost-to-serve before broad headcount or service cuts."
    return "Recommendation: pursue targeted actions aligned to evidence rather than blanket policy moves."


def _risks(role: str, profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    catalog = {
        "CFO": ["margin compression", "cash pressure", "weak ROI spend"],
        "CMO": ["pipeline gaps", "CAC deterioration", "brand erosion"],
        "COO": ["capacity bottlenecks", "quality defects", "execution slippage"],
        "CSO": ["competitive retaliation", "strategic drift", "temporary vs structural misread"],
    }
    risks = list(catalog.get(role, ["execution risk"]))
    if analysis.assessment == "mixed":
        risks.insert(0, "growth not converting to earnings")
    churn = profile.get("churn")
    if churn and churn.business_direction == "deteriorated":
        risks.append("rising churn")
    return "Risks: " + ", ".join(risks[:3]) + "."


def _round_two(
    role: str,
    question: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    peers: dict[str, str],
) -> str:
    """Round 2: respond naturally to peer arguments with metric-backed agree/disagree."""
    if not peers:
        return _round_one(role, question, profile, analysis)

    lines: list[str] = []
    responded_peers: set[str] = set()
    seen_fragments: set[str] = set()

    priority_peers = _priority_peers_for_role(role, peers)
    for peer_role in priority_peers:
        if peer_role == role or peer_role in responded_peers:
            continue
        peer_text = peers.get(peer_role, "")
        if not peer_text:
            continue
        line = _debate_line(role, peer_role, _peer_theme(peer_text), profile, analysis, peer_text)
        if line:
            fragment = line[:72].lower()
            if fragment not in seen_fragments:
                lines.append(line)
                seen_fragments.add(fragment)
            responded_peers.add(peer_role)
        if len(lines) >= 1:
            break

    if not lines:
        peer_role = next(iter(peers))
        peer_text = peers[peer_role]
        claim = extract_peer_claim(peer_text)
        if claim and not claim.lower().startswith(("revenue", "market share", "ebitda", "cac", "gross")):
            lines.append(
                f"The {peer_role} raised a valid point: {claim}. "
                f"I refine my view from a {PERSONA_LENS[role].split(',')[0]} standpoint."
            )
        else:
            lines.append(
                f"I have reviewed the {peer_role}'s analysis and update my recommendation below "
                f"based on the uploaded metrics."
            )

    lines.append(_round_two_closer(role, question, profile, analysis))
    return " ".join(lines)


def _priority_peers_for_role(role: str, peers: dict[str, str]) -> list[str]:
    """Order peers so each executive debates the most relevant counterpart first."""
    order_map = {
        "CFO": ("CMO", "COO", "CSO"),
        "CMO": ("CFO", "COO", "CSO"),
        "COO": ("CMO", "CFO", "CSO"),
        "CSO": ("CFO", "CMO", "COO"),
    }
    ordered = [p for p in order_map.get(role, ROLES) if p in peers]
    for peer in peers:
        if peer not in ordered:
            ordered.append(peer)
    return ordered


def _peer_theme(text: str) -> str:
    lower = text.lower()
    if "protect" in lower and ("marketing" in lower or "acquisition" in lower or "demand" in lower):
        return "protecting efficient acquisition"
    if "cut" in lower or "reduce" in lower or "austerity" in lower or "discipline" in lower:
        return "financial discipline"
    if "capacity" in lower or "throughput" in lower or "operational" in lower:
        return "operational constraints"
    if "share" in lower or "competitive" in lower or "strategic" in lower:
        return "competitive opportunity"
    if "roi" in lower or "margin" in lower or "ebitda" in lower or "cash" in lower:
        return "profitability validation"
    if "recommendation:" in lower:
        rec = lower.split("recommendation:")[-1][:80].strip()
        return rec or "prior recommendation"
    return "prior analysis"


def _debate_line(
    role: str,
    peer_role: str,
    theme: str,
    profile: CompanyDataProfile,
    analysis: QuestionAnalysis,
    peer_text: str = "",
) -> str | None:
    cac = profile.get("cac")
    share = profile.get("market_share")
    cap = profile.get("capacity_utilization")
    ltv = profile.get("ltv")

    if role == "CFO":
        if peer_role == "CMO" and theme in {"protecting efficient acquisition", "competitive opportunity"}:
            if cac and cac.available:
                if cac.business_direction == "improved":
                    return (
                        f"The CMO is right that CAC improved from {cac.format_value(cac.previous)} to "
                        f"{cac.format_value(cac.current)}"
                        + (f" and share moved to {share.format_value(share.current)}." if share else ".")
                        + " However, I would only scale those channels after confirming contribution margin and payback."
                    )
                if cac.business_direction == "deteriorated":
                    return (
                        f"While I share the CMO's growth instinct, CAC actually deteriorated from "
                        f"{cac.format_value(cac.previous)} to {cac.format_value(cac.current)}"
                        + (f" and share is {share.format_value(share.current)}." if share else ".")
                        + " I would audit channel ROI before approving any marketing increase."
                    )
                return (
                    f"The CMO makes a fair case for demand investment, but I would not approve a broad marketing increase "
                    "without contribution-margin evidence."
                )
            return (
                "The CMO makes a fair case for demand investment, but I would not approve a broad marketing increase "
                "without contribution-margin evidence."
            )
        if peer_role == "COO" and theme == "operational constraints":
            cap_note = f" Utilization is already {cap.format_value(cap.current)}." if cap and cap.current else ""
            return (
                f"The COO is right that capacity must gate any growth plan.{cap_note} "
                "Financial approval depends on executable volume, not demand targets alone."
            )
        if peer_role == "CSO" and theme == "competitive opportunity":
            return (
                "I agree there may be a strategic window, but investment should remain staged until "
                "unit economics and payback are validated."
            )

    if role == "CMO":
        if peer_role == "CFO" and theme == "financial discipline":
            if cac and cac.business_direction == "improved":
                ltv_note = ""
                if ltv and ltv.business_direction == "improved":
                    ltv_note = f" LTV is also rising to {ltv.format_value(ltv.current)}."
                return (
                    f"I agree with the CFO on unit economics, but broad caution should not stop us from scaling "
                    f"channels where CAC is falling ({cac.format_value(cac.previous)} -> {cac.format_value(cac.current)})."
                    f"{ltv_note} I recommend selective expansion rather than a blanket increase."
                )
            return (
                "I respect the CFO's financial discipline, but indiscriminate cuts could weaken demand "
                "in segments where conversion remains strong."
            )
        if peer_role == "COO" and theme == "operational constraints":
            return (
                "The COO is right that demand plans must fit capacity, but that should not block investment "
                "in channels where acquisition efficiency is improving."
            )

    if role == "COO":
        cap = profile.get("capacity_utilization")
        cap_note = ""
        if cap and cap.current is not None:
            cap_note = f" Utilization is already {cap.format_value(cap.current)},"
        if peer_role == "CMO":
            return (
                f"The growth case is attractive, but{cap_note} I would validate throughput and service "
                "capacity before increasing demand generation."
            )
        if peer_role == "CFO":
            return (
                f"I align with the CFO that spend must be gated by execution capacity.{cap_note} "
                "Financial approval should follow operational feasibility, not precede it."
            )
        if peer_role == "CSO":
            return (
                "Strategic momentum matters, but scaling demand without throughput validation "
                "would raise delivery risk and cost-to-serve."
            )

    if role == "CSO":
        if share and share.business_direction == "improved":
            if peer_role == "CFO":
                return (
                    f"The {share.format_value(share.previous)} to {share.format_value(share.current)} share gain "
                    "creates a strategic opportunity, but we should determine whether competitors can replicate "
                    "the acquisition gains before committing to aggressive expansion."
                )
            if peer_role == "CMO" and theme == "protecting efficient acquisition":
                return (
                    "I support selective investment if competitors cannot easily replicate the acquisition "
                    "efficiency gains shown in the uploaded data."
                )
        if peer_role == "CFO" and theme == "profitability validation":
            return (
                "The CFO's financial caution is warranted given margin pressure in the uploaded data, "
                "but we should not forfeit strategic gains if unit economics remain acceptable."
            )
        if peer_role == "CMO":
            return (
                "The CMO's growth case has merit, but we need to confirm whether share and acquisition gains "
                "are structurally durable before committing to aggressive expansion."
            )

    if role == "CFO" and peer_role == "CMO" and theme == "prior recommendation":
        return (
            "The CMO's growth priorities need to clear ROI and payback thresholds before I would approve "
            "material incremental spend."
        )

    return None


def _round_two_closer(role: str, question: str, profile: CompanyDataProfile, analysis: QuestionAnalysis) -> str:
    rec = _recommendation(role, question, profile, analysis).replace("Recommendation:", "Updated recommendation:")
    return rec


def mock_synthesis_json(*, user_prompt: str) -> dict[str, Any]:
    """Deterministic board synthesis grounded in question analysis and uploaded metrics."""
    question, _, _, profile, analysis = _resolve_context(user_prompt)
    turn = get_board_turn()
    discussion = turn.discussion if turn else []

    if not profile.has_upload:
        return {
            "recommendation": "Upload company metrics before the board can issue a data-grounded decision.",
            "key_risks": ["Deciding without internal metrics"],
            "disagreements": [],
            "actions": ["Upload CSV/JSON company data", "Reconvene the board"],
            "metrics": ["Revenue", "EBITDA", "Operating Margin", "CAC", "Market Share"],
            "confidence": "Low",
        }

    recommendation = build_direct_recommendation(question, profile, analysis, discussion)
    disagreements = build_synthesis_disagreements(discussion, profile, analysis)
    actions = build_synthesis_actions(question, profile, analysis)
    if analysis.primary_metrics:
        metrics = [m.label for m in analysis.primary_metrics]
    else:
        metrics = [m.label for m in analysis.relevant_metrics[:6]] or profile.available_metric_names()[:6]
    confidence = compute_synthesis_confidence(question, profile, analysis)

    return {
        "recommendation": recommendation,
        "key_risks": _synthesis_risks(profile, analysis),
        "disagreements": disagreements,
        "actions": actions,
        "metrics": metrics,
        "confidence": confidence,
    }


def _synthesis_risks(profile: CompanyDataProfile, analysis: QuestionAnalysis) -> list[str]:
    risks: list[str] = []
    if analysis.assessment == "mixed":
        risks.append("Conflicting metric trends creating decision risk")
    for metric in analysis.deteriorating[:2]:
        risks.append(
            f"{metric.label} deterioration ({metric.format_value(metric.previous)} -> {metric.format_value(metric.current)})"
        )
    cap = next((m for m in analysis.relevant_metrics if m.key == "capacity_utilization"), None)
    if cap and cap.current is not None and cap.current >= 75:
        risks.append(f"Capacity constraint at {cap.format_value(cap.current)} utilization")
    churn = next((m for m in analysis.relevant_metrics if m.key == "churn"), None)
    if churn and churn.business_direction == "deteriorated":
        risks.append("Rising churn eroding customer lifetime value")
    if not risks:
        risks = ["Acting on incomplete evidence"]
    return risks[:4]


def mock_chat_json(*, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    return mock_synthesis_json(user_prompt=user_prompt)
