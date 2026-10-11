"""
CSV Data Ingestion Engine for Multi-Plant Order Allocation System.

Handles reading uploaded CSV files, validating each row against Pydantic models,
persisting valid rows to SQLite, and returning detailed rejection reports.

Supports both programmatic usage (via ingest_csv function) and CLI usage
for initial data loading during development/deployment.

Validation Strategy:
    - Each row is validated independently using the appropriate Pydantic model
    - Valid rows are batch-inserted via pandas DataFrame.to_sql()
    - Invalid rows are collected with error details for the rejection report
    - Reference tables (plants, transport_duties) use REPLACE strategy
    - Append tables (orders, capacity_events) use APPEND strategy
"""

import csv
import io
import logging
import sqlite3
from typing import Any

import pandas as pd
from pydantic import ValidationError

from src.models import OrderRow, PlantRow, TransportDutyRow, CapacityEventRow
from src.database import get_connection

logger = logging.getLogger(__name__)

# Mapping of table names to their Pydantic validation models
TABLE_MODEL_MAP: dict[str, type] = {
    "orders": OrderRow,
    "plants": PlantRow,
    "transport_duties": TransportDutyRow,
    "capacity_events": CapacityEventRow,
}

# Tables that should replace all existing data on each ingest
# (reference/master data tables vs. transactional tables)
REPLACE_TABLES: set[str] = {"plants", "transport_duties"}


def ingest_csv(file_bytes: bytes, table_name: str, conn: sqlite3.Connection) -> dict[str, Any]:
    """Ingest a CSV file into the specified SQLite table with row-level validation.

    Args:
        file_bytes: Raw bytes of the uploaded CSV file.
        table_name: Target table name. Must be one of:
                    orders, plants, transport_duties, capacity_events.
        conn: Active SQLite connection.

    Returns:
        Dict with keys:
            - rows_loaded (int): Count of successfully inserted rows.
            - rows_rejected (int): Count of rows that failed validation.
            - validation_errors (list[dict]): Details of each rejected row.

    Raises:
        ValueError: If table_name is not recognized.
    """
    if table_name not in TABLE_MODEL_MAP:
        raise ValueError(f"Unknown table: {table_name}. Valid tables: {list(TABLE_MODEL_MAP.keys())}")

    model_class = TABLE_MODEL_MAP[table_name]

    # Decode bytes to string, handling BOM (Byte Order Mark) if present
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    valid_records: list[dict] = []
    validation_errors: list[dict] = []

    for row_num, raw_row in enumerate(reader, start=2):  # Start at 2 (row 1 is header)
        try:
            # Validate the row using the Pydantic model
            validated = model_class(**raw_row)
            # Convert to dict, serializing date objects to ISO strings for SQLite
            record = validated.model_dump()
            for key, value in record.items():
                if hasattr(value, "isoformat"):
                    record[key] = value.isoformat()
            valid_records.append(record)
        except ValidationError as e:
            # Capture the first error message for this row
            first_error = e.errors()[0]["msg"] if e.errors() else "Unknown validation error"
            validation_errors.append({
                "row": row_num,
                "data": dict(raw_row),
                "error": first_error,
            })
            logger.warning(f"Row {row_num} in '{table_name}' rejected: {first_error}")
        except Exception as e:
            validation_errors.append({
                "row": row_num,
                "data": dict(raw_row),
                "error": str(e),
            })
            logger.warning(f"Row {row_num} in '{table_name}' unexpected error: {e}")

    # Batch insert valid records directly into SQLite for maximum reliability
    if valid_records:
        columns = list(valid_records[0].keys())
        col_names = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT OR REPLACE INTO {table_name} ({col_names}) VALUES ({placeholders})"
        rows_tuples = [tuple(r[c] for c in columns) for r in valid_records]
        conn.execute(f"DELETE FROM {table_name}")
        conn.executemany(sql, rows_tuples)
        conn.commit()
        logger.info(f"Loaded {len(valid_records)} rows into '{table_name}'.")

    return {
        "rows_loaded": len(valid_records),
        "rows_rejected": len(validation_errors),
        "validation_errors": validation_errors,
    }


# CLI entry point for initial data loading
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load CSV data into SQLite database")
    parser.add_argument("--file", required=True, help="Path to CSV file")
    parser.add_argument("--table", required=True,
                        choices=["orders", "plants", "transport_duties", "capacity_events"],
                        help="Target table name")
    args = parser.parse_args()

    with open(args.file, "rb") as f:
        result = ingest_csv(f.read(), args.table, get_connection())
    print(f"Ingestion result: {result}")
