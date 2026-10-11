# Data Card: Synthetic Manufacturing & Logistics Dataset

## 1. Overview
This synthetic dataset models a global multi-plant order fulfillment scenario for the **HCLTech Future Ready AI Engineer Hackathon**. It establishes manufacturing capacities, customer orders, shipping tariffs, and disruption schedules to benchmark linear programming optimization models.

No proprietary or real company data was used in the synthesis of this dataset.

---

## 2. Dataset Files & Summaries

### `data/plants.csv` (3 records)
- **Plant A**: High capacity (6,000 units), lowest unit production cost ($18.50 + $3.20 energy), highest carbon intensity (12.4 kg CO2e/unit). Located closer to European destinations.
- **Plant B**: Medium capacity (5,000 units), moderate unit cost ($22.00 + $2.80 energy), moderate carbon intensity (8.6 kg CO2e/unit). Fast transit to UK/Western Europe.
- **Plant C**: Lower capacity (3,500 units), premium unit cost ($25.00 + $4.10 energy), lowest carbon intensity (3.2 kg CO2e/unit). Fast global express transit to Asia-Pacific and the Americas.

### `data/orders.csv` (150 records)
- **Total Demand**: 16,192 units (intentionally exceeds combined 14,500 plant capacity by ~11% to benchmark elastic slack and infeasibility handling).
- **Products**: `P-Alpha`, `P-Beta`, `P-Gamma`, `P-Delta`.
- **Destinations**: 12 global destinations across Europe, the Americas, Asia, and Oceania:
  `Berlin`, `London`, `Paris`, `Tokyo`, `Chicago`, `Mumbai`, `Sydney`, `Toronto`, `Dubai`, `Sao_Paulo`, `Shanghai`, `Mexico_City`.
- **Order Quantities**: Range between 50 and 350 units.
- **Due Dates**: Spanning from 2026-10-15 to 2026-11-15.
- **Priorities**: 1 (highest) to 5 (lowest).

### `data/transport_duties.csv` (36 records)
- Complete matrix covering 3 plants × 12 destinations.
- Includes `transport_cost` ($/unit), `transit_days`, `import_duty` ($/unit), and `transport_carbon` (kg CO2e/unit).
- Tariffs and customs duties model domestic agreements ($0 duty) vs. cross-border trade ($2.00 – $7.00 duty).
- Carbon emissions correlate directly with transit distance.

### `data/capacity_events.csv` (1 record)
- Disruption event `EV-01`: Plant B loses 30% of effective capacity between 2026-10-15 and 2026-10-29 due to scheduled boiler maintenance.

---

## 3. Seeded Test Edge Cases

1. **Cheapest Plant Late Edge Cases (`O-001`, `O-002`, `O-003`)**:
   - `O-001` (Destination: Tokyo, Due: 2026-10-16): Plant A is cheapest on paper but requires 12 transit days (arriving late). Plant C requires only 4 transit days, fulfilling the order on time.
   - `O-002` (Destination: Sydney, Due: 2026-10-18): Plant A requires 14 transit days (late), whereas Plant C arrives within 6 transit days.
   - `O-003` (Destination: Shanghai, Due: 2026-10-16): Plant A requires 11 days (late), whereas Plant C requires 4 days (on time).
2. **Product Eligibility Constraint**:
   - `O-004` specifies product `P-Delta`, validating single-plant specialized tooling or eligibility rules.
3. **Capacity Overflow / Infeasibility**:
   - Combined demand (~16,192 units) exceeds combined capacity (14,500 units), testing elastic slack variables without numerical instability or solver crashes.
