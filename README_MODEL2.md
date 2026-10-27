# MineTrace Model 2 — near-real-time geopolitical monitoring

This ZIP contains the existing Model 1 backend and an integrated Model 2 backend.
Start here. Tested with **Python 3.12.14** on Linux. Windows commands are below;
Windows itself was not available for execution.

The uploaded ZIP already contained substantial Model 2 code. This delivery audits,
repairs and extends that code instead of discarding it. Model 1's UN Comtrade + OFAC
integrations, local SQLite storage, R1–R5 formulas and historical APIs are retained.

## Windows PowerShell setup

Extract the ZIP and open PowerShell in its `backend` directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-tested.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m scripts.migrate_model2
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The migration creates a timestamped SQLite backup, adds missing tables, and marks
exactly recognized legacy fixture articles as synthetic. It never deletes Model 1
records. The bundled `data/minetrace.db` is byte-identical to the uploaded database;
apply the migration locally before use. Stop the backend before restoring a backup.

Swagger: http://127.0.0.1:8000/docs

Linux/macOS: use `python3 -m venv .venv`, `.venv/bin/python -m pip ...`, then the
same module commands with `.venv/bin/python`. `requirements.txt` is the original
compatible-range dependency list; `requirements-tested.txt` pins the directly
installed versions used for verification (not a full transitive lockfile).

## Run an isolated, reproducible offline demo

In a separate terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.model2_demo --reset
$env:DATABASE_URL = "sqlite:///./data/model2_demo.sqlite"
$env:MODEL2_AUTO_SYNC = "false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

The demo writes only `data/model2_demo.sqlite` and `docs/demo-output.json`. `--reset`
removes only that fixed demo database, not the main database. Stop its server before
resetting. Remove the PowerShell DATABASE_URL override before restarting the normal
backend: `Remove-Item Env:DATABASE_URL`.

Demo flow: seed five labeled candidate corridors → baseline → synthetic news
article → classification → geometric matching → R6 → feasibility → Cape alternative.
The incident is **SYNTHETIC**, not real news or an official closure. Its outcome is
AT_RISK / POTENTIALLY_POSSIBLE_UNCONFIRMED. The route alternative reaches the same
stored destination. The fixed indexing date is intentional: recency scores may
change when the demo is run on later dates.

## Manual and automatic monitoring

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/live/sync?source=live"
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/live/sync?source=offline"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/live/status"
```

Live synchronization is synchronous in a FastAPI worker thread; allow the request
timeout to cover retries. Ordinary reads remain available. Offline mode never
fetches news; it reprocesses cached articles and rebuilds derived exposure results.
A failed fetch returns DEGRADED_CACHED and preserves previous data. Check the
returned `result.status`; HTTP 200 alone does not mean provider ingestion succeeded.

Set `MODEL2_AUTO_SYNC=true` in `.env` and restart to monitor every 15 minutes. Run
one designated scheduler worker. SQLite lease + periodic freshness checks prevent
concurrent/duplicate periodic work among processes sharing the same database.
A process crash leaves a bounded 15-minute lease; manual sync may return BUSY until
it expires. Shutdown waits for the bounded in-progress provider request to finish.
Independent database copies do not share coordination.

Important configuration:

| Variable | Default / purpose |
|---|---|
| DATABASE_URL | sqlite:///./data/minetrace.db |
| MODEL2_ENABLED | true; controls scheduler startup |
| MODEL2_AUTO_SYNC | false; explicitly enable live polling |
| MODEL2_SYNC_INTERVAL_MINUTES | 15; minimum effective interval 1 minute |
| MODEL2_MAX_ARTICLES_PER_RUN | 100; clamped to 1–250 |
| GDELT_TIMEOUT | 30 seconds; allowed 1–60 |
| GDELT_MAX_RETRIES | 3 retries; allowed 0–4 |
| GDELT_REQUEST_INTERVAL_SECONDS | 5.5; allowed 5.5–120 |
| GDELT_LOOKBACK_HOURS | 24 |
| GDELT_QUERY | optional custom DOC query; default mineral/chokepoint disruption search |
| MODEL2_REVIEW_TOKEN | required for route import, advisory and verification writes |
| MODEL2_ALLOW_DEMO_MODE | false; internal fixture scheduler gate; prefer isolated demo CLI |
| MODEL2_SEVERITY_WEIGHTS | optional JSON object, e.g. {"WAR":35,"PORT_CLOSURE":30} |
| MODEL2_RISK_THRESHOLDS | optional increasing JSON array; default [25,45,70] |
| OLLAMA_BASE_URL | http://localhost:11434 |
| OLLAMA_MODEL | llama3.2:latest |

GDELT DOC 2.0 requires **no API key**. No paid service is required. Ensure your
network can reach `https://api.gdeltproject.org/api/v2/doc/doc`. This environment's
live probe returned HTTP 503 (upstream connection timeout); live retrieval was not
verified. To retry locally:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_gdelt --query '"mineral" "disruption"' --max-records 5
```

## Verification and evidence

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.capture_model2_evidence
```

See `docs/TESTING.md`, `docs/api-samples.json`, `docs/demo-output.json`,
`docs/preservation.json`, and `docs/startup-smoke.json` for actual execution results.
Tests use isolated databases. No local Ollama server was available; fallback and
rejection of unsupported generated claims are tested. Model 2 retrieves stored
structured evidence; the optional LLM can only reorder validated facts. It cannot
invent factual output. Model 1's existing document/vector RAG remains intact.

## Frontend integration

No frontend application was uploaded. `frontend-integration/minetrace-monitor.js`
is a dependency-free custom element for later integration:

```html
<script src="/your-assets/minetrace-monitor.js"></script>
<minetrace-monitor api-base="http://127.0.0.1:8000"></minetrace-monitor>
```

Serve this script from your frontend. Use port 8001 for the isolated demo. It shows
cached/live state, events and sources, candidate geometry, route statuses and
explanations. The geometry view is a schematic, not a navigable map. It has no
paid dependencies. JavaScript syntax was checked; browser rendering and integration
with your actual frontend were not tested. Never expose the reviewer token in
this public-facing component. Restrict API/CORS access before public deployment;
the existing development API is intended for local use.

## Limits that remain

- GDELT returns article metadata, not independently verified incidents. English
  keyword extraction and a small gazetteer can miss or misclassify reports.
- Headline place matches supply reference infrastructure coordinates, not precise
  incident coordinates. Country ambiguity remains unknown; publisher country is
  never used as incident country. Country alias matching remains limited.
- Routes/graph links are illustrative candidate data, not verified current services.
  Graph distances are approximate. Imported routes can be exposed geographically,
  but alternatives require connectivity in the stored demonstration graph.
- No carrier inventory, freight quotations, actual ETA, insurance underwriting or
  comprehensive legal screening is available. Legal status defaults UNKNOWN.
- Official/corroborated statuses require human review. Authority advisories are
  authenticated by the human reviewer, not automatically by the application.
- Conservative event deduplication groups matching normalized headlines within a
  location/type/day bucket. Differently worded reports remain separate; neither
  copied reports nor additional publishers automatically imply corroboration.
- No alert never establishes safety. R6 is an explainable heuristic, not a probability.
- The implementation provides a working backend and offline demonstration, not
  certification that every real-world disruption or shipment can be assessed.
