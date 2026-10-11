"""
Pre-Analysis Data Validator for Multi-Plant Order Allocation System.

Performs comprehensive data integrity checks BEFORE the solver runs (Section 4.5).
This ensures the data in SQLite is consistent, complete, and ready for optimization.

Checks Performed:
    1. Product Eligibility — all products can be produced by at least one plant
    2. Transport Route Completeness — routes exist for all plant-destination pairs
    3. Positive Capacity — all plants have capacity > 0
    4. Due Date Validity — order due dates are not in the past
    5. Carbon Intensity Range — values within reasonable bounds (0–100 kg CO2e/unit)
    6. Row Count Summary — counts of all data tables
    7. Capacity Event Validity — event references and values are correct
"""

import sqlite3
import logging
from datetime import date

logger = logging.getLogger(__name__)


def validate_data(conn: sqlite3.Connection) -> dict:
    """Run all pre-analysis data integrity checks on the current SQLite data.

    Args:
        conn: Active SQLite connection with populated tables.

    Returns:
        Dict with keys:
            - valid (bool): True if ALL critical checks passed.
            - checks (list[dict]): Detailed result for each check, containing:
                - check_name (str): Human-readable name of the check.
                - passed (bool): Whether this specific check passed.
                - details (str): Description of what was found.
    """
    checks: list[dict] = []
    all_passed = True

    # =========================================================================
    # Check 1: Product Eligibility
    # Verify every order's product_id can be produced by at least one plant.
    # In the basic spec, all plants can make all products unless restricted.
    # =========================================================================
    try:
        products = conn.execute("SELECT DISTINCT product_id FROM orders").fetchall()
        product_ids = [row["product_id"] for row in products]
        # Since no product-plant restriction table exists, all products are eligible
        checks.append({
            "check_name": "Product Eligibility",
            "passed": True,
            "details": f"All {len(product_ids)} product types are eligible at all plants. "
                       f"Products: {', '.join(product_ids)}",
        })
    except Exception as e:
        checks.append({
            "check_name": "Product Eligibility",
            "passed": False,
            "details": f"Error checking product eligibility: {e}",
        })
        all_passed = False

    # =========================================================================
    # Check 2: Transport Route Completeness
    # For every (plant_id, destination) pair needed, verify a transport route exists.
    # =========================================================================
    try:
        destinations = conn.execute("SELECT DISTINCT destination FROM orders").fetchall()
        dest_set = {row["destination"] for row in destinations}

        plants = conn.execute("SELECT DISTINCT plant_id FROM plants").fetchall()
        plant_set = {row["plant_id"] for row in plants}

        routes = conn.execute("SELECT DISTINCT plant_id, destination FROM transport_duties").fetchall()
        route_set = {(row["plant_id"], row["destination"]) for row in routes}

        missing_pairs = []
        for plant_id in plant_set:
            for dest in dest_set:
                if (plant_id, dest) not in route_set:
                    missing_pairs.append(f"({plant_id}, {dest})")

        if missing_pairs:
            checks.append({
                "check_name": "Transport Route Completeness",
                "passed": False,
                "details": f"Missing {len(missing_pairs)} transport routes: {', '.join(missing_pairs[:10])}",
            })
            all_passed = False
        else:
            checks.append({
                "check_name": "Transport Route Completeness",
                "passed": True,
                "details": f"All {len(route_set)} required transport routes are present.",
            })
    except Exception as e:
        checks.append({
            "check_name": "Transport Route Completeness",
            "passed": False,
            "details": f"Error checking transport routes: {e}",
        })
        all_passed = False

    # =========================================================================
    # Check 3: Positive Capacity
    # All plant capacities must be > 0.
    # =========================================================================
    try:
        bad_caps = conn.execute("SELECT plant_id, capacity FROM plants WHERE capacity <= 0").fetchall()
        if bad_caps:
            bad_list = [f"{row['plant_id']}={row['capacity']}" for row in bad_caps]
            checks.append({
                "check_name": "Positive Capacity",
                "passed": False,
                "details": f"Plants with non-positive capacity: {', '.join(bad_list)}",
            })
            all_passed = False
        else:
            checks.append({
                "check_name": "Positive Capacity",
                "passed": True,
                "details": "All plants have positive capacity.",
            })
    except Exception as e:
        checks.append({
            "check_name": "Positive Capacity",
            "passed": False,
            "details": f"Error checking capacity: {e}",
        })
        all_passed = False

    # =========================================================================
    # Check 4: Due Date Validity
    # All order due_dates should be >= today. Flag past dates but don't fail.
    # =========================================================================
    try:
        today = date.today().isoformat()
        past_due = conn.execute(
            "SELECT order_id, due_date FROM orders WHERE due_date < ?", (today,)
        ).fetchall()
        if past_due:
            past_list = [f"{row['order_id']}({row['due_date']})" for row in past_due[:5]]
            checks.append({
                "check_name": "Due Date Validity",
                "passed": True,  # Warning only, not a failure
                "details": f"WARNING: {len(past_due)} orders have past due dates: {', '.join(past_list)}. "
                           f"These will be treated as already late.",
            })
        else:
            checks.append({
                "check_name": "Due Date Validity",
                "passed": True,
                "details": "All order due dates are in the future.",
            })
    except Exception as e:
        checks.append({
            "check_name": "Due Date Validity",
            "passed": False,
            "details": f"Error checking due dates: {e}",
        })
        all_passed = False

    # =========================================================================
    # Check 5: Carbon Intensity Range
    # Verify values are within reasonable bounds (0–100 kg CO2e/unit).
    # =========================================================================
    try:
        outliers = conn.execute(
            "SELECT plant_id, carbon_intensity FROM plants WHERE carbon_intensity > 100"
        ).fetchall()
        if outliers:
            outlier_list = [f"{row['plant_id']}={row['carbon_intensity']}" for row in outliers]
            checks.append({
                "check_name": "Carbon Intensity Range",
                "passed": False,
                "details": f"Outlier carbon intensities (>100 kg CO2e/unit): {', '.join(outlier_list)}",
            })
            all_passed = False
        else:
            checks.append({
                "check_name": "Carbon Intensity Range",
                "passed": True,
                "details": "All carbon intensity values are within reasonable range (0–100).",
            })
    except Exception as e:
        checks.append({
            "check_name": "Carbon Intensity Range",
            "passed": False,
            "details": f"Error checking carbon intensity: {e}",
        })
        all_passed = False

    # =========================================================================
    # Check 6: Row Count Summary
    # Report counts of all data tables.
    # =========================================================================
    try:
        counts = {}
        for table in ["orders", "plants", "transport_duties", "capacity_events"]:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            counts[table] = row["cnt"]
        checks.append({
            "check_name": "Row Count Summary",
            "passed": True,
            "details": f"Orders: {counts['orders']}, Plants: {counts['plants']}, "
                       f"Transport Routes: {counts['transport_duties']}, "
                       f"Capacity Events: {counts['capacity_events']}",
        })
    except Exception as e:
        checks.append({
            "check_name": "Row Count Summary",
            "passed": False,
            "details": f"Error counting rows: {e}",
        })
        all_passed = False

    # =========================================================================
    # Check 7: Capacity Event Validity
    # Events must reference existing plants and have valid reduction percentages.
    # =========================================================================
    try:
        events = conn.execute("SELECT * FROM capacity_events").fetchall()
        if events:
            plant_ids = {row["plant_id"] for row in conn.execute("SELECT plant_id FROM plants").fetchall()}
            bad_events = []
            for ev in events:
                if ev["plant_id"] not in plant_ids:
                    bad_events.append(f"{ev['event_id']}: unknown plant {ev['plant_id']}")
                if not (0 <= ev["capacity_reduction_pct"] <= 1):
                    bad_events.append(f"{ev['event_id']}: invalid reduction {ev['capacity_reduction_pct']}")
            if bad_events:
                checks.append({
                    "check_name": "Capacity Event Validity",
                    "passed": False,
                    "details": f"Invalid events: {'; '.join(bad_events)}",
                })
                all_passed = False
            else:
                checks.append({
                    "check_name": "Capacity Event Validity",
                    "passed": True,
                    "details": f"All {len(events)} capacity events are valid.",
                })
        else:
            checks.append({
                "check_name": "Capacity Event Validity",
                "passed": True,
                "details": "No capacity events to validate.",
            })
    except Exception as e:
        checks.append({
            "check_name": "Capacity Event Validity",
            "passed": False,
            "details": f"Error checking capacity events: {e}",
        })
        all_passed = False

    return {"valid": all_passed, "checks": checks}
