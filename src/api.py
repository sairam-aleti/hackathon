"""
FastAPI application layer for Multi-Plant Order Allocation System.

Provides REST API endpoints:
    - GET  /health: Service readiness status for API, SQLite database, and LLM.
    - POST /ingest: Ingest and validate CSV data files into SQLite tables.
    - POST /analyze: Orchestrates LP allocation optimization and executive briefing.
    - GET  /trace/{run_id}: Retrieves complete execution audit trace.
"""

import json
import logging
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.data_loader import ingest_csv
from src.database import get_connection
from src.graph import run_workflow
from src.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthResponse,
    IngestResponse,
    TraceResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multi-Plant Order Allocation System",
    description="Deterministic LP solver with LangGraph orchestration and zero-hallucination guardrails",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint checking API, Database, and LLM readiness."""
    conn = get_connection()
    db_status = "ready"
    try:
        conn.execute("SELECT 1").fetchone()
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "error"
    finally:
        conn.close()

    llm_status = "mock_mode" if settings.MOCK_LLM else ("ready" if settings.GEMINI_API_KEY else "not_configured")

    return {
        "api": "ready",
        "database": db_status,
        "llm": llm_status,
    }


@app.post("/ingest", response_model=IngestResponse)
async def ingest_data(file: UploadFile = File(...), table_name: str = Form(...)):
    """Upload and validate CSV records into SQLite tables."""
    allowed_tables = {"orders", "plants", "transport_duties", "capacity_events"}
    if table_name not in allowed_tables:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid table_name: '{table_name}'. Allowed tables: {sorted(list(allowed_tables))}",
        )

    file_bytes = await file.read()
    conn = get_connection()
    try:
        result = ingest_csv(file_bytes=file_bytes, table_name=table_name, conn=conn)
    finally:
        conn.close()

    status_str = "success" if result["rows_rejected"] == 0 else "partial"
    return {
        "status": status_str,
        "rows_loaded": {table_name: result["rows_loaded"]},
        "rows_rejected": {table_name: result["rows_rejected"]},
        "validation_errors": result.get("validation_errors", []),
    }


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    """Execute end-to-end allocation optimization pipeline."""
    try:
        result = run_workflow(
            user_query=request.request,
            weights=request.weights,
            scenario=request.scenario,
        )
        return result
    except Exception as e:
        logger.exception("Error in analyze endpoint:")
        raise HTTPException(status_code=500, detail=f"Pipeline execution error: {str(e)}")


@app.get("/trace/{run_id}")
def get_trace(run_id: str):
    """Retrieve full audit trace for an execution run."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT trace_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        return json.loads(row["trace_json"])
    finally:
        conn.close()
