# InterView

**Read-Only System Viewer Surfaces for LegiVellum Meshes**

InterView provides bounded, read-only insight into system state and operations via query surfaces, without introducing orchestration, polling storms, or load amplification on global receipt stores.

## Status

**Implementation:** v0.1.0 (based on SPEC-IV-0000)

See: `InterView Spec v0.txt` for full specification.

## Installation

```bash
pip install -e ".[dev]"
```

## Configuration

Environment variables (prefix `INTERVIEW_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | 0.0.0.0 | Server bind address |
| `PORT` | 8000 | Server port |
| `DEBUG` | false | Enable debug mode |
| `INSTANCE_ID` | interview-1 | Instance identifier |
| `PROJECTION_CACHE_URL` | - | Projection cache URL |
| `LEDGER_MIRROR_URL` | - | Ledger mirror URL |
| `ASYNCGATE_URL` | - | AsyncGate URL for health/queue polls |
| `DEPOTGATE_URL` | - | DepotGate URL for artifact metadata |
| `ALLOW_GLOBAL_LEDGER` | false | Enable global ledger access |
| `GLOBAL_LEDGER_URL` | - | Global ledger URL |
| `COMPONENT_POLL_RATE_LIMIT_PER_MINUTE` | 60 | Rate limit for component polls |
| `COMPONENT_POLL_TIMEOUT_MS` | 500 | Component poll timeout |
| `COMPONENT_POLL_CACHE_SECONDS` | 5 | Component poll cache TTL |

## API Endpoints

### Health
- `GET /health` - Health check
- `GET /` - Service info

### Surfaces (v0)
- `POST /v1/status/receipts` - status.receipts.interview()
- `POST /v1/search/receipts` - search.receipts.interview()
- `POST /v1/get/receipt` - get.receipt.interview()
- `POST /v1/health/async` - health.async.interview()
- `POST /v1/queue/async` - queue.async.interview()
- `POST /v1/inventory/artifacts/depot` - inventory.artifacts.depot.interview()

### Global Ledger (opt-in)
- `POST /v1/global-ledger/receipts` - Direct global ledger query (disabled by default)

## Running

```bash
# Start server
uvicorn interview.main:app --host 0.0.0.0 --port 8000

# Or use the entry point
python -m interview.main
```

## Core Doctrine

InterView is a window. If it can change the world, it is no longer a Viewer.

InterView may query ledgers, caches, storage metadata, and (optionally) poll components for diagnostics. It MUST NOT initiate work, route work, modify artifacts, mutate system state, or trigger automation.

## Non-Goals (Hard Prohibitions)

InterView MUST NOT:
- Submit tasks or work orders
- Issue or revoke leases
- Retry, reschedule, reassign, or "fix" anything
- Ship deliverables or purge staging
- Write receipts as part of "state changes"
- Infer completion based on timeouts or heuristics
- Perform watch/trigger behavior

## Source-of-Truth Hierarchy

InterView protects the global receipt store with a strict source hierarchy:

1. **Projection Cache** (preferred) - Local read-optimized store
2. **Ledger Mirror** (permitted) - Local or read-replica receipt store
3. **Component Diagnostics** (optional, bounded) - Rate-limited health/metrics
4. **Global Ledger** (last resort, opt-in only) - Requires explicit intent

## Surface Convention

```
<verb>.<domain>[.<subdomain>].interview()
```

### Verb Taxonomy (v0)

| Verb | Purpose |
|------|---------|
| `status.*` | Derived state summaries |
| `search.*` | Bounded search/list queries |
| `get.*` | Single-object retrieval by ID |
| `health.*` | Live component polls |
| `queue.*` | Live AsyncGate queue diagnostics |
| `inventory.*` | Storage + metadata listing |

## Required Surfaces (v0)

| Surface | Purpose |
|---------|---------|
| `status.receipts.interview()` | Low-cost derived status for task lineage |
| `search.receipts.interview()` | Search/list receipt headers with bounds |
| `get.receipt.interview()` | Retrieve single receipt by ID |
| `health.async.interview()` | Live health snapshot of AsyncGate |
| `queue.async.interview()` | Live AsyncGate queue diagnostics |
| `inventory.artifacts.depot.interview()` | List artifact pointers for task/deliverable |

## Request Controls

All list/search surfaces support:
- `limit` (default <= 100)
- `time_window` or `since` (default <= 24h)
- `include_body` (default false)
- `freshness` enum: `cache_ok`, `prefer_fresh`, `force_fresh`

## Response Metadata

Every response includes:
- `source` enum (projection_cache, ledger_mirror, component_poll, etc.)
- `freshness_age_ms`
- `truncated` boolean
- `next_page_token` (optional)
- `cost_units`

## Guarantees

- Will not create side effects in the mesh
- Will not hammer the global receipt store by default
- Responses are bounded and labeled with freshness/source

## License

Proprietary - Technomancy Labs
