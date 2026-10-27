# Model 2 API contract

Base: `http://127.0.0.1:8000/api/v1/live`. FastAPI `/docs` is the generated request
schema. `api-samples.json` contains nine actual HTTP-200 responses from the isolated
synthetic demo. Do not describe them as live GDELT news.

| Method / path | Purpose |
|---|---|
| GET /status | Persisted last synchronization, last successful live fetch, freshness notice |
| POST /sync?source=live | Fetch, ingest and run full pipeline; inspect result.status |
| POST /sync?source=offline | Cached-data processing without provider calls |
| GET /news | Paginated article metadata; excludes synthetic fixtures |
| GET /events | Filters: country, mineral, event_type, verification_status, limit, offset |
| GET /events/{event_id} | Event details and linked evidence/exposure |
| GET /events/{event_id}/trade-exposure | Potential historical country-trade exposure |
| GET /affected-countries | Country summaries |
| GET /routes | Candidate geometries and status, optional mineral filter |
| GET /routes/{route_id} | Hubs, ordered segments, geometry and designation |
| GET /affected-routes | Stored route alert summaries |
| GET /routes/{route_id}/impact | R6 factors, scores, consequences, source evidence |
| GET /routes/{route_id}/feasibility | Recomputed status, including advisory expiry |
| GET /routes/{route_id}/alternatives | Evidence-aware candidate alternative summary |
| GET /routes/{route_id}/explanation?use_llm=false | Grounded explanation and sources |
| GET /dashboard/summary | Monitoring counts and synchronization status |
| POST /routes/import | Validated candidate geometry; reviewer token required |
| POST /routes/{route_id}/advisories | Reviewed route-specific operational evidence |
| POST /events/{event_id}/review | Manual verification status and supporting URLs |

Manual sync accepts category and max_records (1–100). Startup polling allows up to
250. A result status of DEGRADED_CACHED means cached analysis succeeded while the
provider failed; BUSY means the shared lease is already held. API source=fixture
is intentionally unavailable: use the isolated demo CLI.

Token-gated writes: set MODEL2_REVIEW_TOKEN locally, then send `X-Model2-Token`.
Never put that token in client-side JavaScript. Invalid tokens produce 403, invalid
schemas 422, unknown records 404, and duplicate imported route identifiers 409.
The reviewer must authenticate the source independently before submitting an advisory.

Example route import body (synthetic geometry):
```json
{"route_id":"candidate_test_v1","name":"Synthetic corridor","origin":"A","destination":"B","mineral_relevance":"cobalt","transport_mode":"MARITIME","coordinates":[[179,0],[-179,0]],"primary_hubs":[],"source":"Synthetic test geometry"}
```

Example advisory body — use a real authoritative URL, exact route scope and a future
UTC validity timestamp only after reviewing the evidence:
```json
{"authority":"Reviewed authority name","source_url":"https://authority.example/advisory","statement":"Reviewed statement establishing the exact route closure","verified_by":"Reviewer name","status":"CLOSED","valid_until":"2026-11-01T00:00:00Z","affected_hubs":["Bab el-Mandeb"]}
```
The URL above is a placeholder, not a real advisory. Only an authorized reviewer
should submit real evidence. OPEN/UNKNOWN and expiring advisories are supported.

Verification review body: status, source_urls (nonempty http(s) list), reason
(minimum 20 characters), reviewer. Re-run offline synchronization after changing
an event's review status. Event confirmation alone does not close its routes.

The frontend component expects `items` from /events, `routes` from /routes,
`overview` and `system_status` from /dashboard/summary, and `facts`/`sources` from
route explanations. It never interprets no-alert as verified shipping availability.
