"""
Executive Brief Writer Agent for Multi-Plant Order Allocation System.

This module formats solver output into concise leadership summaries.
If MOCK_LLM is enabled (default), it immediately invokes the deterministic
template builder from guardrails to guarantee 100% zero-hallucination.
When MOCK_LLM is disabled and a GEMINI_API_KEY is supplied, it interacts with
Google Gemini (via langchain-google-genai) with strict prompting instructions.
"""

import json
import logging
from typing import Optional

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

from src.config import settings
from src.guardrails import generate_deterministic_brief

logger = logging.getLogger(__name__)


def call_local_llama(prompt: str) -> Optional[str]:
    """Call a running llama-server instance via its OpenAI-compatible /v1/chat/completions API.

    Args:
        prompt: Prompt text to generate from.

    Returns:
        Generated text string or None if server unreachable.
    """
    url = f"{settings.LOCAL_LLM_URL.rstrip('/')}/v1/chat/completions"
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 800,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return content.strip()
    except Exception as err:
        logger.warning(f"Local llama-server call to {url} failed: {err}. Falling back to safe deterministic output.")
        return None


def get_llm():
    """Initialize and return LLM client if configured and mock mode is disabled.

    Returns:
        ChatGoogleGenerativeAI or None if mock mode is active.
    """
    if settings.MOCK_LLM:
        return None

    if settings.LLM_PROVIDER.lower() in ["local", "llama", "llama_cpp", "llama-server"]:
        return "local_llama"

    if settings.LLM_PROVIDER.lower() == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            if not settings.GEMINI_API_KEY:
                logger.warning("GEMINI_API_KEY not configured. Falling back to mock LLM mode.")
                return None

            return ChatGoogleGenerativeAI(
                model=settings.LLM_MODEL,
                google_api_key=settings.GEMINI_API_KEY,
                temperature=0.1,
            )
        except Exception as err:
            logger.error(f"Failed to initialize ChatGoogleGenerativeAI: {err}")
            return None

    return None


def generate_brief(solver_result: dict, user_query: str) -> str:
    """Generate an executive summary brief from solver output.

    Args:
        solver_result: The complete dictionary of results from PuLP solver.
        user_query: The incoming natural language user question/instruction.

    Returns:
        String containing the executive summary brief.
    """
    llm = get_llm()
    if llm is None:
        return generate_deterministic_brief(solver_result)

    prompt = f"""SYSTEM: You are a supply chain analyst writing an executive brief for senior leadership.
You MUST use ONLY the numbers provided below. Do NOT compute, estimate, or invent any numbers.
Every figure in your brief must come directly from the data below.

SOLVER OUTPUT DATA:
{json.dumps(solver_result, indent=2)}

USER REQUEST: {user_query}

Write a concise 1-paragraph executive summary covering:
1. Total landed cost and total carbon emissions
2. Number of late orders and overall on-time delivery rate
3. Plant utilization percentages
4. If this is a re-plan, what changed from the previous plan
5. Key trade-off: what would it cost to reduce carbon

Use only the numbers above. Do not add any numbers not present in the data."""

    if llm == "local_llama":
        local_text = call_local_llama(prompt)
        if local_text:
            return local_text
        return generate_deterministic_brief(solver_result)

    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        return text.strip()
    except Exception as e:
        logger.error(f"LLM call failed: {e}. Falling back to deterministic brief.")
        return generate_deterministic_brief(solver_result)


def generate_explanation(solver_result: dict, order_id: str, counterfactuals: dict) -> str:
    """Explain counterfactual choices for a specific order.

    Args:
        solver_result: Complete solver output dictionary.
        order_id: The specific order identifier.
        counterfactuals: Comparative metrics across plants.

    Returns:
        Plain English explanation for why the order was allocated to its selected plant.
    """
    chosen_plant = counterfactuals.get("chosen_plant", "Unknown")
    chosen_cost = counterfactuals.get("chosen_cost", 0.0)
    chosen_carbon = counterfactuals.get("chosen_carbon", 0.0)

    llm = get_llm()
    if llm is None:
        alt_summaries = []
        for pid, alt in counterfactuals.get("alternatives", {}).items():
            if pid != chosen_plant:
                reason = alt.get("reason", "")
                alt_summaries.append(f"{pid}: {reason}")
        alts_str = "; ".join(alt_summaries) if alt_summaries else "No alternative data."
        return (
            f"Order {order_id} was assigned to Plant {chosen_plant} at cost ${chosen_cost:,.2f} "
            f"and {chosen_carbon:,.1f} kg CO2e. Alternatives evaluation: {alts_str}."
        )

    prompt = f"""Explain why order {order_id} was assigned to Plant {chosen_plant}.
Here are the alternatives:
{json.dumps(counterfactuals, indent=2)}

Use ONLY these numbers. Mention cost, carbon, transit time, and capacity."""

    if llm == "local_llama":
        local_text = call_local_llama(prompt)
        if local_text:
            return local_text

    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        return text.strip()
    except Exception as e:
        logger.error(f"LLM explanation call failed: {e}. Falling back to deterministic summary.")
        return (
            f"Order {order_id} assigned to Plant {chosen_plant} (Cost: ${chosen_cost:,.2f}, "
            f"Carbon: {chosen_carbon:,.1f} kg CO2e)."
        )
