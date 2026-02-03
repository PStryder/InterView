> LEGACY NOTE (2026-02-03): InterView is MCP-only. REST endpoint references are historical.

# InterView Code Review

**Review Date:** 2026-01-08
**Spec Version:** SPEC-IV-0000 (v0)
**Implementation Version:** 0.1.0
**Reviewer:** Code Review Agent

---

## Executive Summary

InterView is a read-only system viewer surface for LegiVellum Meshes, designed to provide bounded, observational insight into system state without causing side effects. The implementation is well-structured and demonstrates strong adherence to the specification's core doctrine. However, there are notable gaps in security implementation, testing coverage, and several spec compliance issues that need attention.

### Overall Assessment

| Category | Rating | Notes |
|----------|--------|-------|
| Spec Compliance | **7/10** | Core surfaces implemented; missing permission system and derivation rules |
| Code Quality | **8/10** | Clean architecture, good patterns, well-organized |
| Security | **5/10** | Critical CORS issue, missing tenant isolation verification |
| Error Handling | **7/10** | Good coverage but some gaps |
| Testing | **1/10** | No tests present |
| Documentation | **8/10** | Good README, inline docs, but missing API docs |

---

## 1. Spec Compliance Analysis

### 1.1 Required Surfaces (Section 7 & 13)

| Surface | Status | Notes |
|---------|--------|-------|
| `status.receipts.interview()` | Implemented | `/v1/status/receipts` |
| `search.receipts.interview()` | Implemented | `/v1/search/receipts` |
| `get.receipt.interview()` | Implemented | `/v1/get/receipt` |
| `health.async.interview()` | Implemented | `/v1/health/async` |
| `queue.async.interview()` | Implemented | `/v1/queue/async` |
| `inventory.artifacts.depot.interview()` | Implemented | `/v1/inventory/artifacts/depot` |

**Result: All 6 required v0 surfaces are implemented.**

### 1.2 Core Doctrine Compliance (Section 0)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Read-only / observational only | **PASS** | No write operations in codebase |
| No work initiation | **PASS** | No task submission endpoints |
| No state mutation | **PASS** | Only GET/POST for reads |
| No automation triggers | **PASS** | No watch/trigger patterns |

### 1.3 Non-Goals Verification (Section 1)

All hard prohibitions appear to be respected:
- No task/work order submission
- No lease operations
- No retry/reschedule logic
- No deliverable shipping
- No receipt writing
- No timeout-based inference
- No watch/trigger behavior

### 1.4 Source-of-Truth Hierarchy (Section 2)

| Source | Implementation | Status |
|--------|---------------|--------|
| Projection Cache | `ProjectionCache` class | Implemented |
| Ledger Mirror | `LedgerMirror` class | Implemented |
| Component Poll | `ComponentPoller` class | Implemented |
| Storage Metadata | `StorageMetadata` class | Implemented |
| Global Ledger | `GlobalLedger` class | Implemented (opt-in) |

**Source Priority:** The code correctly prioritizes projection_cache over ledger_mirror. Global ledger is correctly disabled by default (`allow_global_ledger=False`).

### 1.5 Required Scoping (Section 4)

| Requirement | Status | Notes |
|-------------|--------|-------|
| `tenant_id` required on all calls | **PASS** | All request models include `tenant_id` |
| Identifier scoping (task_id/receipt_id/etc.) | **PASS** | Implemented in request models |
| Strict tenant isolation | **PARTIAL** | tenant_id passed but not verified against auth |

**Issue:** Tenant isolation is passed through to backend services but there is no verification that the caller is authorized for the specified tenant_id.

### 1.6 Request Controls (Section 5)

| Control | Spec Default | Implementation | Status |
|---------|--------------|----------------|--------|
| `limit` | <= 100 | default=100, max=200 | **PASS** |
| `time_window` | <= 24h | default=24h, max=168h | **PASS** |
| `include_body` | false | default=False | **PASS** |
| `freshness` enum | cache_ok | CACHE_OK default | **PASS** |

**File:** `F:\HexyLab\LV_Stack\InterView\src\interview\models.py` (lines 49-56)

### 1.7 Response Metadata (Section 6)

| Field | Required | Implemented |
|-------|----------|-------------|
| `source` enum | Yes | **PASS** |
| `freshness_age_ms` | Yes | **PASS** |
| `truncated` | Yes | **PASS** |
| `next_page_token` | Optional | **PASS** |
| `cost_units` | Yes | **PASS** |

**File:** `F:\HexyLab\LV_Stack\InterView\src\interview\models.py` (lines 39-46)

### 1.8 Status Derivation Rules (Section 7.1)

**MISSING IMPLEMENTATION**

The spec defines specific derivation rules:
```
If shipment_complete exists -> shipped
Else if complete exists for root obligation -> resolved
Else if escalate exists without acceptance -> escalated/blocked
Else if accepted exists -> in_progress
Else -> unknown
```

**Current Implementation:** Always returns `TaskState.UNKNOWN` when no cached data exists. The derivation logic is not implemented.

**File:** `F:\HexyLab\LV_Stack\InterView\src\interview\api.py` (lines 152-168)

### 1.9 Global Ledger Protection (Section 9)

| Requirement | Status |
|-------------|--------|
| Disabled by default | **PASS** (`allow_global_ledger=False`) |
| Explicit opt-in required | **PASS** |
| Error codes GLOBAL_LEDGER_DISABLED / GLOBAL_LEDGER_FORBIDDEN | **PARTIAL** (only DISABLED implemented) |

**Missing:** `GLOBAL_LEDGER_FORBIDDEN` error code for permission-denied scenarios.

### 1.10 Security and Redaction (Section 11)

| Requirement | Status | Notes |
|-------------|--------|-------|
| Tenant scoping enforcement | **PARTIAL** | Passed but not verified |
| Artifact pointer redaction | **NOT IMPLEMENTED** | No redaction logic |
| Diagnostic field redaction | **NOT IMPLEMENTED** | No redaction logic |
| Per-surface permissions | **NOT IMPLEMENTED** | No permission system |

**Missing Permissions (Section 11):**
- `can_view_receipts`
- `can_view_artifacts`
- `can_poll_health`
- `can_poll_queue`
- `can_force_global_ledger`

---

## 2. Code Quality Assessment

### 2.1 Architecture

**Strengths:**
- Clean separation of concerns (models, config, sources, api, main)
- Proper use of FastAPI dependency injection
- Abstract base class for data sources
- Source hierarchy pattern is well-implemented

**Files:**
- `F:\HexyLab\LV_Stack\InterView\src\interview\models.py` - Data models
- `F:\HexyLab\LV_Stack\InterView\src\interview\config.py` - Configuration
- `F:\HexyLab\LV_Stack\InterView\src\interview\sources.py` - Data source clients
- `F:\HexyLab\LV_Stack\InterView\src\interview\api.py` - API endpoints
- `F:\HexyLab\LV_Stack\InterView\src\interview\main.py` - Application entry

### 2.2 Type Safety

**Strengths:**
- Comprehensive Pydantic models for all requests/responses
- Proper use of type hints throughout
- Enums for fixed values (Source, Freshness, TaskState)

**Example (good):**
```python
class ResponseMetadata(BaseModel):
    source: Source = Field(..., description="Data source used")
    freshness_age_ms: int = Field(..., ge=0, description="Age of data in milliseconds")
    truncated: bool = Field(default=False, description="Whether results were truncated")
```

### 2.3 Code Patterns

**Good Patterns:**
- Async/await used consistently
- Proper HTTP client lifecycle management
- LRU cache for settings
- Rate limiting implementation for component polls

**Areas for Improvement:**
- Global `_source_manager` variable pattern could be improved with proper FastAPI lifespan context
- In-memory caching in ProjectionCache won't scale for production

### 2.4 Readability

**Strengths:**
- Clear docstrings referencing spec sections
- Consistent naming conventions
- Well-organized file structure
- Logical grouping with section comments

---

## 3. Security Review

### 3.1 Critical Issues

#### CRITICAL: Permissive CORS Configuration

**File:** `F:\HexyLab\LV_Stack\InterView\src\interview\main.py` (lines 69-75)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Risk:** This configuration allows any origin to make authenticated requests. Combined with `allow_credentials=True`, this is a significant security vulnerability that could enable CSRF attacks.

**Recommendation:** Configure specific allowed origins or make this environment-configurable.

### 3.2 High-Priority Issues

#### HIGH: No Authentication/Authorization

The API has no authentication mechanism. Any caller can:
- Query any tenant's data by specifying any `tenant_id`
- Access health and queue diagnostics
- Potentially access global ledger if enabled

**Recommendation:** Implement authentication (e.g., JWT, API keys) and verify tenant authorization.

#### HIGH: Tenant Isolation Not Enforced

**File:** `F:\HexyLab\LV_Stack\InterView\src\interview\api.py`

The `tenant_id` is passed through to backend services but never validated against the authenticated caller's permissions.

```python
status, age_ms = await sources.projection_cache.get_status(
    tenant_id=request.tenant_id,  # No verification!
    root_task_id=root_task_id,
)
```

### 3.3 Medium-Priority Issues

#### MEDIUM: No Input Sanitization

While Pydantic provides type validation, there is no sanitization of string inputs for:
- `tenant_id`
- `task_id`
- `receipt_id`
- `queue_id`

These are passed directly to backend services and could potentially be used for injection attacks if backend services don't sanitize.

#### MEDIUM: Rate Limiting Only for Component Polls

Rate limiting is implemented only for component polls (health/queue). Search and status endpoints have no rate limiting, which could lead to:
- Cache exhaustion attacks
- Backend service overload

### 3.4 Low-Priority Issues

#### LOW: Debug Mode Exposes Information

When `debug=True`, the application runs with reload enabled, which is appropriate for development but should never be enabled in production.

#### LOW: No Request ID Tracking

No request correlation IDs for security auditing and debugging.

---

## 4. Error Handling Review

### 4.1 Implemented Error Handling

| Source | Error Type | HTTP Status | Handling |
|--------|------------|-------------|----------|
| Sources | `SourceUnavailableError` | 503 | Returns graceful degradation or error |
| Sources | `GlobalLedgerDisabledError` | 403 | Returns specific error code |
| Sources | `DataSourceError` | 429 | Rate limit exceeded |
| Validation | Pydantic errors | 422 | Automatic via FastAPI |
| HTTP calls | `httpx.HTTPError` | Varies | Converted to SourceUnavailableError |
| HTTP calls | `httpx.TimeoutException` | 503 | Component poll timeout |

### 4.2 Error Handling Gaps

#### Missing Validation Error

**File:** `F:\HexyLab\LV_Stack\InterView\src\interview\api.py` (lines 128-134)

```python
if not root_task_id:
    raise HTTPException(
        status_code=400,
        detail="Either task_id or root_task_id is required",
    )
```

This validation should be in the Pydantic model using `@model_validator`.

#### Missing Circuit Breaker

No circuit breaker pattern for failing backend services. Repeated failures to ledger_mirror or component services could cascade.

#### Silent Failures

**File:** `F:\HexyLab\LV_Stack\InterView\src\interview\api.py` (lines 232-233)

```python
except SourceUnavailableError:
    pass  # Keep empty results from cache
```

Silent exception handling could mask problems.

---

## 5. Testing Review

### 5.1 Current State

**NO TESTS EXIST**

The `pyproject.toml` includes test dependencies (`pytest`, `pytest-asyncio`, `pytest-httpx`) but no test files were found in the codebase.

### 5.2 Required Test Coverage

| Category | Priority | Description |
|----------|----------|-------------|
| Unit Tests | Critical | All data models validation |
| Unit Tests | Critical | Source clients (mocked HTTP) |
| Unit Tests | High | Rate limiter logic |
| Unit Tests | High | Cache expiration logic |
| Integration Tests | Critical | All API endpoints |
| Integration Tests | High | Source fallback behavior |
| Integration Tests | High | Error handling paths |
| Security Tests | High | Tenant isolation |
| Security Tests | High | Global ledger protection |
| Performance Tests | Medium | Rate limiting under load |
| Contract Tests | Medium | Backend service contracts |

---

## 6. Issues Found (Categorized by Severity)

### CRITICAL

| ID | Issue | Location | Description |
|----|-------|----------|-------------|
| C-1 | Permissive CORS | `main.py:69-75` | `allow_origins=["*"]` with `allow_credentials=True` enables CSRF |
| C-2 | No Authentication | All endpoints | No auth mechanism implemented |
| C-3 | No Tests | N/A | Zero test coverage |

### HIGH

| ID | Issue | Location | Description |
|----|-------|----------|-------------|
| H-1 | Tenant Isolation | `api.py` | `tenant_id` not verified against caller |
| H-2 | Missing Permissions | All surfaces | Per-surface permissions not implemented (spec section 11) |
| H-3 | No Redaction | `api.py` | Artifact/diagnostic redaction not implemented |
| H-4 | Missing Derivation Rules | `api.py:152-168` | Status derivation per spec 7.1 not implemented |
| H-5 | Global Rate Limiting | All endpoints | Only component polls are rate-limited |

### MEDIUM

| ID | Issue | Location | Description |
|----|-------|----------|-------------|
| M-1 | In-Memory Cache | `sources.py:53-67` | ProjectionCache uses dict; won't scale horizontally |
| M-2 | No Circuit Breaker | `sources.py` | No protection against cascading failures |
| M-3 | Silent Exceptions | `api.py:232-233` | `except: pass` masks failures |
| M-4 | Missing Error Code | N/A | `GLOBAL_LEDGER_FORBIDDEN` not implemented |
| M-5 | UTC Deprecation | `sources.py:71` | `datetime.utcnow()` is deprecated |
| M-6 | Global State | `api.py:56` | `_source_manager` global variable pattern |

### LOW

| ID | Issue | Location | Description |
|----|-------|----------|-------------|
| L-1 | No Request IDs | N/A | No correlation ID for request tracing |
| L-2 | No Pagination Tokens | `api.py` | `next_page_token` always None |
| L-3 | License Mismatch | `README.md` vs `LICENSE` | README says "Proprietary" but LICENSE is Apache 2.0 |
| L-4 | Missing Optional Surfaces | N/A | `health.depot.interview()` and `status.depot.interview()` not implemented |
| L-5 | Host Binding | `config.py:14` | Default `0.0.0.0` may expose to network |

---

## 7. Recommendations

### Immediate Actions (Before Production)

1. **Fix CORS Configuration (C-1)**
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=settings.allowed_origins,  # Configure from env
       allow_credentials=True,
       allow_methods=["GET", "POST"],
       allow_headers=["*"],
   )
   ```

2. **Implement Authentication (C-2)**
   - Add JWT or API key authentication middleware
   - Extract tenant_id from auth token
   - Verify tenant authorization on each request

3. **Write Core Tests (C-3)**
   - Start with endpoint integration tests
   - Add unit tests for rate limiting and caching

4. **Implement Tenant Verification (H-1)**
   ```python
   def verify_tenant_access(request_tenant: str, auth_tenant: str):
       if request_tenant != auth_tenant:
           raise HTTPException(403, "Tenant access denied")
   ```

### Short-Term Improvements

5. **Implement Permission System (H-2)**
   - Add permission checks per surface
   - Integrate with auth system

6. **Add Redaction Logic (H-3)**
   - Create redaction service
   - Apply based on caller permissions

7. **Implement Status Derivation (H-4)**
   - Add receipt analysis logic
   - Implement spec section 7.1 rules

8. **Add Global Rate Limiting (H-5)**
   - Use slowapi or similar
   - Configure per-tenant limits

### Long-Term Improvements

9. **Replace In-Memory Cache (M-1)**
   - Use Redis or similar
   - Enable horizontal scaling

10. **Add Circuit Breaker (M-2)**
    - Use circuitbreaker library
    - Configure per backend service

11. **Implement Pagination (L-2)**
    - Add cursor-based pagination
    - Return `next_page_token` when applicable

12. **Add Observability**
    - Request ID generation
    - Structured logging
    - Metrics collection

---

## 8. Positive Observations

The implementation demonstrates several excellent practices:

1. **Strong Spec Adherence**: Core doctrine is well-respected; the system is truly observational
2. **Clean Architecture**: Clear separation between models, config, sources, and API layers
3. **Type Safety**: Comprehensive Pydantic models with proper validation
4. **Source Hierarchy**: Correct implementation of the load-safety contract
5. **Rate Limiting**: Component polls properly rate-limited per spec
6. **Graceful Degradation**: Fallback behavior when sources unavailable
7. **Good Documentation**: README is comprehensive and matches spec

---

## 9. Conclusion

InterView v0.1.0 provides a solid foundation implementing the SPEC-IV-0000 specification. The core functionality is present and the architectural patterns are sound. However, the implementation is not production-ready due to:

1. **Critical security gaps** (CORS, authentication, tenant isolation)
2. **Zero test coverage**
3. **Missing permission and redaction systems**
4. **Incomplete status derivation logic**

### Production Readiness Checklist

- [ ] Fix CORS configuration
- [ ] Implement authentication
- [ ] Add tenant verification
- [ ] Implement permission system
- [ ] Add comprehensive tests (target >80% coverage)
- [ ] Implement status derivation rules
- [ ] Add redaction logic
- [ ] Replace in-memory cache with distributed cache
- [ ] Add rate limiting to all endpoints
- [ ] Add request tracing/correlation IDs
- [ ] Resolve license inconsistency

---

**End of Code Review**
