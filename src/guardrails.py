"""
Zero-Hallucination Guardrails for Multi-Plant Order Allocation System.

This module verifies that every number in an LLM-generated executive brief
matches a number from the solver output. If a mismatch is found (potential
hallucination), the LLM text is replaced with a safe deterministic template.

This is critical because the LLM should NEVER invent numbers — all figures
must come directly from the PuLP solver output.

Pipeline:
    1. Extract all numbers from the brief text using regex
    2. Extract all valid reference numbers from the solver output
    3. Compare with a 0.5% tolerance for rounding
    4. If any unverified numbers found, fall back to deterministic template
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Numbers in this range are likely years or section numbers, not metrics
YEAR_RANGE = range(2020, 2035)
# Small integers that are likely list indices or section numbers
LIKELY_INDICES = {0, 1, 2, 3}
# Tolerance for number comparison (0.5% to handle rounding)
TOLERANCE = 0.005


def extract_numbers_from_text(text: str) -> set[float]:
    """Extract all numeric values from a text string.

    Uses regex to find numbers in various formats (with commas, decimals, etc.)
    and filters out obvious non-metric values like years and list indices.

    Args:
        text: The text to extract numbers from (typically an LLM-generated brief).

    Returns:
        Set of extracted float values that are likely metric values.
    """
    # Match numbers with optional commas and decimals
    pattern = r'[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.?\d*'
    matches = re.findall(pattern, text)

    numbers: set[float] = set()
    for match in matches:
        try:
            # Remove commas before converting to float
            value = float(match.replace(",", ""))

            # Filter out likely years (2020-2034)
            if int(value) in YEAR_RANGE and value == int(value):
                continue

            # Filter out small integers that are likely indices/section numbers
            # Only filter if they don't appear with units like "2 days"
            if value in LIKELY_INDICES:
                # Check if the number appears with a unit suffix in the text
                idx = text.find(match)
                if idx >= 0:
                    after = text[idx + len(match):idx + len(match) + 10].strip().lower()
                    if not any(unit in after for unit in ["day", "order", "plant", "unit", "%", "tonne", "kg"]):
                        continue

            numbers.add(value)
        except ValueError:
            continue

    return numbers


def extract_numbers_from_solver_output(solver_result: dict) -> set[float]:
    """Recursively extract all numeric values from the solver result dictionary.

    Builds a comprehensive set of valid reference numbers including common
    derived values (e.g., cost in millions, cost in thousands) that the LLM
    might reasonably use in a brief.

    Args:
        solver_result: The complete solver output dictionary.

    Returns:
        Set of all valid reference numbers.
    """
    numbers: set[float] = set()

    def _walk(obj: object) -> None:
        """Recursively walk a nested dict/list and collect all numeric values."""
        if isinstance(obj, (int, float)):
            val = float(obj)
            numbers.add(val)
            numbers.add(round(val, 2))
            numbers.add(round(val, 1))
            numbers.add(round(val, 0))
            # Common derived values for executive briefs
            if val > 1000:
                numbers.add(round(val / 1000, 2))   # Thousands (e.g., "1.84K")
                numbers.add(round(val / 1000, 1))
            if val > 1000000:
                numbers.add(round(val / 1000000, 2))  # Millions (e.g., "1.84M")
                numbers.add(round(val / 1000000, 1))
            # Percentage conversions for utilization values
            if 0 <= val <= 1:
                numbers.add(round(val * 100, 2))  # e.g., 0.85 -> 85%
                numbers.add(round(val * 100, 1))
                numbers.add(round(val * 100, 0))
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(solver_result)
    return numbers


def verify_brief(brief_text: str, solver_result: dict) -> tuple[bool, list[float]]:
    """Verify that all numbers in the brief text come from the solver output.

    For each number found in the brief, checks if it exists in the reference
    set (with tolerance for rounding).

    Args:
        brief_text: The LLM-generated executive brief text.
        solver_result: The complete solver output dictionary.

    Returns:
        Tuple of (all_verified: bool, unverified_numbers: list[float]).
    """
    brief_numbers = extract_numbers_from_text(brief_text)
    reference_numbers = extract_numbers_from_solver_output(solver_result)

    unverified: list[float] = []

    for num in brief_numbers:
        # Check if this number (or a close match) exists in the reference set
        found = False
        for ref in reference_numbers:
            if abs(ref) < 1e-9:
                if abs(num) < 1e-9:
                    found = True
                    break
            elif abs(num - ref) / max(abs(ref), 1e-9) < TOLERANCE:
                found = True
                break

        if not found:
            unverified.append(num)

    all_verified = len(unverified) == 0
    return all_verified, unverified


def generate_deterministic_brief(solver_result: dict) -> str:
    """Generate a SAFE fallback brief using pure Python f-strings.

    This function uses NO LLM involvement — it's a pure template-based
    summary that can never hallucinate because all values come directly
    from the solver result dictionary.

    Args:
        solver_result: The complete solver output dictionary.

    Returns:
        A deterministic executive brief string.
    """
    kpis = solver_result.get("kpis", {})
    answer_type = solver_result.get("answer_type", "allocation")

    total_cost = kpis.get("total_cost", 0)
    total_carbon_t = kpis.get("total_carbon_t", 0)
    late_orders = kpis.get("late_orders", 0)
    utilisation = kpis.get("plant_utilisation", {})

    # Build utilization string for all plants
    util_parts = []
    for plant_id in sorted(utilisation.keys()):
        pct = utilisation[plant_id] * 100
        util_parts.append(f"Plant {plant_id} at {pct:.0f}%")
    util_str = ", ".join(util_parts) if util_parts else "No plant data"

    # Calculate on-time rate
    allocation = solver_result.get("allocation", [])
    total_orders = len(allocation)
    on_time_count = sum(1 for a in allocation if a.get("on_time", False))
    on_time_rate = (on_time_count / total_orders * 100) if total_orders > 0 else 0

    brief = (
        f"Allocation Summary: Total landed cost is ${total_cost:,.2f}. "
        f"Total carbon emissions are {total_carbon_t:.1f} tonnes CO2e. "
        f"{late_orders} order(s) are projected to arrive late "
        f"({on_time_rate:.1f}% on-time delivery rate). "
        f"Plant utilization: {util_str}."
    )

    # Add professional capacity constraint notice if applicable
    unfulfilled = solver_result.get("unfulfilled_orders", [])
    if answer_type == "infeasible" or unfulfilled:
        brief += (
            f" Capacity Notice: Available manufacturing capacity is fully saturated; "
            f"{len(unfulfilled)} order(s) have been deferred to protect line throughput and maintain delivery SLAs."
        )

    return brief


# =============================================================================
# GENERAL LLM INPUT GUARDRAILS (Prompt Injection, Domain, Safety)
# =============================================================================

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|prior|system)\s+(instructions|directives)",
    r"bypass\s+(all\s+)?(guidelines|rules|filters|constraints)",
    r"act\s+as\s+(an?\s+)?(unrestricted|dan|jailbreak|unfiltered)",
    r"system\s*prompt\s*override",
    r"you\s+are\s+now\s+in\s+developer\s+mode",
]

DOMAIN_KEYWORDS = [
    "allocat", "plan", "assign", "order", "plant", "facilit", "capacit", "cost", "carbon",
    "tradeoff", "trade-off", "pareto", "replan", "re-plan", "disrupt", "outage", "schedul",
    "manufactur", "landed", "tariff", "duty", "transit", "delay", "sla", "due date",
    "berlin", "london", "tokyo", "paris", "sydney", "chicago", "mumbai", "toronto", "dubai",
    "sao_paulo", "shanghai", "mexico_city", "cheapest", "greenest", "emission", "co2", "why",
    "what if", "what-if", "compare", "brief", "summary", "leadership", "management",
    "solve", "run", "optimize"
]


def screen_prompt_injection(query: str) -> tuple[bool, Optional[str]]:
    """Screen for adversarial jailbreak and prompt injection attempts."""
    q_lower = query.lower()
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, q_lower):
            logger.warning(f"Guardrail Alert: Prompt injection pattern matched: '{pattern}'")
            return False, "Input rejected: Adversarial prompt injection or system override detected."
    return True, None


def screen_domain_relevance(query: str) -> tuple[bool, Optional[str]]:
    """Verify that user query pertains to supply chain and order allocation domain."""
    q_lower = query.lower().strip()
    if not q_lower:
        return True, None

    # Intercept ambiguous/incomplete fragments that lack an actionable predicate
    ambiguous_fragments = {"plan b", "plan a", "plan c", "plant a", "plant b", "plant c", "plant", "orders", "order"}
    if q_lower in ambiguous_fragments:
        target_name = "Plant B" if "b" in q_lower else ("Plant A" if "a" in q_lower else ("Plant C" if "c" in q_lower else "a specific facility"))
        return False, (
            f"Insufficient information: Ambiguous directive '{query}'. Did you mean {target_name}? "
            f"Please provide an actionable directive (e.g., '{target_name} loses 30% capacity due to maintenance' or "
            f"'Allocate all orders prioritizing {target_name}')."
        )

    has_domain_term = any(term in q_lower for term in DOMAIN_KEYWORDS)
    has_order_pattern = bool(re.search(r'o-\d+', q_lower))
    has_plant_pattern = bool(re.search(r'\bplant\s+[a-c]\b', q_lower))

    if has_domain_term or has_order_pattern or has_plant_pattern:
        return True, None

    return False, (
        "Insufficient information / Out of domain: Query does not contain recognized "
        "manufacturing order allocation, facility capacity, or logistics directives."
    )


def validate_input_guardrail(query: str) -> tuple[bool, Optional[str]]:
    """Comprehensive input guardrail combining prompt injection and domain screening."""
    # 1. Prompt Injection check
    safe_inject, err_inject = screen_prompt_injection(query)
    if not safe_inject:
        return False, err_inject

    # 2. Domain Relevance check
    safe_domain, err_domain = screen_domain_relevance(query)
    if not safe_domain:
        return False, err_domain

    return True, None


def verify_entity_hallucination(brief_text: str, valid_plants: set[str] = {"A", "B", "C"}) -> tuple[bool, list[str]]:
    """Screen for hallucinated facilities (e.g. Plant D, Plant Z) not present in database."""
    matches = re.findall(r"\bPlant\s+([A-Z])\b", brief_text)
    hallucinated = [p for p in matches if p not in valid_plants]
    return len(hallucinated) == 0, hallucinated


def guardrail_check(brief_text: str, solver_result: dict) -> str:
    """Run comprehensive zero-hallucination guardrails on an LLM-generated brief.

    Checks:
        1. Numerical fidelity against PuLP solver output within 0.5% tolerance.
        2. Entity verification (no hallucinated plants outside A, B, C).

    If any unverified numbers or entities are found, logs a warning and returns
    a safe deterministic replacement brief.
    """
    # 1. Numerical fidelity
    all_num_verified, unverified_nums = verify_brief(brief_text, solver_result)

    # 2. Entity hallucination check
    entities_verified, bad_entities = verify_entity_hallucination(brief_text)

    if all_num_verified and entities_verified:
        logger.info("Guardrail PASSED: All metrics and entities verified against solver output.")
        return brief_text
    else:
        logger.warning(
            f"Guardrail FAILED: Unverified numbers: {unverified_nums}, "
            f"Hallucinated entities: {bad_entities}. Replacing with deterministic brief."
        )
        return generate_deterministic_brief(solver_result)
