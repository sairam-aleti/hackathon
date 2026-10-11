"""
LangGraph Orchestration Pipeline for Multi-Plant Order Allocation System.

Defines the 5-node StateGraph pipeline:
    1. parse_intent: Analyzes user query or structured payload to determine workflow intent.
    2. run_solver: Invokes PuLP solver with appropriate scenario/weights.
    3. validate_output: Asserts data integrity and solver constraints satisfaction.
    4. generate_brief: Generates executive brief (using LLM or deterministic template).
    5. guardrail_check: Enforces zero-hallucination verification and records run trace.
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.brief_writer import generate_brief, generate_explanation
from src.config import settings
from src.database import get_connection
from src.guardrails import guardrail_check, validate_input_guardrail
from src.solver import (
    explain_order_choice,
    generate_pareto_frontier,
    solve_allocation,
)
from src.validator import validate_data

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    """Execution state passed through the LangGraph pipeline."""

    user_query: str
    weights: Optional[dict]
    scenario: Optional[dict]
    intent: Optional[str]
    solver_result: Optional[dict]
    baseline_allocation: Optional[dict]
    brief_text: Optional[str]
    final_response: Optional[dict]
    trace_steps: list[dict]
    run_id: str


def _record_trace_step(state: GraphState, step_name: str, input_data: dict, output_data: dict, duration_ms: float) -> None:
    """Helper to append structured step execution metrics to the trace."""
    step = {
        "step_name": step_name,
        "input_data": input_data,
        "output_data": output_data,
        "duration_ms": round(duration_ms, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
    state["trace_steps"].append(step)


def parse_intent(state: GraphState) -> GraphState:
    """Node 1: Extract intent and parameters from natural language or query."""
    t0 = time.time()
    query = state.get("user_query", "") or ""
    q_lower = query.lower().strip()

    scenario = state.get("scenario") or None
    weights = state.get("weights") or None
    intent = "allocation"

    # General LLM Input Guardrails (Prompt injection, safety, domain relevance)
    is_valid, rejection_reason = validate_input_guardrail(query)
    if not is_valid:
        intent = "clarification_needed"
        state["refusal_reason"] = rejection_reason
    elif "plant" in q_lower and any(w in q_lower for w in ["loses", "lost", "capacity", "drop", "down", "disrupt"]):
        intent = "capacity_replan"
        if not scenario:
            # Extract plant letter
            plant_match = re.search(r'plant\s+([a-c])', q_lower)
            pct_match = re.search(r'(\d+)%', q_lower)
            plant_id = plant_match.group(1).upper() if plant_match else "B"
            pct = float(pct_match.group(1)) / 100.0 if pct_match else 0.30
            scenario = {"plant_id": plant_id, "capacity_reduction_pct": pct}
    elif any(w in q_lower for w in ["compare", "what if", "what-if", "scenario"]):
        intent = "scenario"
    elif any(w in q_lower for w in ["brief", "leadership", "management", "summary"]):
        intent = "brief"
    elif "why" in q_lower and "order" in q_lower:
        intent = "explain"
    elif any(w in q_lower for w in ["cheapest", "cost only", "cost-only"]):
        intent = "cheapest_plan"
        if not weights:
            weights = {"cost": 1.0, "carbon": 0.0, "lateness": 0.0}
    elif any(w in q_lower for w in ["carbon cut", "carbon reduc", "greenest"]):
        intent = "carbon_tradeoff"
        if not weights:
            weights = {"cost": 0.0, "carbon": 1.0, "lateness": 0.0}

    state["intent"] = intent
    state["scenario"] = scenario
    state["weights"] = weights

    duration_ms = (time.time() - t0) * 1000
    _record_trace_step(
        state,
        "parse_intent",
        {"query": query},
        {"intent": intent, "scenario": scenario, "weights": weights},
        duration_ms,
    )
    return state


def run_solver(state: GraphState) -> GraphState:
    """Node 2: Deterministic PuLP linear programming optimization."""
    t0 = time.time()
    intent = state.get("intent", "allocation")

    # If query is irrelevant or out-of-domain, skip optimization and request clarification
    if intent == "clarification_needed":
        state["solver_result"] = {
            "allocation": [],
            "kpis": None,
            "tradeoff": [],
            "weights_used": state.get("weights") or {},
            "answer_type": "clarification_needed",
            "summary": state.get("refusal_reason") or (
                "Insufficient information: Cannot assist with this query. The query does not contain recognized "
                "supply chain, plant allocation, or operational parameters. Please provide relevant "
                "operational directives (e.g., 'Allocate all orders balancing cost and carbon', 'Plant B capacity drop 30%', "
                "or 'Explain order O-001')."
            ),
            "assumptions": [],
            "limitations": ["Query was out of domain or lacked required supply chain parameters."],
            "unfulfilled_orders": [],
        }
        duration_ms = (time.time() - t0) * 1000
        _record_trace_step(
            state,
            "run_solver",
            {"query": state.get("user_query")},
            {"status": "skipped_irrelevant_query"},
            duration_ms,
        )
        return state

    conn = get_connection()
    try:
        weights = state.get("weights")
        scenario = state.get("scenario")
        baseline = state.get("baseline_allocation")

        # Solve allocation
        solver_res = solve_allocation(
            conn=conn,
            weights=weights,
            scenario=scenario,
            baseline_allocation=baseline,
        )

        # Generate Pareto frontier for tradeoff analysis
        tradeoff_pts = generate_pareto_frontier(conn=conn, scenario=scenario, num_points=11)
        solver_res["tradeoff"] = tradeoff_pts

        # Always compute counterfactuals for either target order in query or default first order
        order_match = re.search(r'o-\d+', state.get("user_query", "").lower())
        target_order = order_match.group(0).upper() if order_match else None
        if not target_order and solver_res.get("allocation"):
            target_order = solver_res["allocation"][0]["order_id"]
        if not target_order:
            target_order = "O-001"
        solver_res["counterfactuals"] = explain_order_choice(conn, target_order, solver_res)

        state["solver_result"] = solver_res
    finally:
        conn.close()

    duration_ms = (time.time() - t0) * 1000
    kpis = state["solver_result"].get("kpis", {}) or {}
    _record_trace_step(
        state,
        "run_solver",
        {"weights": state.get("weights"), "scenario": state.get("scenario")},
        {"total_cost": kpis.get("total_cost"), "total_carbon_t": kpis.get("total_carbon_t"), "late_orders": kpis.get("late_orders")},
        duration_ms,
    )
    return state


def validate_output(state: GraphState) -> GraphState:
    """Node 3: Validate database integrity and verify solver output limits."""
    t0 = time.time()
    if state.get("intent") == "clarification_needed":
        return state

    conn = get_connection()
    try:
        val_data = validate_data(conn)
    finally:
        conn.close()

    solver_res = state.get("solver_result") or {}
    kpis = solver_res.get("kpis", {}) or {}
    plant_util = kpis.get("plant_utilisation", {})

    capacity_ok = all(util <= 1.0001 for util in plant_util.values())
    eligibility_ok = val_data.get("valid", True)

    validator_result = {
        "capacity_ok": capacity_ok,
        "eligibility_ok": eligibility_ok,
    }
    solver_res["validator"] = validator_result
    state["solver_result"] = solver_res

    duration_ms = (time.time() - t0) * 1000
    _record_trace_step(
        state,
        "validate_output",
        {"allocation_count": len(solver_res.get("allocation", []))},
        validator_result,
        duration_ms,
    )
    return state


def generate_brief_node(state: GraphState) -> GraphState:
    """Node 4: Synthesize plain English summary from numerical solver output."""
    t0 = time.time()
    solver_res = state.get("solver_result") or {}
    query = state.get("user_query", "")

    if state.get("intent") == "clarification_needed":
        brief_text = solver_res.get("summary", "Insufficient query details.")
    elif state.get("intent") == "explain" and solver_res.get("counterfactuals"):
        cf = solver_res["counterfactuals"]
        target_oid = cf.get("order_id", "O-001")
        brief_text = generate_explanation(solver_res, target_oid, cf)
    else:
        brief_text = generate_brief(solver_res, query)

    state["brief_text"] = brief_text

    duration_ms = (time.time() - t0) * 1000
    _record_trace_step(
        state,
        "generate_brief",
        {"intent": state.get("intent")},
        {"brief_length": len(brief_text)},
        duration_ms,
    )
    return state


def guardrail_check_node(state: GraphState) -> GraphState:
    """Node 5: Zero-hallucination interceptor and audit trace persistence."""
    t0 = time.time()
    solver_res = state.get("solver_result") or {}
    raw_brief = state.get("brief_text") or ""

    if state.get("intent") == "clarification_needed":
        verified_summary = raw_brief
        answer_type = "clarification_needed"
    else:
        verified_summary = guardrail_check(raw_brief, solver_res)
        answer_type = solver_res.get("answer_type", "allocation")
        if state.get("intent") == "brief":
            answer_type = "brief"
        elif state.get("intent") in ["scenario", "capacity_replan"]:
            answer_type = "scenario"

    final_resp = {
        "run_id": state["run_id"],
        "answer_type": answer_type,
        "summary": verified_summary,
        "allocation": solver_res.get("allocation", []),
        "kpis": solver_res.get("kpis"),
        "tradeoff": solver_res.get("tradeoff", []),
        "weights_used": solver_res.get("weights_used", {}),
        "validator": solver_res.get("validator"),
        "assumptions": solver_res.get("assumptions", []),
        "limitations": solver_res.get("limitations", []),
        "unfulfilled_orders": solver_res.get("unfulfilled_orders", []),
        "counterfactuals": solver_res.get("counterfactuals"),
    }
    state["final_response"] = final_resp

    # Persist run to SQLite runs table for auditability
    conn = get_connection()
    try:
        now_iso = datetime.utcnow().isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO runs (run_id, request_text, response_json, created_at, trace_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                state["run_id"],
                state.get("user_query", ""),
                json.dumps(final_resp),
                now_iso,
                json.dumps({
                    "run_id": state["run_id"],
                    "steps": state["trace_steps"],
                    "total_duration_ms": sum(s["duration_ms"] for s in state["trace_steps"]),
                    "llm_calls": 0 if settings.MOCK_LLM else 1,
                    "llm_tokens": 0,
                }),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to persist run {state['run_id']}: {e}")
    finally:
        conn.close()

    return state


# Build and compile LangGraph StateGraph
workflow = StateGraph(GraphState)
workflow.add_node("parse_intent", parse_intent)
workflow.add_node("run_solver", run_solver)
workflow.add_node("validate_output", validate_output)
workflow.add_node("generate_brief", generate_brief_node)
workflow.add_node("guardrail_check", guardrail_check_node)

workflow.set_entry_point("parse_intent")
workflow.add_edge("parse_intent", "run_solver")
workflow.add_edge("run_solver", "validate_output")
workflow.add_edge("validate_output", "generate_brief")
workflow.add_edge("generate_brief", "guardrail_check")
workflow.add_edge("guardrail_check", END)

app = workflow.compile()


def run_workflow(
    user_query: str,
    weights: Optional[dict] = None,
    scenario: Optional[dict] = None,
    baseline_allocation: Optional[dict] = None,
) -> dict:
    """Execute the end-to-end allocation orchestration workflow."""
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    initial_state: GraphState = {
        "user_query": user_query,
        "weights": weights,
        "scenario": scenario,
        "intent": None,
        "solver_result": None,
        "baseline_allocation": baseline_allocation,
        "brief_text": None,
        "final_response": None,
        "trace_steps": [],
        "run_id": run_id,
    }
    result = app.invoke(initial_state)
    return result["final_response"]
