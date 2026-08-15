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

Environment variables (prefix `INTERVIEW_`). Generated from the `Settings`
class; MetaGate bootstrap variables are documented in their own section below.

`INTERVIEW_API_KEY` is **required** unless `INTERVIEW_ALLOW_INSECURE_DEV=true`; startup fails without it.

See `.env.example` for a working starting point.

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERVIEW_DEBUG` | `false` | Enable debug mode |
| `INTERVIEW_HOST` | `0.0.0.0` | Server bind address |
| `INTERVIEW_INSTANCE_ID` | `interview-1` | Instance identifier |
| `INTERVIEW_INTERVIEW_VERSION` | `0.1.0` | Service version |
| `INTERVIEW_PORT` | `8000` | Server port |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERVIEW_ALLOW_INSECURE_DEV` | `false` | Allow unauthenticated access (dev only) |
| `INTERVIEW_API_KEY` | *(empty)* | API key for authentication |

### Upstream services

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERVIEW_ASYNCGATE_API_KEY` | *(unset)* | AsyncGate API key |
| `INTERVIEW_ASYNCGATE_URL` | *(unset)* | AsyncGate MCP endpoint |
| `INTERVIEW_DEPOTGATE_API_KEY` | *(unset)* | DepotGate API key |
| `INTERVIEW_DEPOTGATE_URL` | *(unset)* | DepotGate MCP endpoint |
| `INTERVIEW_GLOBAL_LEDGER_URL` | *(unset)* | Global ledger MCP endpoint |
| `INTERVIEW_LEDGER_MIRROR_URL` | *(unset)* | Legacy ledger mirror URL |
| `INTERVIEW_MEMORYGATE_URL` | *(unset)* | Deprecated MemoryGate URL |
| `INTERVIEW_PROJECTION_CACHE_TTL_SECONDS` | `60` | Projection cache TTL |
| `INTERVIEW_PROJECTION_CACHE_URL` | *(unset)* | Projection cache URL |
| `INTERVIEW_RECEIPTGATE_API_KEY` | *(unset)* | ReceiptGate API key |
| `INTERVIEW_RECEIPTGATE_URL` | *(unset)* | ReceiptGate MCP endpoint |

### Rate limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERVIEW_RATE_LIMIT_ENABLED` | `true` | Enable API rate limiting |
| `INTERVIEW_RATE_LIMIT_REQUESTS_PER_MINUTE` | `100` | API rate limit per minute |

### CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERVIEW_CORS_ALLOW_CREDENTIALS` | `true` | Allow credentials in CORS requests |
| `INTERVIEW_CORS_ALLOWED_HEADERS` | `['Authorization', 'Content-Type', 'X-Tenant-ID']` | Allowed request headers |
| `INTERVIEW_CORS_ALLOWED_METHODS` | `['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']` | Allowed HTTP methods |
| `INTERVIEW_CORS_ALLOWED_ORIGINS` | `['http://localhost:3000', 'http://localhost:8080']` | Allowed CORS origins |

### Behaviour and limits

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERVIEW_ALLOW_GLOBAL_LEDGER` | `false` | Allow global ledger access |
| `INTERVIEW_COMPONENT_POLL_CACHE_SECONDS` | `5` | Component poll cache duration |
| `INTERVIEW_COMPONENT_POLL_RATE_LIMIT_PER_MINUTE` | `60` | Component poll rate limit per minute |
| `INTERVIEW_COMPONENT_POLL_TIMEOUT_MS` | `500` | Component poll timeout in milliseconds |
| `INTERVIEW_DEFAULT_LIMIT` | `100` | Default result limit |
| `INTERVIEW_DEFAULT_TIME_WINDOW_HOURS` | `24` | Default time window in hours |
| `INTERVIEW_MAX_LIMIT` | `200` | Maximum result limit |
| `INTERVIEW_MAX_TIME_WINDOW_HOURS` | `168` | Maximum time window in hours (1 week) |

## MCP Interface

InterView is MCP-HTTP only. Use `/mcp` with JSON-RPC methods:
- `tools/list`
- `tools/call`

All read-only surfaces (status/search/get/health/queue/inventory) are exposed as MCP tools.

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

> **Open discrepancy.** The canonical `mcp.naming.md` requires service-owned
> tools to be namespaced `interview.*`, and §6 of that document outranks this
> README. The surface below is what the code advertises today, so it is
> documented here as fact rather than as compliance. `global.ledger.receipts`
> is the sharper case: it carries no service segment at all, which the naming
> contract forbids under any convention. See §7 of `mcp.naming.md` for the two
> ways this can be resolved — renaming (which breaks callers and the
> `tests/test_mcp_snapshot.py` contract snapshot) or a recorded exception.

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
| `global.ledger.receipts()` | Global ledger sweep. Last resort, opt-in only: requires explicit intent because it is the one surface not scoped to a task lineage. |
| `interview.health()` | Health check for InterView itself |

That is the full surface reported by `tools/list` — eight tools, not the six
required by v0. `interview.health` follows the canonical namespacing; the rest
do not, per the discrepancy noted above.

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

## MetaGate Bootstrap

On startup this gate asks MetaGate for the topology it belongs to and fills in
endpoints the operator did not configure. It resolves: `receiptgate` → `receiptgate_url`, `asyncgate` → `asyncgate_url`, `depotgate` → `depotgate_url`.

| Variable | Default | Meaning |
|----------|---------|---------|
| `INTERVIEW_METAGATE_ENDPOINT` | *(unset)* | MetaGate MCP endpoint. Unset disables bootstrap; the gate starts on configured values alone. |
| `INTERVIEW_METAGATE_API_KEY` | *(unset)* | Credential presented to MetaGate |
| `INTERVIEW_METAGATE_COMPONENT_KEY` | `interview` | Which component in the manifest this process is |
| `INTERVIEW_METAGATE_BOOTSTRAP_TIMEOUT_SECONDS` | `5.0` | Per-call timeout |

Bootstrap never prevents startup. Every failure — unreachable, timeout, auth
rejected, no binding, malformed packet — degrades to a logged warning and
"carry on with configured values", because a bootstrap authority that can take
the mesh down would be a hidden master. Explicit configuration always wins;
bootstrap fills gaps and logs when the mesh disagrees rather than overriding.

See `LegiVellum/docs/canonical/metagate.bootstrap.md` for the full contract.

## License

Proprietary - Technomancy Labs
