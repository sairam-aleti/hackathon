"""
Database module for Multi-Plant Order Allocation System.

Provides SQLite connection management and schema initialization.
Uses Python's built-in sqlite3 module for lightweight, zero-dependency
database access. Tables are created automatically on module import.

Tables:
    - orders: Customer manufacturing orders to be allocated
    - plants: Manufacturing plant specifications and costs
    - transport_duties: Shipping costs, times, and duties per plant-destination pair
    - capacity_events: Scheduled disruptions that reduce plant capacity
    - runs: Audit log of every allocation run with full trace data
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

# Database file path — kept simple for SQLite
DB_PATH = "allocation.db"


def get_connection() -> sqlite3.Connection:
    """Get a reusable SQLite connection with Row factory enabled.

    Returns:
        sqlite3.Connection: A connection object that returns Row objects
        (dict-like access by column name) instead of plain tuples.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all required tables if they don't already exist.

    This is idempotent — safe to call multiple times. Each table uses
    IF NOT EXISTS to avoid errors on re-initialization.

    Args:
        conn: Active SQLite connection to initialize.
    """
    cursor = conn.cursor()

    # Orders table: customer manufacturing orders
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            destination TEXT NOT NULL,
            due_date TEXT NOT NULL,
            priority INTEGER NOT NULL
        )
    """)

    # Plants table: manufacturing facility specifications
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plants (
            plant_id TEXT PRIMARY KEY,
            capacity INTEGER NOT NULL,
            unit_cost REAL NOT NULL,
            energy_price REAL NOT NULL,
            carbon_intensity REAL NOT NULL
        )
    """)

    # Transport duties: shipping costs and logistics per plant-destination pair
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transport_duties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plant_id TEXT NOT NULL,
            destination TEXT NOT NULL,
            transport_cost REAL NOT NULL,
            transit_days INTEGER NOT NULL,
            import_duty REAL NOT NULL,
            transport_carbon REAL NOT NULL,
            UNIQUE(plant_id, destination)
        )
    """)

    # Capacity events: scheduled disruptions reducing plant capacity
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS capacity_events (
            event_id TEXT PRIMARY KEY,
            plant_id TEXT NOT NULL,
            capacity_reduction_pct REAL NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT NOT NULL
        )
    """)

    # Runs table: audit log for every allocation run
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            request_text TEXT,
            response_json TEXT,
            created_at TEXT,
            trace_json TEXT
        )
    """)

    conn.commit()
    logger.info("Database tables initialized successfully.")


def clear_table(conn: sqlite3.Connection, table_name: str) -> None:
    """Delete all rows from a given table.

    Args:
        conn: Active SQLite connection.
        table_name: Name of the table to clear. Must be one of the known tables
                    to prevent SQL injection.

    Raises:
        ValueError: If table_name is not a recognized table.
    """
    allowed_tables = {"orders", "plants", "transport_duties", "capacity_events", "runs"}
    if table_name not in allowed_tables:
        raise ValueError(f"Unknown table: {table_name}. Allowed: {allowed_tables}")
    conn.execute(f"DELETE FROM {table_name}")
    conn.commit()
    logger.info(f"Cleared all rows from table '{table_name}'.")


# Auto-initialize database on module import
try:
    _conn = get_connection()
    init_db(_conn)
    _conn.close()
except Exception as e:
    logger.warning(f"Database auto-init failed (non-critical): {e}")
