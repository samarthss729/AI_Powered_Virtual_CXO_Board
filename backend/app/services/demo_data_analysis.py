"""Backward-compatible exports; analysis lives in data_service."""

from app.services.data_service import (  # noqa: F401
    CompanyDataProfile as FinancialAnalysis,
    MetricSnapshot as SeriesPoint,
    build_company_profile,
    split_sentences,
)

# Legacy helpers used by older tests
def analyze_uploaded_data(user_prompt: str):
    from app.services.demo_responses import _profile_from_prompt
    from app.services.data_service import analyze_question

    profile = _profile_from_prompt(user_prompt)
    question = "analysis"
    if "CEO question:" in user_prompt:
        import re

        match = re.search(
            r"CEO question:\s*\n(.*?)\n\nCompany data context:",
            user_prompt,
            flags=re.DOTALL,
        )
        if match:
            question = match.group(1).strip()
    analysis = analyze_question(profile, question)
    profile.has_upload = profile.has_upload  # keep interface
    return profile


def extract_data_payload(user_prompt: str):
    from app.services.demo_responses import _profile_from_prompt
    from app.services.data_service import build_structured_context_block
    import json

    profile = _profile_from_prompt(user_prompt)
    if not profile.has_upload:
        return None
    return json.loads(build_structured_context_block(profile))


def insufficient_data_phrase(metric: str = "financial") -> str:
    return (
        f"The uploaded dataset does not contain enough {metric} fields to answer this quantitatively."
    )
