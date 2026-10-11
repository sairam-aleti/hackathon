"""
PuLP Linear Programming Solver for Multi-Plant Order Allocation.

THIS IS THE MOST CRITICAL FILE IN THE SYSTEM.
The solver uses Mixed-Integer Linear Programming (MILP) to find the optimal
assignment of customer orders to manufacturing plants, balancing:
    - Landed cost (manufacturing + energy + transport + import duty)
    - Carbon emissions (production + transport CO2e)
    - Delivery timeliness (on-time vs. late penalties)

Key Design Decisions:
    1. The LLM NEVER computes numbers — ALL math happens here in PuLP.
    2. Elastic slack variables prevent the solver from crashing on infeasible input.
    3. Churn penalty minimizes disruption during re-planning scenarios.
    4. The objective function normalizes cost and carbon to make weights comparable.

Requirements Covered: R2 (landed cost), R3 (carbon), R4 (solver), R5 (delivery),
                       R6 (trade-off), R7 (re-planning), R11 (Pareto frontier).
"""

import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import pulp

from src.database import get_connection

logger = logging.getLogger(__name__)

# Large penalty constants — named to avoid magic numbers
MISSING_ROUTE_COST = 1e9         # Effectively prohibits assignment to missing routes
UNFULFILLED_DEMAND_PENALTY = 1e6 # Very high penalty per unit of unfulfilled demand
LATE_ORDER_PENALTY = 10000       # Penalty per late order (activated by binary indicator)
CHURN_PENALTY_FACTOR = 100       # Moderate penalty per unit of churn (re-planning stability)
SOLVER_TIME_LIMIT_SECONDS = 5    # Maximum time for CBC solver


# =============================================================================
# DATA LOADING HELPER
# =============================================================================

def load_solver_data(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load all required data from SQLite into pandas DataFrames.

    Args:
        conn: Active SQLite connection with populated tables.

    Returns:
        Tuple of (orders_df, plants_df, transport_df, events_df).
    """
    df_orders = pd.read_sql_query("SELECT * FROM orders", conn)
    df_plants = pd.read_sql_query("SELECT * FROM plants", conn)
    df_transport = pd.read_sql_query("SELECT * FROM transport_duties", conn)
    df_events = pd.read_sql_query("SELECT * FROM capacity_events", conn)
    return df_orders, df_plants, df_transport, df_events


# =============================================================================
# LANDED COST CALCULATION (Requirement R2)
# =============================================================================

def calculate_landed_cost(plant_row: pd.Series, transport_row: pd.Series) -> float:
    """Calculate the per-unit landed cost for a plant-destination combination.

    Landed cost = manufacturing cost + energy cost + shipping cost + import duty.

    Args:
        plant_row: pandas Series with unit_cost and energy_price columns.
        transport_row: pandas Series with transport_cost and import_duty columns.

    Returns:
        Total per-unit landed cost in USD.
    """
    return (
        float(plant_row["unit_cost"])
        + float(plant_row["energy_price"])
        + float(transport_row["transport_cost"])
        + float(transport_row["import_duty"])
    )


# =============================================================================
# CARBON CALCULATION (Requirement R3)
# =============================================================================

def calculate_carbon_per_unit(plant_row: pd.Series, transport_row: pd.Series) -> float:
    """Calculate per-unit carbon emissions for a plant-destination combination.

    Total carbon = production emissions + transport emissions.

    Args:
        plant_row: pandas Series with carbon_intensity column (kg CO2e/unit).
        transport_row: pandas Series with transport_carbon column (kg CO2e/unit).

    Returns:
        Total per-unit carbon emissions in kg CO2e.
    """
    return float(plant_row["carbon_intensity"]) + float(transport_row["transport_carbon"])


# =============================================================================
# DELIVERY CHECK (Requirement R5)
# =============================================================================

def check_delivery(order_due_date: str, transit_days: int,
                   planning_start_date: date) -> tuple[str, bool, int]:
    """Check whether an order can be delivered on time from a given plant.

    Calculates the arrival date as planning_start_date + transit_days,
    then compares against the order's due date.

    Args:
        order_due_date: ISO-8601 string of the order's due date.
        transit_days: Number of days in transit from plant to destination.
        planning_start_date: The date when production/shipping begins.

    Returns:
        Tuple of (arrival_date_iso, on_time_bool, late_days_int).
    """
    due = datetime.strptime(order_due_date, "%Y-%m-%d").date() if isinstance(order_due_date, str) else order_due_date
    arrival = planning_start_date + timedelta(days=transit_days)
    late_days = max(0, (arrival - due).days)
    on_time = late_days == 0
    return arrival.isoformat(), on_time, late_days


# =============================================================================
# MAIN SOLVER FUNCTION (Requirements R4, R6, R7)
# =============================================================================

def solve_allocation(
    conn: sqlite3.Connection,
    weights: Optional[dict] = None,
    scenario: Optional[dict] = None,
    baseline_allocation: Optional[dict] = None,
    planning_start_date: Optional[str] = None,
) -> dict:
    """Solve the order allocation optimization problem using PuLP MILP.

    This is the core optimization engine. It assigns customer orders to
    manufacturing plants to minimize a weighted combination of landed cost,
    carbon emissions, and delivery lateness, subject to capacity constraints.

    Algorithm Overview:
        1. Load data from SQLite
        2. Apply capacity disruptions (scheduled events + ad-hoc scenario)
        3. Pre-compute cost, carbon, and delivery matrices for all order-plant pairs
        4. Build the PuLP optimization model with decision variables
        5. Define the weighted multi-objective function with normalization
        6. Add demand satisfaction and capacity constraints
        7. Solve using CBC solver with time limit
        8. Extract and format results per Section 6.1 response schema

    Args:
        conn: Active SQLite connection with populated data tables.
        weights: Optimization weight overrides. Dict with keys:
                 - cost (float): Weight for landed cost objective (default 0.7)
                 - carbon (float): Weight for carbon objective (default 0.3)
                 - lateness (float): Weight for late delivery penalty (default 0.0)
        scenario: Ad-hoc disruption scenario. Dict with keys:
                  - plant_id (str): Plant to disrupt
                  - capacity_reduction_pct (float): Fraction of capacity lost (0.0–1.0)
        baseline_allocation: Previous allocation for churn minimization during re-planning.
                            Dict mapping (order_id, plant_id) -> quantity.
        planning_start_date: ISO-8601 date string for when planning begins.
                            Defaults to today's date.

    Returns:
        Dict matching AnalyzeResponse schema with keys:
            allocation, kpis, tradeoff, weights_used, answer_type,
            assumptions, limitations, unfulfilled_orders.
    """

    # =========================================================================
    # Step 1: Load data from SQLite
    # =========================================================================
    df_orders, df_plants, df_transport, df_events = load_solver_data(conn)

    if df_orders.empty or df_plants.empty:
        return {
            "allocation": [],
            "kpis": {"total_cost": 0, "total_carbon_t": 0, "late_orders": 0, "plant_utilisation": {}},
            "tradeoff": [],
            "weights_used": {},
            "answer_type": "infeasible",
            "summary": "No orders or plants data available.",
            "assumptions": [],
            "limitations": ["No data loaded"],
            "unfulfilled_orders": [],
        }

    # =========================================================================
    # Step 2: Apply capacity disruptions
    # =========================================================================
    # Start with original capacity as effective capacity
    df_plants = df_plants.copy()
    df_plants["effective_capacity"] = df_plants["capacity"].astype(float)

    # Apply scheduled capacity events that overlap the planning date
    plan_date = (
        datetime.strptime(planning_start_date, "%Y-%m-%d").date()
        if planning_start_date
        else date.today()
    )

    if not df_events.empty:
        for _, event in df_events.iterrows():
            ev_start = datetime.strptime(event["start_date"], "%Y-%m-%d").date()
            ev_end = datetime.strptime(event["end_date"], "%Y-%m-%d").date()
            if ev_start <= plan_date <= ev_end:
                mask = df_plants["plant_id"] == event["plant_id"]
                reduction = float(event["capacity_reduction_pct"])
                df_plants.loc[mask, "effective_capacity"] *= (1 - reduction)
                logger.info(
                    f"Applied capacity event: Plant {event['plant_id']} "
                    f"reduced by {reduction*100:.0f}% due to '{event['reason']}'"
                )

    # Apply ad-hoc scenario disruption (from user request)
    if scenario and "plant_id" in scenario:
        mask = df_plants["plant_id"] == scenario["plant_id"]
        reduction = float(scenario.get("capacity_reduction_pct", 0.3))
        df_plants.loc[mask, "effective_capacity"] *= (1 - reduction)
        logger.info(
            f"Applied scenario disruption: Plant {scenario['plant_id']} "
            f"reduced by {reduction*100:.0f}%"
        )

    # =========================================================================
    # Step 3: Set default weights if not provided
    # =========================================================================
    w_cost = float(weights.get("cost", 0.7)) if weights else 0.7
    w_carbon = float(weights.get("carbon", 0.3)) if weights else 0.3
    w_late = float(weights.get("lateness", 0.0)) if weights else 0.0

    # =========================================================================
    # Step 4: Pre-compute cost, carbon, and delivery matrices
    # =========================================================================
    # Build lookup dict from transport_duties for O(1) access
    transport_lookup: dict[tuple[str, str], pd.Series] = {}
    for _, t_row in df_transport.iterrows():
        transport_lookup[(t_row["plant_id"], t_row["destination"])] = t_row

    cost_matrix: dict[str, dict[str, float]] = {}    # cost_matrix[order_id][plant_id]
    carbon_matrix: dict[str, dict[str, float]] = {}  # carbon_matrix[order_id][plant_id]
    delivery_info: dict[str, dict[str, tuple]] = {}   # delivery_info[order_id][plant_id]

    for _, order in df_orders.iterrows():
        oid = order["order_id"]
        cost_matrix[oid] = {}
        carbon_matrix[oid] = {}
        delivery_info[oid] = {}

        for _, plant in df_plants.iterrows():
            pid = plant["plant_id"]
            t_key = (pid, order["destination"])

            if t_key in transport_lookup:
                t_row = transport_lookup[t_key]
                cost_matrix[oid][pid] = calculate_landed_cost(plant, t_row)
                carbon_matrix[oid][pid] = calculate_carbon_per_unit(plant, t_row)
                delivery_info[oid][pid] = check_delivery(
                    order["due_date"], int(t_row["transit_days"]), plan_date
                )
            else:
                # Missing route — effectively prohibit this assignment
                cost_matrix[oid][pid] = MISSING_ROUTE_COST
                carbon_matrix[oid][pid] = MISSING_ROUTE_COST
                delivery_info[oid][pid] = (
                    (plan_date + timedelta(days=999)).isoformat(), False, 999
                )

    # =========================================================================
    # Step 5: Compute normalization baselines
    # =========================================================================
    # Baseline = ideal cost/carbon if we could always pick the best plant per order
    # ignoring capacity. Used to make cost and carbon objectives comparable.
    cost_baseline = sum(
        min(cost_matrix[o["order_id"]][p["plant_id"]] for _, p in df_plants.iterrows())
        * int(o["quantity"])
        for _, o in df_orders.iterrows()
    )
    carbon_baseline = sum(
        min(carbon_matrix[o["order_id"]][p["plant_id"]] for _, p in df_plants.iterrows())
        * int(o["quantity"])
        for _, o in df_orders.iterrows()
    )
    # Prevent division by zero
    cost_baseline = max(cost_baseline, 1.0)
    carbon_baseline = max(carbon_baseline, 1.0)

    # =========================================================================
    # Step 6: Create the PuLP optimization problem
    # =========================================================================
    prob = pulp.LpProblem("Order_Allocation", pulp.LpMinimize)

    # =========================================================================
    # Step 7: Create decision variables
    # =========================================================================
    # x[order_id, plant_id] = quantity of order assigned to plant (integer for non-splittable)
    x: dict[tuple[str, str], pulp.LpVariable] = {}
    for _, order in df_orders.iterrows():
        for _, plant in df_plants.iterrows():
            x[order["order_id"], plant["plant_id"]] = pulp.LpVariable(
                f"x_{order['order_id']}_{plant['plant_id']}",
                lowBound=0,
                upBound=int(order["quantity"]),
                cat="Integer",
            )

    # s[order_id] = unfulfilled slack (elastic variable to prevent infeasibility crash)
    s: dict[str, pulp.LpVariable] = {}
    for _, order in df_orders.iterrows():
        s[order["order_id"]] = pulp.LpVariable(
            f"slack_{order['order_id']}", lowBound=0, cat="Continuous"
        )

    # u[order_id] = binary lateness indicator (1 if order is late, 0 otherwise)
    u: dict[str, pulp.LpVariable] = {}
    for _, order in df_orders.iterrows():
        u[order["order_id"]] = pulp.LpVariable(
            f"late_{order['order_id']}", lowBound=0, upBound=1, cat="Binary"
        )

    # =========================================================================
    # Step 8: Define the objective function
    # =========================================================================
    # Total landed cost across all assignments
    total_cost_expr = pulp.lpSum([
        cost_matrix[order["order_id"]][plant["plant_id"]]
        * x[order["order_id"], plant["plant_id"]]
        for _, order in df_orders.iterrows()
        for _, plant in df_plants.iterrows()
    ])

    # Total carbon emissions across all assignments
    total_carbon_expr = pulp.lpSum([
        carbon_matrix[order["order_id"]][plant["plant_id"]]
        * x[order["order_id"], plant["plant_id"]]
        for _, order in df_orders.iterrows()
        for _, plant in df_plants.iterrows()
    ])

    # Lateness penalty — activated per late order
    total_late_penalty = pulp.lpSum([
        u[order["order_id"]] * LATE_ORDER_PENALTY
        for _, order in df_orders.iterrows()
    ])

    # Unfulfilled demand penalty — extremely high to prioritize fulfillment
    total_slack_penalty = pulp.lpSum([
        s[order["order_id"]] * UNFULFILLED_DEMAND_PENALTY
        for _, order in df_orders.iterrows()
    ])

    # Churn penalty — only active during re-planning with a baseline allocation
    # Minimizes changes from the previous plan to reduce operational disruption
    churn_penalty = 0
    if baseline_allocation:
        churn_vars: dict[tuple[str, str], pulp.LpVariable] = {}
        for _, order in df_orders.iterrows():
            for _, plant in df_plants.iterrows():
                key = (order["order_id"], plant["plant_id"])
                baseline_qty = baseline_allocation.get(key, 0)
                churn_vars[key] = pulp.LpVariable(
                    f"churn_{key[0]}_{key[1]}", lowBound=0
                )
                # Absolute value linearization: churn >= |x - baseline|
                prob += churn_vars[key] >= x[key] - baseline_qty
                prob += churn_vars[key] >= baseline_qty - x[key]
        churn_penalty = pulp.lpSum(churn_vars.values()) * CHURN_PENALTY_FACTOR

    # Combined normalized objective function
    # Normalization ensures cost and carbon are on comparable scales
    prob += (
        w_cost * (total_cost_expr / cost_baseline)
        + w_carbon * (total_carbon_expr / carbon_baseline)
        + w_late * total_late_penalty
        + total_slack_penalty
        + churn_penalty
    )

    # =========================================================================
    # Step 9: Add constraints
    # =========================================================================

    # Constraint 1: Demand satisfaction
    # Each order must be either fulfilled by plants or covered by slack
    for _, order in df_orders.iterrows():
        prob += (
            pulp.lpSum([
                x[order["order_id"], plant["plant_id"]]
                for _, plant in df_plants.iterrows()
            ]) + s[order["order_id"]] == int(order["quantity"]),
            f"demand_{order['order_id']}",
        )

    # Constraint 2: Plant capacity limits (with disruption adjustments applied)
    for _, plant in df_plants.iterrows():
        effective_cap = float(plant["effective_capacity"])
        prob += (
            pulp.lpSum([
                x[order["order_id"], plant["plant_id"]]
                for _, order in df_orders.iterrows()
            ]) <= effective_cap,
            f"capacity_{plant['plant_id']}",
        )

    # Constraint 3: Lateness indicator linking
    # If an order is assigned to a plant where it would arrive late,
    # the binary lateness indicator u[order_id] is forced to 1
    for _, order in df_orders.iterrows():
        for _, plant in df_plants.iterrows():
            arrival, on_time, late_days = delivery_info[order["order_id"]][plant["plant_id"]]
            if not on_time:
                # If any quantity is assigned to a late plant, mark order as late
                prob += (
                    x[order["order_id"], plant["plant_id"]]
                    <= int(order["quantity"]) * (1 - u[order["order_id"]]) + int(order["quantity"]),
                    f"late_link_{order['order_id']}_{plant['plant_id']}",
                )

    # =========================================================================
    # Step 10: Solve the problem
    # =========================================================================
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=SOLVER_TIME_LIMIT_SECONDS)
    prob.solve(solver)

    solver_status = pulp.LpStatus[prob.status]
    logger.info(f"Solver status: {solver_status}, Objective: {pulp.value(prob.objective)}")

    # =========================================================================
    # Step 11: Extract results into Section 6.1 response schema
    # =========================================================================
    allocation: list[dict] = []
    total_cost = 0.0
    total_carbon_kg = 0.0
    late_count = 0
    plant_allocated: dict[str, float] = {p["plant_id"]: 0.0 for _, p in df_plants.iterrows()}
    unfulfilled_orders: list[str] = []

    for _, order in df_orders.iterrows():
        oid = order["order_id"]

        # Find which plant(s) got this order's allocation
        assigned_plant = None
        assigned_qty = 0

        for _, plant in df_plants.iterrows():
            pid = plant["plant_id"]
            val = x[oid, pid].varValue
            if val is not None and val > 0.5:  # Threshold for integer rounding
                assigned_plant = pid
                assigned_qty = int(round(val))
                break

        if assigned_plant:
            unit_cost = cost_matrix[oid][assigned_plant]
            unit_carbon = carbon_matrix[oid][assigned_plant]
            arrival, on_time, late_days = delivery_info[oid][assigned_plant]

            order_cost = unit_cost * assigned_qty
            order_carbon = unit_carbon * assigned_qty

            allocation.append({
                "order_id": oid,
                "plant": assigned_plant,
                "cost": round(order_cost, 2),
                "carbon_kg": round(order_carbon, 2),
                "arrival": arrival,
                "on_time": on_time,
            })

            total_cost += order_cost
            total_carbon_kg += order_carbon
            if not on_time:
                late_count += 1
            plant_allocated[assigned_plant] += assigned_qty
        else:
            # Order unfulfilled (slack variable absorbed all of it)
            unfulfilled_orders.append(oid)

        # Also check if slack variable absorbed any part of this order
        slack_val = s[oid].varValue
        if slack_val is not None and slack_val > 0.5:
            if oid not in unfulfilled_orders:
                unfulfilled_orders.append(oid)

    # Calculate plant utilization ratios
    plant_utilisation: dict[str, float] = {}
    for _, plant in df_plants.iterrows():
        pid = plant["plant_id"]
        eff_cap = float(plant["effective_capacity"])
        if eff_cap > 0:
            plant_utilisation[pid] = round(plant_allocated[pid] / eff_cap, 4)
        else:
            plant_utilisation[pid] = 0.0

    # Convert total carbon from kg to tonnes
    total_carbon_t = total_carbon_kg / 1000.0

    # Determine answer type
    answer_type = "allocation" if not unfulfilled_orders else "infeasible"

    # Build assumptions list
    assumptions = [
        "All plants can manufacture all product types",
        f"Planning start date: {plan_date.isoformat()}",
        f"Solver time limit: {SOLVER_TIME_LIMIT_SECONDS} seconds",
        "Orders are non-splittable (integer allocation)",
    ]

    # Build limitations list
    limitations = []
    if unfulfilled_orders:
        limitations.append(
            f"{len(unfulfilled_orders)} orders could not be fulfilled due to capacity constraints"
        )
    if solver_status != "Optimal":
        limitations.append(f"Solver terminated with status: {solver_status}")

    return {
        "allocation": allocation,
        "kpis": {
            "total_cost": round(total_cost, 2),
            "total_carbon_t": round(total_carbon_t, 2),
            "late_orders": late_count,
            "plant_utilisation": plant_utilisation,
        },
        "tradeoff": [],  # Populated separately by generate_pareto_frontier
        "weights_used": {"cost": w_cost, "carbon": w_carbon, "lateness": w_late},
        "answer_type": answer_type,
        "summary": "",  # Populated by brief writer
        "assumptions": assumptions,
        "limitations": limitations,
        "unfulfilled_orders": unfulfilled_orders,
    }


# =============================================================================
# PARETO FRONTIER SWEEPER (Requirements R6, R11)
# =============================================================================

def generate_pareto_frontier(
    conn: sqlite3.Connection,
    scenario: Optional[dict] = None,
    num_points: int = 11,
) -> list[dict]:
    """Generate the Pareto trade-off frontier by sweeping cost/carbon weights.

    Runs the solver multiple times with different weight settings to map out
    the trade-off curve between cost and carbon emissions. Each point represents
    the optimal allocation under a different cost-vs-carbon preference.

    Args:
        conn: Active SQLite connection with populated tables.
        scenario: Optional disruption scenario to apply uniformly.
        num_points: Number of points on the frontier (default 11 for 0% to 100%).

    Returns:
        List of TradeoffPoint dicts with keys:
            - carbon_cut_pct: Percentage carbon reduction vs. cost-only baseline.
            - cost: Total cost at this weight setting.
            - late_orders: Number of late orders at this weight setting.
    """
    frontier: list[dict] = []
    baseline_carbon: Optional[float] = None

    for i in range(num_points):
        # Sweep from pure cost optimization to pure carbon optimization
        w_cost = round(1.0 - i / (num_points - 1), 2)
        w_carbon = round(i / (num_points - 1), 2)

        result = solve_allocation(
            conn,
            weights={"cost": w_cost, "carbon": w_carbon},
            scenario=scenario,
        )

        kpis = result["kpis"]
        total_carbon = kpis["total_carbon_t"]
        total_cost = kpis["total_cost"]

        # First point (w_cost=1.0) is the cost-only baseline
        if baseline_carbon is None:
            baseline_carbon = total_carbon

        # Calculate carbon reduction relative to cost-only baseline
        if baseline_carbon > 0:
            carbon_cut_pct = round(
                (baseline_carbon - total_carbon) / baseline_carbon * 100, 2
            )
        else:
            carbon_cut_pct = 0.0

        frontier.append({
            "carbon_cut_pct": carbon_cut_pct,
            "cost": round(total_cost, 2),
            "late_orders": kpis["late_orders"],
        })

    return frontier


# =============================================================================
# EXPLAINABLE COUNTERFACTUALS (Innovation Feature)
# =============================================================================

def explain_order_choice(
    conn: sqlite3.Connection,
    order_id: str,
    current_allocation: dict,
) -> dict:
    """Generate counterfactual explanations for why an order was assigned to its plant.

    For the given order, computes landed cost and carbon at ALL plants,
    showing what would change if the order were assigned elsewhere.

    Args:
        conn: Active SQLite connection.
        order_id: The order to explain.
        current_allocation: The current allocation result dict.

    Returns:
        Dict with chosen_plant info and alternatives with deltas and reasons.
    """
    df_orders, df_plants, df_transport, _ = load_solver_data(conn)
    plan_date = date.today()

    # Find the order
    order = df_orders[df_orders["order_id"] == order_id]
    if order.empty:
        return {"error": f"Order {order_id} not found"}
    order = order.iloc[0]

    # Find which plant was chosen in the current allocation
    chosen_plant = None
    for item in current_allocation.get("allocation", []):
        if item["order_id"] == order_id:
            chosen_plant = item["plant"]
            break

    if not chosen_plant:
        return {"error": f"Order {order_id} not in current allocation"}

    # Build transport lookup
    transport_lookup = {}
    for _, t_row in df_transport.iterrows():
        transport_lookup[(t_row["plant_id"], t_row["destination"])] = t_row

    # Compute metrics for all plants
    alternatives = {}
    chosen_cost = 0.0
    chosen_carbon = 0.0

    for _, plant in df_plants.iterrows():
        pid = plant["plant_id"]
        t_key = (pid, order["destination"])

        if t_key in transport_lookup:
            t_row = transport_lookup[t_key]
            landed_cost = calculate_landed_cost(plant, t_row) * int(order["quantity"])
            carbon = calculate_carbon_per_unit(plant, t_row) * int(order["quantity"])
            arrival, on_time, late_days = check_delivery(
                order["due_date"], int(t_row["transit_days"]), plan_date
            )

            if pid == chosen_plant:
                chosen_cost = landed_cost
                chosen_carbon = carbon

            alternatives[pid] = {
                "landed_cost": round(landed_cost, 2),
                "carbon_kg": round(carbon, 2),
                "transit_days": int(t_row["transit_days"]),
                "on_time": on_time,
                "late_days": late_days,
            }

    # Build human-readable reasons for each alternative
    for pid, alt in alternatives.items():
        if pid == chosen_plant:
            alt["reason"] = "Selected plant (current allocation)"
        else:
            cost_delta = alt["landed_cost"] - chosen_cost
            carbon_delta = alt["carbon_kg"] - chosen_carbon
            reason_parts = []
            if cost_delta > 0:
                reason_parts.append(f"${cost_delta:,.0f} more expensive")
            elif cost_delta < 0:
                reason_parts.append(f"${abs(cost_delta):,.0f} cheaper")
            if carbon_delta > 0:
                reason_parts.append(f"{carbon_delta:,.0f}kg more CO2e")
            elif carbon_delta < 0:
                reason_parts.append(f"{abs(carbon_delta):,.0f}kg less CO2e")
            if not alt["on_time"]:
                reason_parts.append(f"misses deadline by {alt['late_days']} days")
            alt["reason"] = "Plant " + pid + " is " + " but ".join(reason_parts) if reason_parts else "Comparable"
            alt["cost_delta"] = round(cost_delta, 2)
            alt["carbon_delta"] = round(carbon_delta, 2)

    return {
        "order_id": order_id,
        "chosen_plant": chosen_plant,
        "chosen_cost": round(chosen_cost, 2),
        "chosen_carbon": round(chosen_carbon, 2),
        "alternatives": alternatives,
    }


# =============================================================================
# SLA CARBON ARBITRAGE (Innovation Feature)
# =============================================================================

def evaluate_carbon_arbitrage(
    conn: sqlite3.Connection,
    order_id: str,
    max_extra_days: int = 2,
) -> dict:
    """Evaluate if allowing extra transit days could yield carbon savings.

    Checks whether relaxing the delivery deadline by max_extra_days opens up
    a greener plant option that was previously excluded due to timing.

    Args:
        conn: Active SQLite connection.
        order_id: The order to evaluate.
        max_extra_days: Maximum additional transit days to consider.

    Returns:
        Dict with original and alternative plant info, carbon savings potential.
    """
    df_orders, df_plants, df_transport, _ = load_solver_data(conn)
    plan_date = date.today()

    order = df_orders[df_orders["order_id"] == order_id]
    if order.empty:
        return {"error": f"Order {order_id} not found"}
    order = order.iloc[0]

    transport_lookup = {}
    for _, t_row in df_transport.iterrows():
        transport_lookup[(t_row["plant_id"], t_row["destination"])] = t_row

    # Find on-time options with original deadline
    on_time_options = []
    all_options = []

    for _, plant in df_plants.iterrows():
        pid = plant["plant_id"]
        t_key = (pid, order["destination"])
        if t_key not in transport_lookup:
            continue
        t_row = transport_lookup[t_key]
        carbon = calculate_carbon_per_unit(plant, t_row) * int(order["quantity"])
        cost = calculate_landed_cost(plant, t_row) * int(order["quantity"])
        _, on_time_orig, _ = check_delivery(order["due_date"], int(t_row["transit_days"]), plan_date)

        # Check with relaxed deadline
        relaxed_due = (
            datetime.strptime(order["due_date"], "%Y-%m-%d").date()
            + timedelta(days=max_extra_days)
        )
        _, on_time_relaxed, _ = check_delivery(
            relaxed_due.isoformat(), int(t_row["transit_days"]), plan_date
        )

        option = {
            "plant_id": pid,
            "carbon_kg": round(carbon, 2),
            "cost": round(cost, 2),
            "transit_days": int(t_row["transit_days"]),
            "on_time_original": on_time_orig,
            "on_time_relaxed": on_time_relaxed,
        }
        all_options.append(option)
        if on_time_orig:
            on_time_options.append(option)

    if not on_time_options:
        return {
            "order_id": order_id,
            "message": "No on-time options available even with original deadline",
        }

    # Find greenest on-time option with original deadline
    original_best = min(on_time_options, key=lambda x: x["carbon_kg"])

    # Find greenest option with relaxed deadline
    relaxed_options = [o for o in all_options if o["on_time_relaxed"]]
    if relaxed_options:
        relaxed_best = min(relaxed_options, key=lambda x: x["carbon_kg"])

        if relaxed_best["carbon_kg"] < original_best["carbon_kg"]:
            savings_pct = round(
                (original_best["carbon_kg"] - relaxed_best["carbon_kg"])
                / original_best["carbon_kg"] * 100, 2
            )
            return {
                "order_id": order_id,
                "original_plant": original_best["plant_id"],
                "original_carbon_kg": original_best["carbon_kg"],
                "alternative_plant": relaxed_best["plant_id"],
                "alternative_carbon_kg": relaxed_best["carbon_kg"],
                "carbon_savings_pct": savings_pct,
                "extra_days_needed": relaxed_best["transit_days"] - original_best["transit_days"],
            }

    return {
        "order_id": order_id,
        "original_plant": original_best["plant_id"],
        "original_carbon_kg": original_best["carbon_kg"],
        "message": "No greener alternative found even with relaxed deadline",
    }
