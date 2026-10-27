# Executed verification report

Executed on 27 October 2026, Python 3.12.14, Linux.

## Results

- Initial dependency check: pytest was unavailable. Installed requirements.
- First baseline: **176 passed, 13 failed**. Failures were caused by this environment's
  SOCKS proxy configuration and missing `socksio` dependency.
- Installed socksio; untouched-source baseline: **189 passed**, one deprecated-query warning.
- Final integrated suite: **224 passed, 0 failed**, 6.20 seconds. See test-results.txt.
- Actual uvicorn startup + localhost GET /api/v1/live/status: **HTTP 200**.
- Example environment configuration loaded successfully.
- Python compileall: success. Frontend JavaScript `node --check`: success.
- Offline synthetic demo: passed full ingestion → classification → geometric
  matching → R6 → AT_RISK → unconfirmed feasibility → same-destination Cape alternative.
- Nine synthetic API response captures: all HTTP 200 (api-samples.json).
- Original database: byte-identical to uploaded archive. Two migrations and a full
  offline pipeline on a temporary copy preserved row hashes across all **13 Model 1
  tables**, including 4 trade records and 6 sanctions records (preservation.json).
- Live GDELT: **not verified**. One real bounded request returned HTTP 503 with
  upstream connection timeout. See gdelt-connectivity.txt. No fabricated live sample.
- Local Ollama: unavailable; deterministic fallback and malformed/unsupported model
  output rejection tested. Actual model inference remains unverified.
- Frontend application: absent from upload. Component syntax checked, not browser-tested.

## Commands actually executed

```
python --version
python -m pip install -r requirements.txt
python -m pytest -q
python -m pip install socksio
python -m pytest -q
python -m scripts.model2_demo --reset
python -m scripts.capture_model2_evidence
python -m compileall -q app scripts
node --check frontend-integration/minetrace-monitor.js
```

Additional executed Python probes: GdeltClient.fetch_articles with query
`"mineral" "disruption"`, 24h, max_records=5, timeout=8 and zero retries; byte/hash
comparison against the original ZIP; SQLite copy migration twice followed by offline
pipeline; Settings(_env_file='.env.example'); and subprocess uvicorn on port 18761
with a temporary database followed by a real local HTTP request and clean shutdown.

## Coverage and fixes

Original tests cover R1–R5, trade/sanctions ingestion, historical APIs, evidence,
classification/ranking, PDF reports and existing RAG. Provider tests simulate success,
empty response, connection failure, timeout, 429, 5xx and invalid JSON. Ingestion tests
cover deduplication, categories, rollback and Model 1 preservation.

New acceptance tests cover date-line and interior-segment distance, invalid geometry,
ambiguous country/publisher separation, unsupported official claims, UTC conversion,
unsafe URL schemes, cross-worker lease, duplicate periodic-run suppression, offline
network isolation, degraded cached operation, route-specific advisory expiration,
same-destination alternatives, missing alternatives, additive migration, full APIs,
route import validation/token checks, synthetic-data isolation, safe default route
status, LLM claim rejection, configurable-policy validation and scheduler lifecycle.

Four original unsafe behavioral expectations were intentionally corrected: no-alert
routes were treated as commercially verified; official headlines were treated as route
closures; unrelated regional reports were merged/corroborated; and confirmed events
were treated as confirmed route impacts. Fixture provenance expectation was also
updated to synthetic_fixture. These are specification corrections, not disabled tests.

No historical risk formulas were changed. Existing Ollama generate() referenced an
undefined `endpoint`; the compatibility fix now uses base_url + /api/generate.

## Remaining acceptance limitations

Live-provider success, carrier operations, legal clearance, global incident detection,
authoritative automatic source verification, precise incident geolocation, operational
route dataset accuracy, actual Ollama inference and actual frontend/browser integration
cannot be certified from this environment/data. Refer to README_MODEL2.md for the
explicit behavior and limits. Synthetic/API outputs establish reproducible backend
functionality, not real-world shipment availability.
