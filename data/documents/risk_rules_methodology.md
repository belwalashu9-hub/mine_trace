# MineTrace Risk Rules Methodology

## Overview
MineTrace applies a deterministic, explainable multi-rule anomaly detection engine designed for critical mineral supply-chain integrity and trade route monitoring. The engine evaluates five core risk rules (R1 through R5), assigns objective numerical anomaly scores (0 to 100), and screens for sanctions exposure.

## Rule Definitions

### Rule R1: Mirror Trade Gap (Weight: 30)
- **Objective**: Detects significant reporting discrepancies between export values declared by the exporting country and corresponding import values declared by the destination partner.
- **Formula**: `abs(export_value - import_value) / max(export_value, import_value) * 100`
- **Threshold**: Anomaly is flagged when `mirror_gap_percentage > 30.0%`.
- **Sufficiency**: Requires valid, positive values for both export and import. If either value is missing, the rule outcome is `INSUFFICIENT_DATA`.

### Rule R2: Volume Spike (Weight: 20)
- **Objective**: Detects unusually sharp surges in trade volume compared to a valid baseline period, which may indicate sudden transshipment or corridor redirection.
- **Formula**: `(current_volume - previous_volume) / previous_volume * 100`
- **Threshold**: Anomaly is flagged when `volume_change_percentage > 200.0%`.
- **Sufficiency**: Requires historical trade volume in the immediate baseline period.

### Rule R3: Route Concentration (Weight: 30)
- **Objective**: Measures bilateral import dependency and supplier dominance.
- **Formula**: `partner_import_volume / total_comparable_import_volume * 100`
- **Threshold**: Anomaly is flagged when bilateral concentration exceeds `80.0%`.
- **Sufficiency**: Applicable to import flows with comparable commodity import records.

### Rule R4: Unusual Unit Price (Weight: 20)
- **Objective**: Detects transfer mispricing, trade-based money laundering (TBML), or tariff circumvention by comparing FOB/CIF unit prices ($/kg) against peer transaction distributions.
- **Formula**: `abs(unit_price - median_price) / median_price * 100`
- **Threshold**: Anomaly is flagged when unit price deviates by more than `60.0%` from the peer median.
- **Sufficiency**: Requires a minimum sample size of 3 comparable transactions.

### Rule R5: Sanctions Exposure Status (Weight: 0, Screening Only)
- **Objective**: Cross-references involved corporate entities, trading intermediaries, or shipping consignees against official US Treasury Office of Foreign Assets Control (OFAC) Specially Designated Nationals (SDN) lists.
- **Outcomes**: `REVIEW_MATCH` (exact or token similarity > 0.85), `NO_IDENTIFIED_MATCH`, or `UNKNOWN`.
- **Scoring**: R5 is deliberately excluded from the numerical anomaly score (weight 0) to avoid masking or conflating empirical trade divergence with legal sanctions classifications.
