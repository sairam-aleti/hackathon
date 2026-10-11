"""
Pytest fixtures for Multi-Plant Order Allocation System test suite.
"""

import sqlite3
import pytest

from src.database import init_db


@pytest.fixture
def test_conn():
    """In-memory SQLite database pre-populated with controlled test data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Insert test plants
    plants_data = [
        ("A", 6000, 18.50, 3.20, 12.4),
        ("B", 5000, 22.00, 2.80, 8.6),
        ("C", 3500, 25.00, 4.10, 3.2),
    ]
    conn.executemany(
        "INSERT INTO plants (plant_id, capacity, unit_cost, energy_price, carbon_intensity) VALUES (?, ?, ?, ?, ?)",
        plants_data,
    )

    # Insert test transport duties (3 plants x 3 destinations: Berlin, London, Tokyo)
    transport_data = [
        ("A", "Berlin", 2.50, 2, 0.00, 1.20),
        ("A", "London", 4.20, 4, 2.50, 2.10),
        ("A", "Tokyo", 12.50, 12, 6.00, 7.80),
        ("B", "Berlin", 4.00, 4, 2.00, 2.20),
        ("B", "London", 2.20, 2, 0.00, 1.10),
        ("B", "Tokyo", 9.80, 8, 4.50, 5.80),
        ("C", "Berlin", 5.50, 5, 2.50, 2.80),
        ("C", "London", 5.20, 5, 2.20, 2.60),
        ("C", "Tokyo", 6.80, 4, 2.00, 3.20),
    ]
    conn.executemany(
        "INSERT INTO transport_duties (plant_id, destination, transport_cost, transit_days, import_duty, transport_carbon) VALUES (?, ?, ?, ?, ?, ?)",
        transport_data,
    )

    # Insert 5 test orders
    orders_data = [
        ("O-001", "P-Alpha", 100, "Tokyo", "2026-10-18", 1),   # Plant A takes 12d (late), Plant C takes 4d (on time)
        ("O-002", "P-Beta", 200, "Berlin", "2026-10-25", 2),
        ("O-003", "P-Gamma", 150, "London", "2026-10-25", 3),
        ("O-004", "P-Delta", 300, "Tokyo", "2026-11-01", 1),
        ("O-005", "P-Alpha", 250, "Berlin", "2026-10-20", 4),
    ]
    conn.executemany(
        "INSERT INTO orders (order_id, product_id, quantity, destination, due_date, priority) VALUES (?, ?, ?, ?, ?, ?)",
        orders_data,
    )

    # Insert test capacity event
    conn.execute(
        "INSERT INTO capacity_events (event_id, plant_id, capacity_reduction_pct, start_date, end_date, reason) VALUES (?, ?, ?, ?, ?, ?)",
        ("EV-01", "B", 0.30, "2026-10-15", "2026-10-29", "Boiler maintenance"),
    )

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def sample_solver_result():
    """Mock solver output result for testing guardrails and formatters."""
    return {
        "run_id": "test-run-123",
        "answer_type": "allocation",
        "summary": "",
        "allocation": [
            {
                "order_id": "O-001",
                "plant": "C",
                "cost": 3810.00,
                "carbon_kg": 640.0,
                "arrival": "2026-10-15",
                "on_time": True,
            },
            {
                "order_id": "O-002",
                "plant": "A",
                "cost": 4840.00,
                "carbon_kg": 2720.0,
                "arrival": "2026-10-13",
                "on_time": True,
            },
        ],
        "kpis": {
            "total_cost": 8650.00,
            "total_carbon_t": 3.36,
            "late_orders": 0,
            "plant_utilisation": {"A": 0.0333, "B": 0.0, "C": 0.0286},
        },
        "tradeoff": [
            {"carbon_cut_pct": 0.0, "cost": 8650.00, "late_orders": 0},
            {"carbon_cut_pct": 12.5, "cost": 9120.00, "late_orders": 0},
        ],
        "weights_used": {"cost": 0.7, "carbon": 0.3, "lateness": 0.0},
        "validator": {"capacity_ok": True, "eligibility_ok": True},
        "assumptions": ["Standard test fixture"],
        "limitations": [],
        "unfulfilled_orders": [],
    }
