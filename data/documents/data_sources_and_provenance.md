# Critical Mineral Data Sources & Provenance Architecture

## 1. UN Comtrade Trade Data Integration
MineTrace ingests official bilateral mineral flow data using standard Harmonized System (HS) commodity classifications:
- **HS 283691**: Lithium carbonates (battery-grade and technical-grade chemical feedstocks).
- **HS 282520**: Lithium hydroxide and oxide (high-nickel cathode precursor material).
- **HS 253090**: Other mineral substances, including mined spodumene concentrates and lithium-bearing pegmatites.
- **HS 850760**: Lithium-ion electric storage accumulators and battery packs.

### Data Cleaning and Quality Guardrails
- **Missing Value Preservation**: Missing physical weights (`net_weight_kg`) or quantities are preserved as `None` rather than converted to zero.
- **Deduplication Hashing**: Every normalized transaction generates a deterministic SHA-256 fingerprint from canonical business keys (`flow_type`, `commodity_code`, `reporter_country_code`, `partner_country_code`, `period`, `trade_value_usd`, `net_weight_kg`). Duplicate records are logged and discarded without altering historical totals.

## 2. OFAC Sanctions Screening Integration
MineTrace downloads and caches structured Specially Designated Nationals (SDN) data directly from the official US Department of the Treasury.
- **Offline Cache Resilience**: If Treasury endpoints experience network outages or rate limiting, the local system automatically falls back to verified cached snapshots.
- **Entity Matching**: Performs normalized tokenization, punctuation removal, and token Jaccard similarity to catch transliteration variations and obfuscated corporate aliases.
