"""
Pydantic v2 models for Multi-Plant Order Allocation System.

This module defines ALL data validation models used across the system:
1. CSV Row Validation Models — used during POST /ingest to validate each row
2. API Request Models — used to validate incoming API requests
3. API Response Models — used to ensure response schema compliance (Section 6.1)

All models use Pydantic v2 with strict validation and descriptive error messages.
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# 1. CSV ROW VALIDATION MODELS
# =============================================================================

class OrderRow(BaseModel):
    """Validates a single row from orders.csv.

    Fields:
        order_id: Unique order identifier (e.g., O-001). Must be non-empty.
        product_id: Product type identifier (e.g., P-Alpha).
        quantity: Number of units ordered. Must be positive.
        destination: Delivery destination city.
        due_date: Required delivery date (ISO-8601). Auto-parsed from string.
        priority: Order priority level (1=highest, 5=lowest).
    """
    order_id: str = Field(..., min_length=1, description="Unique order identifier")
    product_id: str = Field(..., description="Product type identifier")
    quantity: int = Field(..., gt=0, description="Units ordered, must be positive")
    destination: str = Field(..., description="Delivery destination city")
    due_date: date = Field(..., description="Required delivery date (ISO-8601)")
    priority: int = Field(..., ge=1, le=5, description="Priority 1 (highest) to 5 (lowest)")


class PlantRow(BaseModel):
    """Validates a single row from plants.csv.

    Fields:
        plant_id: Plant identifier (A, B, or C).
        capacity: Maximum units producible per planning period.
        unit_cost: Manufacturing cost per unit (USD).
        energy_price: Energy cost per unit (USD).
        carbon_intensity: kg CO2e emitted per unit produced.
    """
    plant_id: str = Field(..., description="Plant identifier")
    capacity: int = Field(..., gt=0, description="Maximum units per period")
    unit_cost: float = Field(..., gt=0, description="Manufacturing cost per unit (USD)")
    energy_price: float = Field(..., ge=0, description="Energy cost per unit (USD)")
    carbon_intensity: float = Field(..., ge=0, description="kg CO2e per unit produced")


class TransportDutyRow(BaseModel):
    """Validates a single row from transport_duties.csv.

    Fields:
        plant_id: Source plant identifier.
        destination: Destination city.
        transport_cost: Shipping cost per unit (USD).
        transit_days: Number of days in transit.
        import_duty: Import duty per unit (USD).
        transport_carbon: kg CO2e per unit shipped.
    """
    plant_id: str = Field(..., description="Source plant identifier")
    destination: str = Field(..., description="Destination city")
    transport_cost: float = Field(..., ge=0, description="Shipping cost per unit (USD)")
    transit_days: int = Field(..., ge=0, description="Days in transit")
    import_duty: float = Field(..., ge=0, description="Import duty per unit (USD)")
    transport_carbon: float = Field(..., ge=0, description="kg CO2e per unit shipped")


class CapacityEventRow(BaseModel):
    """Validates a single row from capacity_events.csv.

    Fields:
        event_id: Unique event identifier.
        plant_id: Affected plant identifier.
        capacity_reduction_pct: Fraction of capacity lost (0.0 to 1.0).
        start_date: Event start date (ISO-8601).
        end_date: Event end date (ISO-8601).
        reason: Human-readable reason for the disruption.
    """
    event_id: str = Field(..., description="Unique event identifier")
    plant_id: str = Field(..., description="Affected plant identifier")
    capacity_reduction_pct: float = Field(..., ge=0, le=1, description="Fraction of capacity lost")
    start_date: date = Field(..., description="Event start date (ISO-8601)")
    end_date: date = Field(..., description="Event end date (ISO-8601)")
    reason: str = Field(..., description="Reason for the disruption")


# =============================================================================
# 2. API REQUEST MODELS
# =============================================================================

class AnalyzeRequest(BaseModel):
    """Request payload for POST /analyze endpoint.

    Fields:
        request: Natural language query from the user.
        weights: Optional optimization weight overrides (cost, carbon, lateness).
        scenario: Optional disruption scenario to simulate.
    """
    request: str = Field(..., description="Natural language query from the user")
    weights: Optional[dict] = Field(default=None, description="Weight overrides: {cost, carbon, lateness}")
    scenario: Optional[dict] = Field(default=None, description="Disruption scenario to simulate")


class IngestRequest(BaseModel):
    """Request metadata for POST /ingest endpoint.

    Fields:
        table_name: Target table. Must be one of: orders, plants, transport_duties, capacity_events.
    """
    table_name: str = Field(
        ...,
        description="Target table name",
        pattern="^(orders|plants|transport_duties|capacity_events)$"
    )


# =============================================================================
# 3. API RESPONSE MODELS (Section 6.1 compliance)
# =============================================================================

class AllocationItem(BaseModel):
    """A single order-to-plant allocation result.

    Fields:
        order_id: The allocated order identifier.
        plant: The plant this order is assigned to.
        cost: Total landed cost for this allocation (USD).
        carbon_kg: Total carbon emissions for this allocation (kg CO2e).
        arrival: Expected arrival date (ISO-8601).
        on_time: Whether the order arrives by its due date.
    """
    order_id: str
    plant: str
    cost: float
    carbon_kg: float
    arrival: str
    on_time: bool


class KPIs(BaseModel):
    """Key Performance Indicators for the allocation plan.

    Fields:
        total_cost: Sum of all allocation landed costs (USD).
        total_carbon_t: Total carbon emissions in tonnes (kg / 1000).
        late_orders: Count of orders arriving after their due date.
        plant_utilisation: Dict mapping plant_id to utilization ratio (0.0–1.0).
    """
    total_cost: float
    total_carbon_t: float
    late_orders: int
    plant_utilisation: dict


class TradeoffPoint(BaseModel):
    """A single point on the Pareto trade-off frontier.

    Fields:
        carbon_cut_pct: Percentage carbon reduction relative to cost-only baseline.
        cost: Total cost at this weight setting (USD).
        late_orders: Number of late orders at this weight setting.
    """
    carbon_cut_pct: float
    cost: float
    late_orders: int


class ValidatorResult(BaseModel):
    """Results of pre-analysis data integrity checks.

    Fields:
        capacity_ok: True if no plant exceeds its effective capacity.
        eligibility_ok: True if all orders can be produced by at least one plant.
    """
    capacity_ok: bool
    eligibility_ok: bool


class AnalyzeResponse(BaseModel):
    """Complete response from POST /analyze endpoint (Section 6.1 schema).

    Fields:
        run_id: Unique identifier for this analysis run.
        answer_type: One of: allocation, scenario, brief, infeasible, clarification_needed, refused.
        summary: Executive brief text (guardrail-verified).
        allocation: List of order-to-plant allocation items.
        kpis: Key Performance Indicators summary.
        tradeoff: Pareto frontier trade-off points.
        weights_used: The optimization weights that were applied.
        validator: Data integrity validation results.
        assumptions: List of assumptions made during analysis.
        limitations: List of known limitations.
    """
    run_id: str
    answer_type: str
    summary: str
    allocation: list[AllocationItem] = []
    kpis: Optional[KPIs] = None
    tradeoff: list[TradeoffPoint] = []
    weights_used: dict = {}
    validator: Optional[ValidatorResult] = None
    assumptions: list[str] = []
    limitations: list[str] = []
    unfulfilled_orders: list[str] = []
    counterfactuals: Optional[dict] = None


class IngestResponse(BaseModel):
    """Response from POST /ingest endpoint.

    Fields:
        status: "success" or "partial" depending on rejected rows.
        rows_loaded: Dict mapping table name to count of loaded rows.
        rows_rejected: Dict mapping table name to count of rejected rows.
        validation_errors: List of dicts describing each validation error.
    """
    status: str
    rows_loaded: dict
    rows_rejected: dict
    validation_errors: list[dict] = []


class HealthResponse(BaseModel):
    """Response from GET /health endpoint.

    Fields:
        api: API server status.
        database: Database connection status.
        llm: LLM service status (or "mock_mode").
    """
    api: str
    database: str
    llm: str


class TraceStep(BaseModel):
    """A single step in the execution trace for audit logging.

    Fields:
        step_name: Name of the pipeline step.
        input_data: Summary of input data for this step.
        output_data: Summary of output data from this step.
        duration_ms: Time taken for this step in milliseconds.
        timestamp: ISO-8601 timestamp when this step started.
    """
    step_name: str
    input_data: dict
    output_data: dict
    duration_ms: float
    timestamp: str


class TraceResponse(BaseModel):
    """Complete trace response from GET /trace/{run_id}.

    Fields:
        run_id: The analysis run identifier.
        steps: List of trace steps in execution order.
        total_duration_ms: Total pipeline duration in milliseconds.
        llm_calls: Number of LLM API calls made.
        llm_tokens: Total tokens consumed by LLM calls.
    """
    run_id: str
    steps: list[TraceStep]
    total_duration_ms: float
    llm_calls: int
    llm_tokens: int
