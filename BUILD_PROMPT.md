# MASTER BUILD PROMPT: Multi-Plant Order Allocation System
# HCLTech Future Ready AI Engineer Hackathon
# ============================================================
# This prompt contains EVERY implementation detail needed to generate
# the complete working codebase in one sitting.
# ============================================================

## CONTEXT & OBJECTIVE
You are building a complete, production-grade AI system for a hackathon evaluated by HCLTech judges.
The system allocates customer manufacturing orders across 3 plants (A, B, C), balancing landed cost,
carbon emissions, and delivery deadlines. The LLM NEVER computes numbers. A PuLP linear programming
solver does ALL math. The LLM only parses user intent and writes executive briefs from solver output.

The system will be judged on: valid allocation (25 pts), trade-off view (15 pts), re-planning (15 pts),
scenario & brief agents (10 pts), weight reasoning (10 pts), evaluation rigour (5 pts), engineering
quality (10 pts), architecture judgement (10 pts). Total = 100 points.

## TECHNOLOGY STACK (MANDATORY - DO NOT DEVIATE)
- Python 3.11
- FastAPI + Uvicorn + Pydantic v2 (API layer)
- LangGraph (Python) for orchestration (NOT LangChain agents, NOT a simple script)
- PuLP with CBC solver for linear programming optimization
- SQLite for all structured data storage (NOT PostgreSQL, NOT DuckDB)
- Streamlit for the frontend dashboard
- pandas, numpy for data manipulation
- plotly for interactive charts (Pareto curve, utilization bars)
- Docker + docker-compose for packaging
- LLM: Google Gemini (gemini-2.0-flash) via API, with MOCK_LLM=true fallback
- All API keys loaded from .env file using python-dotenv, NEVER hardcoded

## COMPLETE FILE STRUCTURE TO GENERATE
```
project-root/
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
├── EXPLANATION.md              (already exists, do not regenerate)
├── DESIGN.md                   (already exists, do not regenerate)
├── data/
│   ├── orders.csv
│   ├── plants.csv
│   ├── transport_duties.csv
│   ├── capacity_events.csv
│   └── DATA_CARD.md
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── database.py
│   ├── data_loader.py
│   ├── validator.py
│   ├── solver.py
│   ├── api.py
│   ├── guardrails.py
│   ├── graph.py
│   └── agents/
│       ├── __init__.py
│       └── brief_writer.py
├── ui/
│   └── app.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── test_evaluation.py
```

---

## FILE-BY-FILE IMPLEMENTATION SPECIFICATIONS

---

### FILE 1: `.env.example`
```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
GEMINI_API_KEY=your-key-here
MOCK_LLM=true
DATABASE_URL=sqlite:///./allocation.db
LOG_LEVEL=INFO
```

---

### FILE 2: `.gitignore`
Standard Python gitignore. Include: `__pycache__/`, `*.pyc`, `.env`, `*.db`, `*.sqlite3`,
`.venv/`, `venv/`, `dist/`, `build/`, `*.egg-info/`, `.pytest_cache/`, `htmlcov/`.

---

### FILE 3: `requirements.txt`
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
pydantic==2.9.0
python-dotenv==1.0.1
pulp==2.9.0
pandas==2.2.0
numpy==1.26.0
plotly==5.22.0
streamlit==1.38.0
langgraph==0.2.0
langchain-core==0.3.0
langchain-google-genai==2.0.0
httpx==0.27.0
pytest==8.3.0
```

---

### FILE 4: `src/config.py`
PURPOSE: Central configuration loader. All settings come from environment variables.

```python
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.0-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    MOCK_LLM: bool = os.getenv("MOCK_LLM", "true").lower() == "true"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./allocation.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()
```

---

### FILE 5: `src/database.py`
PURPOSE: SQLite connection manager. Creates tables on startup. Provides a single reusable
connection function.

IMPLEMENTATION DETAILS:
- Use Python's built-in `sqlite3` module.
- Create function `get_connection()` that returns a sqlite3.Connection with `row_factory = sqlite3.Row`.
- Create function `init_db(conn)` that creates these tables if they don't exist:
  - `orders`: order_id TEXT PRIMARY KEY, product_id TEXT, quantity INTEGER, destination TEXT,
    due_date TEXT, priority INTEGER
  - `plants`: plant_id TEXT PRIMARY KEY, capacity INTEGER, unit_cost REAL, energy_price REAL,
    carbon_intensity REAL
  - `transport_duties`: id INTEGER PRIMARY KEY AUTOINCREMENT, plant_id TEXT, destination TEXT,
    transport_cost REAL, transit_days INTEGER, import_duty REAL, transport_carbon REAL,
    UNIQUE(plant_id, destination)
  - `capacity_events`: event_id TEXT PRIMARY KEY, plant_id TEXT, capacity_reduction_pct REAL,
    start_date TEXT, end_date TEXT, reason TEXT
  - `runs`: run_id TEXT PRIMARY KEY, request_text TEXT, response_json TEXT, created_at TEXT,
    trace_json TEXT
- Create function `clear_table(conn, table_name)` that deletes all rows from a given table.
- On module import, automatically call `init_db(get_connection())`.

---

### FILE 6: `src/models.py`
PURPOSE: All Pydantic v2 models for API request/response validation AND CSV row validation.

MODELS TO CREATE:

1. **CSV Row Validation Models** (used during POST /ingest):
   - `OrderRow`: order_id (str, min_length=1), product_id (str), quantity (int, gt=0),
     destination (str), due_date (date, Pydantic auto-parses ISO strings), priority (int, ge=1, le=5)
   - `PlantRow`: plant_id (str), capacity (int, gt=0), unit_cost (float, gt=0),
     energy_price (float, ge=0), carbon_intensity (float, ge=0)
   - `TransportDutyRow`: plant_id (str), destination (str), transport_cost (float, ge=0),
     transit_days (int, ge=0), import_duty (float, ge=0), transport_carbon (float, ge=0)
   - `CapacityEventRow`: event_id (str), plant_id (str), capacity_reduction_pct (float, ge=0, le=1),
     start_date (date), end_date (date), reason (str)

2. **API Request Models**:
   - `AnalyzeRequest`: request (str), weights (Optional dict with keys cost, carbon, lateness,
     all floats, default None), scenario (Optional dict, default None)
   - `IngestRequest`: table_name (str, must be one of: orders, plants, transport_duties, capacity_events)

3. **API Response Models** (MUST match Section 6.1 of hackathon spec exactly):
   - `AllocationItem`: order_id (str), plant (str), cost (float), carbon_kg (float),
     arrival (str, ISO date), on_time (bool)
   - `KPIs`: total_cost (float), total_carbon_t (float), late_orders (int),
     plant_utilisation (dict mapping plant_id to float between 0 and 1)
   - `TradeoffPoint`: carbon_cut_pct (float), cost (float), late_orders (int)
   - `ValidatorResult`: capacity_ok (bool), eligibility_ok (bool)
   - `AnalyzeResponse`: run_id (str), answer_type (str, one of: allocation, scenario, brief,
     infeasible, clarification_needed, refused), summary (str), allocation (list of AllocationItem),
     kpis (KPIs), tradeoff (list of TradeoffPoint), weights_used (dict), validator (ValidatorResult),
     assumptions (list of str), limitations (list of str)
   - `IngestResponse`: status (str), rows_loaded (dict mapping table name to int),
     rows_rejected (dict mapping table name to int), validation_errors (list of dict)
   - `HealthResponse`: api (str), database (str), llm (str)
   - `TraceStep`: step_name (str), input_data (dict), output_data (dict),
     duration_ms (float), timestamp (str)
   - `TraceResponse`: run_id (str), steps (list of TraceStep), total_duration_ms (float),
     llm_calls (int), llm_tokens (int)

---

### FILE 7: `src/data_loader.py`
PURPOSE: CSV file ingestion engine. Reads uploaded CSV bytes, validates each row using
Pydantic models, saves valid rows to SQLite, returns rejection report.

IMPLEMENTATION DETAILS:
- Function `ingest_csv(file_bytes: bytes, table_name: str, conn: sqlite3.Connection) -> dict`:
  1. Read bytes as UTF-8 string, handle BOM if present.
  2. Use `csv.DictReader` to iterate rows.
  3. Based on `table_name`, select the appropriate Pydantic model:
     - "orders" -> OrderRow
     - "plants" -> PlantRow
     - "transport_duties" -> TransportDutyRow
     - "capacity_events" -> CapacityEventRow
  4. For each row, try to validate with the Pydantic model.
     - On success: append `model.model_dump()` to valid_records list (convert date objects to
       ISO string format for SQLite storage).
     - On ValidationError: append row number, raw data, and first error message to rejected list.
  5. If valid_records is not empty, use pandas DataFrame.to_sql() to write to SQLite
     with `if_exists="replace"` for plants and transport_duties (since they are reference tables),
     and `if_exists="append"` for orders and capacity_events.
  6. Return dict with rows_loaded count, rows_rejected count, and validation_errors list.

- Also provide a CLI entry point:
  ```python
  if __name__ == "__main__":
      import argparse
      parser = argparse.ArgumentParser(description="Load CSV data into SQLite")
      parser.add_argument("--file", required=True, help="Path to CSV file")
      parser.add_argument("--table", required=True, choices=["orders", "plants",
                          "transport_duties", "capacity_events"])
      args = parser.parse_args()
      with open(args.file, "rb") as f:
          result = ingest_csv(f.read(), args.table, get_connection())
      print(result)
  ```

---

### FILE 8: `src/validator.py`
PURPOSE: Pre-analysis data integrity checks (Section 4.5 of hackathon spec). This runs
BEFORE the solver to ensure the data in SQLite is consistent and complete.

IMPLEMENTATION DETAILS:
- Function `validate_data(conn: sqlite3.Connection) -> dict`:
  Returns a dict with keys: `valid` (bool), `checks` (list of dicts with check_name, passed, details).

  Checks to implement (ALL of these are mandatory per Section 4.5):

  1. **Product Eligibility Check**: Every order's product_id must be producible by at least one plant.
     Since we don't have a product-plant mapping table in the basic spec, assume all plants can make
     all products UNLESS the data shows otherwise. Log a warning if product_ids are found that don't
     appear in any order.

  2. **Transport Route Completeness**: For every unique (plant_id, destination) pair needed by orders,
     verify that a matching row exists in transport_duties. Query:
     `SELECT DISTINCT destination FROM orders` cross-joined with
     `SELECT DISTINCT plant_id FROM plants`, then check each pair exists in transport_duties.
     Report missing pairs.

  3. **Positive Capacity Check**: All plant capacities must be > 0.

  4. **Due Date Validity**: All order due_dates must be >= today's date (the planning start date).
     If some are in the past, flag them but do not crash.

  5. **Carbon Intensity Unit Check**: Verify carbon_intensity values are within reasonable range
     (0 to 100 kg CO2e/unit). Flag outliers.

  6. **Row Count Summary**: Report counts of orders, plants, transport routes, and capacity events.

  7. **Capacity Event Validity**: If capacity_events table has rows, verify that the plant_id
     references exist in the plants table and that capacity_reduction_pct is between 0 and 1.

---

### FILE 9: `src/solver.py` -- THIS IS THE MOST CRITICAL FILE
PURPOSE: The deterministic mathematical optimization engine. Uses PuLP to solve a
Mixed-Integer Linear Programming (MILP) problem that assigns orders to plants.

THIS FILE MUST BE EXTREMELY WELL-COMMENTED because judges will inspect it line by line.

IMPLEMENTATION DETAILS:

#### Data Loading Helper:
- Function `load_solver_data(conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]`:
  Reads orders, plants, transport_duties, capacity_events from SQLite into pandas DataFrames.

#### Landed Cost Calculation (Requirement R2):
- Function `calculate_landed_cost(plant_row, transport_row) -> float`:
  ```
  landed_cost_per_unit = plant.unit_cost + plant.energy_price + transport.transport_cost + transport.import_duty
  ```
  Returns the per-unit landed cost.

#### Carbon Calculation (Requirement R3):
- Function `calculate_carbon_per_unit(plant_row, transport_row) -> float`:
  ```
  carbon_per_unit = plant.carbon_intensity + transport.transport_carbon
  ```
  Returns kg CO2e per unit.

#### Delivery Check (Requirement R5):
- Function `check_delivery(order_due_date, transit_days, planning_start_date) -> tuple[str, bool, int]`:
  ```
  arrival_date = planning_start_date + timedelta(days=transit_days)
  late_days = max(0, (arrival_date - due_date).days)
  on_time = (late_days == 0)
  ```
  Returns (arrival_date_iso_string, on_time_bool, late_days_int).

#### Main Solver Function (Requirements R4, R6, R7):
- Function `solve_allocation(conn, weights: dict = None, scenario: dict = None,
  baseline_allocation: dict = None, planning_start_date: str = None) -> dict`:

  DETAILED STEP-BY-STEP IMPLEMENTATION:

  Step 1: Load data from SQLite.
  ```python
  df_orders, df_plants, df_transport, df_events = load_solver_data(conn)
  ```

  Step 2: Apply capacity events (disruption scenario).
  - If `scenario` parameter is provided (e.g., {"plant_id": "B", "capacity_reduction_pct": 0.30}),
    apply it to the plants DataFrame: `effective_capacity = capacity * (1 - reduction_pct)`.
  - Also apply any active events from the capacity_events table whose date range overlaps
    the planning_start_date.

  Step 3: Set default weights if not provided.
  ```python
  w_cost = weights.get("cost", 0.7) if weights else 0.7
  w_carbon = weights.get("carbon", 0.3) if weights else 0.3
  w_late = weights.get("lateness", 0.0) if weights else 0.0
  ```

  Step 4: Pre-compute the cost matrix and carbon matrix.
  - For every (order_i, plant_j) pair, compute:
    - `cost_matrix[i][j]` = landed_cost_per_unit (using calculate_landed_cost)
    - `carbon_matrix[i][j]` = carbon_per_unit (using calculate_carbon_per_unit)
    - `delivery_info[i][j]` = (arrival_date, on_time, late_days) (using check_delivery)
  - If a transport route is missing for a pair, set cost to a very large number (1e9)
    to effectively prohibit that assignment.

  Step 5: Compute normalization baselines.
  - `cost_baseline` = sum of (cheapest plant cost * quantity) for each order
    (i.e., the cost if we always pick the cheapest plant ignoring capacity).
  - `carbon_baseline` = sum of (greenest plant carbon * quantity) for each order.
  - If either baseline is 0, set to 1.0 to avoid division by zero.

  Step 6: Create the PuLP optimization problem.
  ```python
  prob = pulp.LpProblem("Order_Allocation", pulp.LpMinimize)
  ```

  Step 7: Create decision variables.
  ```python
  # x[i][j] = quantity of order i assigned to plant j (continuous or integer)
  x = {}
  for i, order in df_orders.iterrows():
      for j, plant in df_plants.iterrows():
          x[order.order_id, plant.plant_id] = pulp.LpVariable(
              f"x_{order.order_id}_{plant.plant_id}",
              lowBound=0,
              upBound=order.quantity,
              cat="Integer"  # Integer for non-splittable orders
          )

  # s[i] = unfulfilled slack for order i (elastic variable to prevent infeasibility crash)
  s = {}
  for i, order in df_orders.iterrows():
      s[order.order_id] = pulp.LpVariable(
          f"slack_{order.order_id}", lowBound=0, cat="Continuous"
      )

  # u[i] = lateness indicator for order i
  u = {}
  for i, order in df_orders.iterrows():
      u[order.order_id] = pulp.LpVariable(
          f"late_{order.order_id}", lowBound=0, upBound=1, cat="Binary"
      )
  ```

  Step 8: Define the objective function.
  ```python
  total_cost_expr = pulp.lpSum([
      cost_matrix[order.order_id][plant.plant_id] * x[order.order_id, plant.plant_id]
      for i, order in df_orders.iterrows()
      for j, plant in df_plants.iterrows()
  ])

  total_carbon_expr = pulp.lpSum([
      carbon_matrix[order.order_id][plant.plant_id] * x[order.order_id, plant.plant_id]
      for i, order in df_orders.iterrows()
      for j, plant in df_plants.iterrows()
  ])

  total_late_penalty = pulp.lpSum([
      u[order.order_id] * 10000  # High penalty per late order
      for i, order in df_orders.iterrows()
  ])

  total_slack_penalty = pulp.lpSum([
      s[order.order_id] * 1000000  # Very high penalty for unfulfilled demand
      for i, order in df_orders.iterrows()
  ])

  # Churn penalty (only active during re-planning with a baseline)
  churn_penalty = 0
  if baseline_allocation:
      churn_vars = {}
      for i, order in df_orders.iterrows():
          for j, plant in df_plants.iterrows():
              key = (order.order_id, plant.plant_id)
              baseline_qty = baseline_allocation.get(key, 0)
              churn_vars[key] = pulp.LpVariable(f"churn_{key[0]}_{key[1]}", lowBound=0)
              prob += churn_vars[key] >= x[key] - baseline_qty
              prob += churn_vars[key] >= baseline_qty - x[key]
      churn_penalty = pulp.lpSum(churn_vars.values()) * 100  # Moderate churn penalty

  # Combined normalized objective
  prob += (
      w_cost * (total_cost_expr / max(cost_baseline, 1)) +
      w_carbon * (total_carbon_expr / max(carbon_baseline, 1)) +
      w_late * total_late_penalty +
      total_slack_penalty +
      churn_penalty
  )
  ```

  Step 9: Add constraints.
  ```python
  # Constraint 1: Demand satisfaction (each order must be fulfilled or slacked)
  for i, order in df_orders.iterrows():
      prob += (
          pulp.lpSum([x[order.order_id, plant.plant_id] for j, plant in df_plants.iterrows()])
          + s[order.order_id] == order.quantity,
          f"demand_{order.order_id}"
      )

  # Constraint 2: Plant capacity limits (with disruption applied)
  for j, plant in df_plants.iterrows():
      effective_cap = plant.effective_capacity  # Already adjusted for disruptions
      prob += (
          pulp.lpSum([x[order.order_id, plant.plant_id] for i, order in df_orders.iterrows()])
          <= effective_cap,
          f"capacity_{plant.plant_id}"
      )

  # Constraint 3: Lateness indicator linking
  # If order i is assigned to plant j where late_days > 0, then u[i] = 1
  for i, order in df_orders.iterrows():
      for j, plant in df_plants.iterrows():
          arrival, on_time, late_days = delivery_info[order.order_id][plant.plant_id]
          if not on_time:
              prob += (
                  x[order.order_id, plant.plant_id] <= order.quantity * (1 - u[order.order_id]) + order.quantity,
                  f"late_link_{order.order_id}_{plant.plant_id}"
              )
  ```

  Step 10: Solve the problem.
  ```python
  solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=5)
  prob.solve(solver)
  ```

  Step 11: Extract results into the Section 6.1 response schema.
  - For each order, find which plant got the allocation (x[i,j].varValue > 0).
  - Build the `allocation` list of AllocationItem dicts.
  - Compute KPIs: total_cost, total_carbon_t (divide kg by 1000), late_orders count,
    plant_utilisation (sum allocated to plant / effective_capacity).
  - Compute unfulfilled_orders from slack variables where s[i].varValue > 0.
  - Determine answer_type: "allocation" if all orders fulfilled, "infeasible" if any slack > 0.
  - Return the complete result dictionary matching AnalyzeResponse schema.

#### Pareto Frontier Sweeper (Requirement R6, R11):
- Function `generate_pareto_frontier(conn, scenario=None, num_points=11) -> list[dict]`:
  - Sweeps weight from w_cost=1.0/w_carbon=0.0 to w_cost=0.0/w_carbon=1.0 in `num_points` steps.
  - For each weight setting, calls `solve_allocation()` with those weights.
  - Returns a list of TradeoffPoint dicts: [{carbon_cut_pct, cost, late_orders}, ...].
  - The `carbon_cut_pct` is calculated relative to the w_cost=1.0 baseline:
    `carbon_cut_pct = (baseline_carbon - this_carbon) / baseline_carbon * 100`.

#### Explain Order Choice (Innovation: Explainable Counterfactuals):
- Function `explain_order_choice(conn, order_id: str, current_allocation: dict) -> dict`:
  - For the given order_id, compute landed cost and carbon at ALL 3 plants.
  - Return a dict showing: chosen_plant, chosen_cost, chosen_carbon,
    and for each alternative plant: cost_delta, carbon_delta, transit_days, on_time status,
    and a human-readable reason string (e.g., "Plant A is $2,400 cheaper but misses deadline by 2 days").

#### SLA Carbon Arbitrage (Innovation: Delay for Carbon Savings):
- Function `evaluate_carbon_arbitrage(conn, order_id: str, max_extra_days: int = 2) -> dict`:
  - For the given order, check if allowing `max_extra_days` additional transit time opens up
    a greener plant option (lower carbon) that was previously excluded due to deadline.
  - Return: original_plant, original_carbon, alternative_plant, alternative_carbon,
    carbon_savings_pct, extra_days_needed.

---

### FILE 10: `src/guardrails.py`
PURPOSE: The Zero-Hallucination Interceptor. Verifies that every number in the LLM-generated
brief text matches a number from the solver output. If a mismatch is found, replaces the
LLM text with a safe deterministic template.

IMPLEMENTATION DETAILS:
- Function `extract_numbers_from_text(text: str) -> set[float]`:
  - Use regex pattern `r'[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.?\d*'` to find all numbers.
  - Convert each match to float (remove commas first).
  - Filter out obvious non-metric numbers: years (2024-2030), small integers that could be
    list indices or section numbers (0, 1, 2, 3 unless they appear with units like "2 days").
  - Return set of extracted floats.

- Function `extract_numbers_from_solver_output(solver_result: dict) -> set[float]`:
  - Recursively walk the solver_result dict and extract all numeric values.
  - Include: total_cost, total_carbon_t, late_orders, plant_utilisation values,
    individual allocation costs, carbon_kg values, carbon_cut_pct values, etc.
  - Also include common derived values: total_cost / 1000, total_cost / 1000000
    (since briefs often say "1.84M" instead of "1840000").
  - Return set of all valid reference numbers.

- Function `verify_brief(brief_text: str, solver_result: dict) -> tuple[bool, list[float]]`:
  - Extract numbers from brief_text.
  - Extract reference numbers from solver_result.
  - For each number in the brief, check if it exists in the reference set
    (with a tolerance of 0.5% to handle rounding: `abs(a - b) / max(abs(b), 1e-9) < 0.005`).
  - Return (all_verified: bool, unverified_numbers: list).

- Function `generate_deterministic_brief(solver_result: dict) -> str`:
  - A SAFE FALLBACK that uses pure Python f-strings with NO LLM involvement.
  - Template:
    ```
    f"Allocation Summary: Total landed cost is ${kpis['total_cost']:,.2f}. "
    f"Total carbon emissions are {kpis['total_carbon_t']:.1f} tonnes CO2e. "
    f"{kpis['late_orders']} order(s) are projected to arrive late. "
    f"Plant utilization: Plant A at {kpis['plant_utilisation']['A']*100:.0f}%, "
    f"Plant B at {kpis['plant_utilisation']['B']*100:.0f}%, "
    f"Plant C at {kpis['plant_utilisation']['C']*100:.0f}%."
    ```
  - If answer_type is "infeasible", add: "WARNING: Not all orders can be fulfilled with
    current capacity. {unfulfilled_count} orders remain unallocated."

- Function `guardrail_check(brief_text: str, solver_result: dict) -> str`:
  - Calls verify_brief(). If passed, returns the original brief_text.
  - If failed, logs a warning with the unverified numbers, and returns
    generate_deterministic_brief(solver_result) instead.

---

### FILE 11: `src/agents/brief_writer.py`
PURPOSE: The LLM-powered brief generation agent. Takes solver output and writes
an executive leadership brief in plain English.

IMPLEMENTATION DETAILS:
- Function `get_llm()`:
  - If `settings.MOCK_LLM` is True, return None (we will use the deterministic template).
  - If `settings.LLM_PROVIDER` == "gemini", initialize and return a ChatGoogleGenerativeAI
    with model=settings.LLM_MODEL and api_key=settings.GEMINI_API_KEY.

- Function `generate_brief(solver_result: dict, user_query: str) -> str`:
  - If MOCK_LLM is True, immediately return `generate_deterministic_brief(solver_result)`.
  - Otherwise, construct a prompt:
    ```
    SYSTEM: You are a supply chain analyst writing a brief for senior leadership.
    You MUST use ONLY the numbers provided below. Do NOT compute, estimate, or invent
    any numbers. Every figure in your brief must come directly from the data below.

    SOLVER OUTPUT DATA:
    {json.dumps(solver_result, indent=2)}

    USER REQUEST: {user_query}

    Write a concise 1-paragraph executive summary covering:
    1. Total landed cost and total carbon emissions
    2. Number of late orders and overall on-time delivery rate
    3. Plant utilization percentages
    4. If this is a re-plan, what changed from the previous plan
    5. Key trade-off: what would it cost to reduce carbon by 10%

    Use only the numbers above. Do not add any numbers not present in the data.
    ```
  - Call the LLM with this prompt.
  - Return the LLM's response text.

- Function `generate_explanation(solver_result: dict, order_id: str, counterfactuals: dict) -> str`:
  - If MOCK_LLM, return a template string explaining the order choice.
  - Otherwise, prompt the LLM with the counterfactual data:
    ```
    Explain why order {order_id} was assigned to Plant {chosen_plant}.
    Here are the alternatives:
    {json.dumps(counterfactuals)}
    Use ONLY these numbers. Mention cost, carbon, transit time, and capacity.
    ```

---

### FILE 12: `src/graph.py`
PURPOSE: The LangGraph state machine orchestrator. This is the central brain that
routes user requests through the 5-step pipeline.

IMPLEMENTATION DETAILS:

- Define the graph state as a TypedDict:
  ```python
  class GraphState(TypedDict):
      user_query: str
      weights: Optional[dict]
      scenario: Optional[dict]
      intent: Optional[str]        # allocation, scenario, brief, explain, etc.
      solver_result: Optional[dict]
      baseline_allocation: Optional[dict]
      brief_text: Optional[str]
      final_response: Optional[dict]
      trace_steps: list[dict]
      run_id: str
  ```

- **Node 1: `parse_intent`**
  - If MOCK_LLM is True:
    Use keyword matching to determine intent:
    - Contains "allocat" or "plan" or "assign" -> intent = "allocation"
    - Contains "Plant" and ("loses" or "lost" or "capacity" or "drop") -> intent = "capacity_replan"
    - Contains "compare" or "what if" or "what-if" or "scenario" -> intent = "scenario"
    - Contains "brief" or "leadership" or "management" or "summary" -> intent = "brief"
    - Contains "why" and "order" -> intent = "explain"
    - Contains "cheapest" or "cheap" -> intent = "cheapest_plan"
    - Contains "carbon cut" or "carbon reduc" -> intent = "carbon_tradeoff"
    - Otherwise -> intent = "allocation" (default)
  - If MOCK_LLM is False:
    Use the LLM with function calling / structured output to extract:
    - intent (one of the above strings)
    - any mentioned plant_id and capacity_reduction_pct for scenario
    - any mentioned order_id for explain queries
    - any mentioned weight preferences
  - Record this step in trace_steps with timestamp and duration.

- **Node 2: `run_solver`**
  - Based on intent:
    - "allocation" or "cheapest_plan": Call `solve_allocation(conn, weights=state["weights"])`
    - "capacity_replan": Call `solve_allocation(conn, weights=state["weights"],
      scenario=state["scenario"], baseline_allocation=state.get("baseline_allocation"))`
    - "scenario" / "carbon_tradeoff": Call `generate_pareto_frontier(conn)` and also
      `solve_allocation()` for the specific scenario.
    - "brief": Call `solve_allocation(conn, weights=state["weights"])` to get fresh numbers.
    - "explain": Call `solve_allocation()` then `explain_order_choice()`.
  - Store solver_result in state.
  - Record step in trace.

- **Node 3: `validate_output`**
  - Run `validate_data(conn)` to verify data integrity.
  - Check that solver_result satisfies:
    - No plant exceeded its effective capacity.
    - All allocated quantities are non-negative.
    - Sum of allocations + slack = order quantity.
  - Set validator field: capacity_ok, eligibility_ok.
  - Record step in trace.

- **Node 4: `generate_brief_node`**
  - Call `generate_brief(solver_result, user_query)` from brief_writer.
  - Store brief_text in state.
  - Record step in trace (include LLM token count if available).

- **Node 5: `guardrail_check_node`**
  - Call `guardrail_check(brief_text, solver_result)` from guardrails module.
  - If guardrail returns a different text (deterministic fallback was triggered), log it.
  - Build the final_response dict matching AnalyzeResponse schema.
  - Set the `summary` field to the guardrail-verified brief text.
  - Save the complete run (request, response, trace) to the `runs` table in SQLite.
  - Record step in trace.

- **Build the LangGraph**:
  ```python
  from langgraph.graph import StateGraph, END

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
  ```

- Provide a convenience function:
  ```python
  def run_workflow(user_query: str, weights: dict = None,
                   scenario: dict = None) -> dict:
      run_id = f"run-{uuid.uuid4().hex[:8]}"
      initial_state = {
          "user_query": user_query,
          "weights": weights,
          "scenario": scenario,
          "intent": None,
          "solver_result": None,
          "baseline_allocation": None,
          "brief_text": None,
          "final_response": None,
          "trace_steps": [],
          "run_id": run_id,
      }
      result = app.invoke(initial_state)
      return result["final_response"]
  ```

---

### FILE 13: `src/api.py`
PURPOSE: FastAPI application with all mandatory endpoints per Section 6.

IMPLEMENTATION DETAILS:

```python
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json, uuid
from src.models import AnalyzeRequest, AnalyzeResponse, IngestResponse, HealthResponse, TraceResponse
from src.data_loader import ingest_csv
from src.database import get_connection
from src.graph import run_workflow
from src.config import settings

app = FastAPI(title="Multi-Plant Order Allocation API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health_check():
    conn = get_connection()
    db_status = "ready"
    try:
        conn.execute("SELECT 1")
    except Exception:
        db_status = "error"
    llm_status = "mock_mode" if settings.MOCK_LLM else "ready"
    return {"api": "ready", "database": db_status, "llm": llm_status}

@app.post("/ingest")
async def ingest_data(file: UploadFile = File(...), table_name: str = Form(...)):
    if table_name not in ["orders", "plants", "transport_duties", "capacity_events"]:
        raise HTTPException(status_code=400, detail=f"Invalid table_name: {table_name}")
    file_bytes = await file.read()
    conn = get_connection()
    result = ingest_csv(file_bytes, table_name, conn)
    return {
        "status": "success" if result["rows_rejected"] == 0 else "partial",
        "rows_loaded": {table_name: result["rows_loaded"]},
        "rows_rejected": {table_name: result["rows_rejected"]},
        "validation_errors": result.get("validation_errors", [])
    }

@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    result = run_workflow(
        user_query=request.request,
        weights=request.weights,
        scenario=request.scenario
    )
    return result

@app.get("/trace/{run_id}")
def get_trace(run_id: str):
    conn = get_connection()
    row = conn.execute("SELECT trace_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return json.loads(row["trace_json"])
```

---

### FILE 14: `ui/app.py`
PURPOSE: Streamlit dashboard with Pareto sliders, disruption simulator, allocation table,
trade-off chart, and executive brief viewer.

IMPLEMENTATION DETAILS:
- Use `st.set_page_config(page_title="Plant Allocation Optimizer", layout="wide")`
- API_URL defaults to `http://localhost:8000`

**Sidebar Controls**:
- `st.sidebar.header("Controls")`
- Weight sliders: `cost_weight = st.sidebar.slider("Cost Weight", 0.0, 1.0, 0.7, 0.05)`
  and `carbon_weight = 1.0 - cost_weight` (linked).
- Disruption panel: `st.sidebar.subheader("Disruption Simulator")`
  - Plant selector dropdown (A, B, C).
  - Capacity reduction slider (0% to 100%).
  - "Trigger Disruption" button.
- CSV File Uploader: `st.sidebar.file_uploader("Upload CSV", type=["csv"])`
  with table name selector and "Upload" button. On click, POST to /ingest.

**Main Dashboard**:
- Title: `st.title("Multi-Plant Order Allocation Optimizer")`
- Health check badge: Call GET /health and display status.
- "Generate Plan" button. On click, POST to /analyze with:
  ```json
  {"request": "Allocate all orders", "weights": {"cost": cost_weight, "carbon": carbon_weight}}
  ```
- Display results in 4 columns:
  - Col 1: `st.metric("Total Cost", f"${kpis['total_cost']:,.0f}")`
  - Col 2: `st.metric("Carbon (tonnes)", f"{kpis['total_carbon_t']:.1f}")`
  - Col 3: `st.metric("Late Orders", kpis['late_orders'])`
  - Col 4: `st.metric("On-Time Rate", f"{on_time_pct:.1f}%")`

- Plant utilization bar chart using plotly.

- **Pareto Trade-Off Chart** (Requirement R11):
  - Use plotly scatter plot: X-axis = Total Cost, Y-axis = Total Carbon (tonnes).
  - Each point is a different weight setting from the tradeoff array.
  - Annotate the current plan's position with a larger marker.
  - `st.plotly_chart(fig, use_container_width=True)`

- **Allocation Table**: `st.dataframe(pd.DataFrame(allocation_list))` with columns:
  Order ID, Plant, Cost, Carbon (kg), Arrival Date, On Time.

- **Executive Brief**: `st.markdown(summary)` inside an `st.expander("Leadership Brief")`.

- **Query Box**: `st.text_input("Ask a question")` with a submit button.
  On submit, POST to /analyze with the query text.

- **Trace Inspector**: `st.expander("Audit Trace")` showing the step-by-step trace.

---

### FILE 15: `data/orders.csv` (SYNTHETIC TEST DATA)
Generate exactly 150 orders with these properties:
- order_id: O-001 through O-150
- product_id: randomly from [P-Alpha, P-Beta, P-Gamma, P-Delta]
- quantity: random integers between 50 and 2000
- destination: randomly from at least 12 destinations:
  [Berlin, London, Paris, Tokyo, Chicago, Mumbai, Sydney, Toronto, Dubai, Sao_Paulo, Shanghai, Mexico_City]
- due_date: dates between 2026-10-15 and 2026-11-15 in ISO format
- priority: random integers 1-5

IMPORTANT EDGE CASES TO INCLUDE:
- At least 3 orders where the cheapest plant is late (set tight due_dates with distant destinations).
- At least 1 order where product_id is P-Delta which only Plant A can make (for eligibility testing).
- Total demand should slightly exceed total capacity (e.g., total quantity around 16000 against
  combined capacity around 14500) to test infeasibility handling.

---

### FILE 16: `data/plants.csv`
```csv
plant_id,capacity,unit_cost,energy_price,carbon_intensity
A,6000,18.50,3.20,12.4
B,5000,22.00,2.80,8.6
C,3500,25.00,4.10,3.2
```
Note: Plant A is cheapest but dirtiest, Plant C is cleanest but most expensive with least capacity.

---

### FILE 17: `data/transport_duties.csv`
Generate for all 3 plants x 12 destinations = 36 rows.
- Columns: plant_id, destination, transport_cost, transit_days, import_duty, transport_carbon
- Ensure:
  - Plant A has short transit to Berlin (2 days) but long to Tokyo (12 days).
  - Plant B has short transit to London (2 days) and moderate everywhere else.
  - Plant C has moderate transit everywhere (4-7 days).
  - Import duties vary: some destinations have 0 duty from certain plants (domestic),
    others have 3-8 dollar duty (international cross-border).
  - Transport carbon correlates with distance (longer transit = more emissions).

---

### FILE 18: `data/capacity_events.csv`
```csv
event_id,plant_id,capacity_reduction_pct,start_date,end_date,reason
EV-01,B,0.30,2026-10-15,2026-10-29,Boiler maintenance
```

---

### FILE 19: `data/DATA_CARD.md`
Document how the synthetic data was generated:
- Generation method: Scripted random generation with controlled edge cases.
- Number of records: 150 orders, 3 plants, 36 transport routes, 1 capacity event.
- Edge cases seeded: 3 cheapest-is-late orders, 1 single-plant product, demand > capacity.
- No real company data was used.

---

### FILE 20: `tests/conftest.py`
Provide pytest fixtures:
- `test_conn`: Creates an in-memory SQLite database with sample test data (5 orders, 3 plants,
  9 transport routes).
- `sample_solver_result`: Returns a pre-computed solver result dict for guardrail testing.

---

### FILE 21: `tests/test_evaluation.py`
PURPOSE: The mandatory 20-case evaluation test suite (Section 7).

Implement these 20 test cases using pytest:

1-3: `test_cheapest_plant_late_1/2/3` - Orders where cheapest plant misses deadline.
     Assert that solver picks on-time plant instead.
4-6: `test_capacity_loss_scenario_1/2/3` - Apply 30%, 50%, and dual-plant capacity drops.
     Assert solver returns valid allocation within reduced capacity.
7-8: `test_infeasible_demand_1/2` - Set demand > total capacity.
     Assert answer_type == "infeasible" and slack variables identify shortfall.
9-12: `test_weight_sensitivity_1/2/3/4` - Test w_cost=1.0, w_carbon=1.0, 50/50, and 70/30.
      Assert different weight settings produce different allocations.
13-14: `test_hallucination_injection_1/2` - Feed solver result to guardrail with a brief
       containing a fabricated number. Assert guardrail replaces it.
15: `test_product_eligibility` - Order with single-plant product assigned correctly.
16: `test_tariff_trap` - Order where import duty flips cheapest plant.
17: `test_green_plant_saturation` - Plant C fills to 100% capacity.
18: `test_validator_catches_bad_data` - Negative quantity rejected during ingestion.
19: `test_api_health_endpoint` - GET /health returns 200.
20: `test_full_pipeline_latency` - Run full solve on 150 orders; assert < 5 seconds.

---

### FILE 22: `Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000 8501
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### FILE 23: `docker-compose.yml`
```yaml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - sqlite_data:/app/db
    command: uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload

  ui:
    build: .
    ports:
      - "8501:8501"
    env_file:
      - .env
    depends_on:
      - api
    command: streamlit run ui/app.py --server.port 8501 --server.address 0.0.0.0

volumes:
  sqlite_data:
```

---

## CRITICAL IMPLEMENTATION RULES

1. EVERY file must have detailed docstrings and inline comments explaining the logic.
2. ALL imports must be at the top of each file. No circular imports.
3. The solver MUST use elastic slack variables so it NEVER crashes on infeasible input.
4. The guardrail MUST catch fabricated numbers. Test it with intentionally wrong numbers.
5. MOCK_LLM=true must make the ENTIRE system work without any API keys.
6. All dates must use ISO-8601 format (YYYY-MM-DD).
7. The Pareto frontier must have at least 11 points.
8. Plant utilization must be calculated as: (total_allocated_to_plant / effective_capacity).
9. The trace must record: step_name, input summary, output summary, duration_ms, timestamp.
10. Error handling: Never return HTTP 500. Catch exceptions and return meaningful error messages.

## CODE QUALITY REQUIREMENTS
- Type hints on ALL function signatures.
- Docstrings on ALL functions (Google-style).
- No hardcoded magic numbers without named constants.
- Consistent naming: snake_case for functions/variables, PascalCase for classes.
- Each file should be independently testable.
