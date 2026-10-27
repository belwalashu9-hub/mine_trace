# Architecture and evidence rules

## Responsibilities and storage

Model 1: UN Comtrade historical trade + OFAC sanctions → existing SQLite tables →
unchanged R1–R5 → existing evidence, ranking, reports and RAG.

Model 2: GDELT DOC article discovery → normalizer → `gdelt_articles` and category
links → event classifier → `geopolitical_events` + `event_article_evidence` →
`route_exposure_matches` → `r6_risk_assessments` → `route_feasibility_assessments`.

`transport_routes` contains GeoJSON LineStrings, ordered segment data and hubs.
Existing JSON segment columns are reused instead of duplicating another segment
table. Imported routes store coordinate pairs and segment indexes.
`route_operational_evidence` stores reviewed, expiring route-specific advisories;
`model2_monitoring_lease` coordinates synchronization; `model2_sync_status` and
`gdelt_ingestion_runs` preserve monitoring/fetch history. Tables are added with
SQLAlchemy create_all; the explicit migration CLI takes a SQLite backup first.

The original database includes seven known synthetic GDELT fixture records. Migration
marks those exact fixture URLs `synthetic_fixture`; default news/classification
excludes them. It retains every row and preserves all Model 1 tables.
The standalone demo uses a separate SQLite database.

## Ingestion and extraction

DOC requests use query, mode=ArtList, format=json, timespan, maxrecords<=250 and
sort=DateDesc. Provider reference checked during development:
https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/amp/

URLs are canonicalized and hashed; categories are attached idempotently. UTC parsing
normalizes offset timestamps. Seen dates, publication dates and occurrence dates
are separate. GDELT seen dates never become event/publication dates. Missing
fields remain unknown; unsafe URL schemes are rejected.

Headline rules classify disruption type, country/infrastructure and mineral
relevance. Normalized headline + location + event type + date forms a conservative
cluster key. A single news story is REPORTED; copied stories cannot upgrade it.
Keyword claims such as “official statement” never establish official confirmation.
Reviewer endpoints preserve supporting URLs and reviewer/reason information.
Coordinate positions from this gazetteer are reference points with explicit
uncertainty, not independently geolocated incidents.

## Exposure and distance

Country exposure is a possible trade association, infrastructure exposure matches
named hubs, and physical exposure compares an event/reference point with candidate
route segments. `/events/{id}/trade-exposure` links country names to locally stored
critical-mineral trade records without inventing shipping routes.

Distances use spherical great-circle cross-track and along-track geometry with
mean radius 6371.0088 km; nearest endpoints bound the segment. This handles the
date line and avoids treating longitude/latitude degrees as kilometers. Invalid
coordinates/antipodal ambiguous segments are rejected. Segment index and the
uncertainty note are stored in matching details. Within 5 km is a corridor proximity
flag, not a literal proof of intersection or closure.

Event zones (km): maritime 150; war 120; armed conflict 100; disaster 75; political
instability 60; port/transport/export/sanctions 50; mine shutdown 40; strike 30.
These are configurable constants in `app/geospatial/matching_engine.py`, not
empirically calibrated blast radii. Derived matches and R6 records are rebuilt
on synchronization so removed exposures do not persist as live alerts.

## R6 formula (Model 2 only)

Score = clamp(severity + proximity + verification + mineral relevance + recency,0,100).

| Factor | Default points |
|---|---|
| Severity | WAR/ARMED_CONFLICT 35; maritime/port 30; shutdown/export 25; strike/transport/sanctions 20; disaster/political 15; OTHER 10; UNKNOWN 5 |
| Proximity | <=5 km:35; within zone:20+15*(1-distance/zone); infrastructure:25; country:10 |
| Verification | official:15; corroborated:12; reported:8; unverified/disputed:3; other:5 |
| Mineral relevance | direct:15; indirect:10; otherwise:0 |
| Recency | <=2 days:+5; >14 days:-10; otherwise:0 |

Recency uses known event/publication dates, otherwise associated GDELT indexing
metadata, otherwise storage time. That fallback is an information-freshness proxy,
not a claim about incident occurrence. Status UNKNOWN or extraction confidence
below 0.25 yields UNKNOWN risk. Otherwise: >=70 CRITICAL; >=45 HIGH; >=25 MODERATE;
below25 LOW. Optional bounded environment overrides change severity/thresholds.
Triggering factors store the actual values used; scores never feed Model 1.

Potential security, production, port, border, delay, rerouting, trade restriction
and logistics-cost impacts are categorical hypotheses with event/route evidence.
Official confirmation of a war does not independently confirm operational impact.
No invented delays, prices, carrier cancellations or closure claims are produced.

## Feasibility and alternatives

Current human-reviewed CLOSED advisory for this exact route → CONFIRMED_CLOSED.
Otherwise relevant moderate/high/critical R6 → AT_RISK; no alerts → NO_IDENTIFIED_ALERT;
insufficient/unknown assessments → UNKNOWN. OPEN advisories do not verify carrier
availability. Expired advisories stop supporting closure automatically.

Sanctions/export reports trigger REVIEW_REQUIRED; absence of a full legal assessment
remains UNKNOWN. No branch asserts VERIFIED_OPTION_AVAILABLE without operational,
commercial and legal evidence; this prototype has no such evidence integration.
A closed route without a supported alternative returns NO_SUPPORTED_OPTION_IDENTIFIED,
which is not a statement that all global trade is impossible.

NetworkX searches a different path between the same origin and destination. Closed
hubs are removed. Exposed hubs have a 3x distance-weight penalty. Risk-weighted cost
selects paths; geometric distance is displayed separately. Paths ending at a different
port are not presented as equivalent end-to-end alternatives. Missing/disconnected
networks yield no supported candidate. All alternatives are NOT CARRIER VERIFIED.

## Explanation and frontend

The explanation endpoint retrieves stored R6, article URLs, feasibility and routing
facts. Deterministic prose is always available. Existing Ollama can optionally
return a permutation of fact indexes; schema/membership validation rejects unsupported
output. Only stored facts are rendered, so generated numbers/sources cannot leak in.
No untrusted article text is followed as instructions. The supplied web component
uses textContent for fetched text and permits only http(s) source links.
