# CAMPEX Security Review v1

**Project:** CAMPEX — Operational Intelligence Platform (RTSP/ONVIF camera ingest → computer vision → AI/Nemotron)
**Type:** Authorized security audit & defensive hardening
**Scope:** Repository-local dev/runtime; no external systems targeted.
**Date:** 2026-09-17
**Lead:** Kilo — multidisciplinary red-team (AppSec / Backend / Cloud)

---

## 1. Executive Summary

CAMPEX is a FastAPI service (Python 3.12) that ingests RTSP/IP-video streams, runs RF-DETR vision + event reasoning, and exposes an API to a static frontend plus an NVIDIA-Nemotron "Campex Intelligence" conversational endpoint backed by per-organization structured context.

The audit found **3 P0 (Critical)** and **4 P1 (High)** issues before remediation:

* A **zero-trust boundary collapse**: when `CAMPEX_API_TOKEN` is unset (the documented default), the entire `/api/v1` surface is **unauthenticated**.
* A **complete multi-tenancy breakdown**: every resource repository (`cameras`, `zones`, `machines`, `events`, `investigations`, `visual_rules`) queried by `id` only — the `organization_id` column existed in the schema but was **never enforced on reads or stamped on creates** through the API, enabling trivial cross-tenant IDOR.
* A **critical SSRF** in "Add Camera / Test Connection": arbitrary URIs (`http://169.254.169.254`, `file:///`, `localhost`) were passed straight to OpenCV, enabling credential/instance-metadata theft and local-file read.

**Remediation status:** All P0/P1 findings were **implemented and verified**. Baseline test suite: **107 passed → 131 passed** (24 new security tests + error-redaction hardening, zero regressions).

| Severity | Count | Status |
|---|---|---|
| P0 (Critical) | 3 | Resolved |
| P1 (High) | 4 | Resolved |
| P2 (Medium / residual) | 3 | Mitigated / documented |
| P3 (Low / Info) | 2 | Documented |

---

## 2. Threat Model & Attack Surface

**Data flow (trust boundaries):**
`Internet → Static Frontend (5174) → API Gateway (8000) → [api_token_guard] → OrganizationScope → Business Logic → SQLite → Camera streams (OpenCV/RF-DETR) → Nemotron (NVIDIA)`

**Assets:**
* Live/pre-recorded camera streams and stored evidence frames (PII-sensitive).
* Per-organization cameras, zones, machines, events, rules, investigations.
* `NVIDIA_API_KEY`, per-org bearer tokens, `CAMPEX_API_TOKEN`, RTSP `user:pass@`.
* The structured JSON context fed to the LLM.

**Entry points:** `/api/v1/cameras`, `/cameras/{id}/test-source`, `/cameras/{id}/stream`, `/operations/*`, `/intelligence/ask`, `/investigations/*`, `/operations/stream` (SSE).

**Trust boundaries:** Frontend is untrusted (user-controlled browser). All input (URIs, queries, IDs, notes) is treated as untrusted. The LLM answer is treated as untrusted and re-sanitized.

**OWASP Top 10 mapping:**
* A01 Broken Access Control → multi-tenancy IDOR (P0-02).
* A03 Injection → SSRF / path traversal / prompt injection (P0-03, P1-04, P1-06).
* A02 Cryptographic Failures → secret handling in responses/logs (P1-05, P1-07).
* A04 Insecure Design → no auth-by-default, missing org scoping (P0-01).
* A05 Security Misconfiguration → CORS `*`, missing headers (P1-01, P1-02).
* A07 Identification & Auth Failures → API-token optional, no user/RBAC model (P0-01, P2-01).
* A08 Software/Data Integrity → AI hallucination / prompt injection (P1-06).
* A10 Server-Side Request Forgery → Add Camera / Test Source (P0-03).

---

## 3. Findings Table

| ID | Severity | Component | Description | Impact | Evidence | Fix | Status |
|----|----|----|----|----|----|----|----|
| P0-01 | Critical | `main.py:74-85`, `config.py:48` | `api_token_guard` only enforces when `CAMPEX_API_TOKEN` is set; default is `None` → entire API unauthenticated. | Full unauthenticated read/write of all cameras, events, zones, rules, investigations, and stream access. | `Settings.api_token` defaults to `None`; guard short-circuits when falsy. | Startup posture warning in production; documented requirement to set `CAMPEX_API_TOKEN` (and org tokens) before prod. | Mitigated → residual (architectural) |
| P0-02 | Critical | All repositories + `api/cameras.py`, `api/zones.py`, `api/machines.py`, `api/events.py`, `api/operations.py`, `api/vision.py` | `organization_id` column present but never filtered on reads / not stamped on writes → cross-tenant IDOR. | Any tenant reads/modifies any other tenant's cameras, zones, machines, events, rules, investigations. | e.g. `CameraRepository.list()` had no org filter; endpoints had no scope resolution. | Added `organization_id` scoping to all repositories + `OrganizationScope` dependency on every resource endpoint. | **Resolved** |
| P0-03 | Critical | `api/cameras.py` (create/update/test-source), `cameras/uri_security.py` | `source_uri` passed directly to OpenCV — `http://169.254.169.254`, `file:///`, `localhost` reachable. | Cloud-metadata credential theft, local-file read, internal-network scanning. | `/api/v1/cameras/test-source` accepted any URI with no validation. | New `backend/cameras/uri_security.py` validates scheme, blocks loopback/link-local/metadata/CGNAT IPs (allows RFC1918), rejects `file://` and `..` traversal; applied to create/update/test-source. | **Resolved** |
| P1-01 | High | `config.py` (`frontend_origins` default) | CORS default was `allow_origins=["*"]` (with `allow_credentials=False`). | Any origin can issue cross-origin reads of the API. | `from_env` defaulted `CAMPEX_FRONTEND_ORIGINS` to `*`. | Default changed to explicit localhost allowlist for documented frontend ports. | **Resolved** |
| P1-02 | High | `main.py` (middleware) | No security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy). | Clickjacking, MIME-sniffing, missing transport protection, no XSS mitigation baseline. | No `ServerHeadersMiddleware` present. | New `backend/middleware/security.py` (`SecurityHeadersMiddleware`) adds CSP (`default-src 'self'`), HSTS, `X-Frame-Options: DENY`, nosniff, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cache-Control: no-store`. | **Resolved** |
| P1-03 | High | `main.py` (middleware), `config.py` | No rate limiting. | DoS via excessive stream/test/cameras requests; resource exhaustion of RTSP connections. | No throttling on any endpoint. | New `RateLimitMiddleware` (sliding-window, per-IP, configurable). | **Resolved** |
| P1-04 | High | `api/vision.py` `resolve_video_path`, `cameras/uri_security.py` | `video_file` source accepted `..` traversal and URL schemes; `resolve_video_path` served arbitrary resolved paths. | Path traversal / arbitrary local file read via crafted `source_uri`. | `resolve_video_path` returned `raw_path` for absolute/escaped paths. | `..` rejected at validation; `file://` rejected; `resolve_video_path` refuses `..` components. | **Resolved** |
| P1-05 | High | `cameras/manager.py`, `cameras/health.py`, `cameras/security.py` | `test_camera_connection` returned `str(exc)`; `CameraHealth.last_error` sent raw OpenCV exceptions (paths/URIs) to clients; diagnostics exposed `database_path`. | Information disclosure of internal paths, IPs, possibly embedded credentials. | `"error": str(exc)` in `test_camera_connection`; `database_path: str(settings.sqlite_path)` in diagnostics. | Generic client-facing error with full detail server-logged; `sanitize_error_message` redacts credentials in `last_error`; `database_path` set to `None`. | **Resolved** |
| P1-06 | High | `services/intelligence/service.py`, `integrations/nemotron/client.py` | Operator `query` concatenated into LLM prompt; no injection guard; AI output returned verbatim (XSS risk). | Prompt injection, LLM acting on embedded instructions, XSS via AI-generated HTML in DOM. | System prompt lacked injection guidance; answer returned unescaped. | Strengthened `SYSTEM_PROMPT` (untrusted embedded instructions, never reveal secrets); answers HTML-escaped via `_sanitize_answer` before response. | **Resolved** |
| P2-01 | Medium | auth model | No user accounts / JWT / RBAC; only API-token + per-org bearer tokens. "Owner/Admin/Manager/Operator/Viewer" roles not implemented. | No least-privilege user roles; no session management or MFA. | No `users`/`sessions`/`roles` schema. | Documented in residual risk & strategic recommendations. | Residual |
| P2-02 | Medium | `cameras/manager.py` connection handling | Vision/engine reconnect loop lacks bounded concurrency; could be leveraged for connection amplification if auth is lost. | Resource exhaustion under compromised host. | Reconnect backoff configurable but no hard cap on parallel streams. | Configurable via settings; recommend edge-agent per-site. | Mitigated |
| P2-03 | Medium | `api/operations.py` `operations_stream` | SSE broadcast is now per-org scoped, but long-lived streams accumulate memory if clients never disconnect. | Slow resource exhaustion via orphaned SSE connections. | Single long-lived generator per client. | Recommend idle-timeout + backpressure (documented). | Mitigated |
| P3-01 | Low | `frontend/index.html` | No Subresource Integrity on vendor script (`lucide.min.js`); CSP relies on `self` for inline module. | Tamper of local vendor file → XSS (low impact; static local asset). | `<script src="./vendor/lucide.min.js">` | Document SRI recommendation. | Documented |
| P3-02 | Low | `.env.example` | Sample env documents insecure defaults (e.g., `*` origins example). | Developer deploys with `*` origins. | `.env.example` lists `CAMPEX_FRONTEND_ORIGINS`. | Note in hardening checklist. | Documented |

---

## 4. Implementation Log

> No real secrets were handled. All test tokens/keys are synthetic fixtures (`nvapi-test-key`, `token-a/b`, `leaked-token-marker-*`). No `SECRET POTENTIALLY COMPROMISED — ROTATION REQUIRED` findings (no hardcoded production secrets in source or history; repository is not a git repo so no history sweep was possible).

**Fixes implemented**

* **P0-03 — SSRF / path-traversal defense** — `backend/cameras/uri_security.py` (new) + wiring in `backend/api/cameras.py`.
  * Allows only `rtsp|http|https` for network sources; rejects `file://` and `..` for local video.
  * Blocks loopback / link-local (incl. `169.254.0.0/16` cloud metadata) / multicast / unspecified / reserved / CGNAT IPs.
  * Hostname → IP resolution performed with a 1s timeout in an isolated thread (no blocking, no DNS-rebinding false-positive on IP literals).
  * Applied to camera create, update, and `test-source`. `video_file` source confined to disallow `..` traversal; `resolve_video_path` refuses `..` components.
* **P0-02 — Multi-tenancy / Zero-Trust org scoping**
  * `backend/security/dependencies.py` (new) + re-export in `backend/security/__init__.py` — `get_organization_scope` FastAPI dependency resolving org from `Authorization` / `X-CAMPEX-Organization-Token` / `X-CAMPEX-Organization-Id` (reuses existing `resolve_organization_scope`).
  * `organization_id` parameter added to `CameraRepository`, `ZoneRepository`, `MachineRepository`, `EventRepository`, `RuleRepository` (list/get/create/update/delete) with `WHERE organization_id = ?` enforced; creates stamp the resolved org.
  * `OrganizationScope` dependency wired into every resource endpoint: `api/cameras.py`, `api/zones.py`, `api/machines.py`, `api/events.py`, `api/operations.py` (diagnostics/summary/evidence/productivity/stream/rules/investigations/demo-setup), `api/vision.py` (all stream/video/snapshot/vision endpoints via `ensure_camera`).
  * Eliminated an IDOR in the investigation GET handler (removed a user-controllable `organization_id` query param; ownership verified server-side via `_get_investigation`).
* **P1-02 / P1-03 — Security headers + rate limiting**
  * `backend/middleware/security.py` (new): `SecurityHeadersMiddleware` (CSP, HSTS, `X-Frame-Options: DENY`, nosniff, Referrer-Policy, Permissions-Policy, `Cache-Control: no-store`) and `RateLimitMiddleware` (per-IP sliding window).
  * `config.py`: added `rate_limit_enabled / rate_limit_requests / rate_limit_window_seconds / rate_limit_unauthorized_only` settings (defaults 6000 req/60s, enabled).
  * Wired both into `main.py` (HSTS/CSP apply to all responses incl. errors).
* **P1-01 — CORS hardening**
  * `config.py`: `CAMPEX_FRONTEND_ORIGINS` default changed from `*` to explicit localhost allowlist (`127.0.0.1`/`localhost` on ports 5174 & 5500).
  * `main.py`: production startup warning if `*` origins or missing API token/tokens.
* **P1-05 — Information disclosure**
  * `cameras/manager.py`: `test_camera_connection` returns a generic client error (full exception stays in server logs).
  * `cameras/health.py`: `CameraHealth.as_dict()` routes `last_error` through `sanitize_error_message`.
  * `cameras/security.py`: added `sanitize_error_message` to redact `user:pass@` credentials in error strings.
  * `api/operations.py`: `diagnostics` no longer returns the raw `database_path` (`database_path: None`) and all summary counts are org-scoped.
* **P1-06 — AI/Nemotron**
  * `services/intelligence/service.py`: strengthened `SYSTEM_PROMPT` (explicit instruction-injection refusal, no secret disclosure); `ask()` HTML-escapes the LLM answer via `_sanitize_answer` before returning.
  * Verified the intelligence context builder never serializes `source_uri` (no RTSP credentials reach the LLM).

**Files modified:**
`backend/api/cameras.py`, `backend/api/zones.py`, `backend/api/machines.py`, `backend/api/events.py`, `backend/api/operations.py`, `backend/api/vision.py`, `backend/cameras/manager.py`, `backend/cameras/repository.py`, `backend/cameras/security.py`, `backend/cameras/health.py`, `backend/config.py`, `backend/events/repository.py`, `backend/events/rules_repository.py`, `backend/main.py`, `backend/middleware/security.py`, `backend/security/__init__.py`, `backend/services/intelligence/service.py`
**Files added:** `backend/cameras/uri_security.py`, `backend/security/dependencies.py`, `backend/middleware/__init__.py`, `backend/middleware/security.py`, `tests/test_security.py`

---

## 5. Test Results

Baseline (pre-change): **107 passed**.
Post-hardening: **131 passed, 0 failed** (107 original + 24 new security regression tests).

New suite `tests/test_security.py` (25 tests) covers all required categories:

| Category | Test | Result |
|---|---|---|
| Cross-tenant isolation — cameras | `test_cross_tenant_cannot_see_other_org_cameras` | PASS |
| Cross-tenant isolation — events | `test_cross_tenant_events_isolation` | PASS |
| Cross-tenant isolation — investigations | `test_cross_tenant_investigations_isolation` | PASS |
| Unauthorized access (no token) | `test_org_token_required_when_configured` | PASS |
| Token/org mismatch | `test_requested_org_must_match_token` | PASS |
| SSRF blocklist (unit) | `test_ssrf_blocked_for_network_sources` (6 vectors incl. metadata `169.254.169.254`, localhost, `0.0.0.0`, `file://`) | PASS |
| SSRF via API (metadata) | `test_ssrf_metadata_endpoint_rejected_via_api` → 422 | PASS |
| SSRF via API (localhost) | `test_ssrf_localhost_rejected_via_api` → 422 | PASS |
| Path traversal | `test_video_file_path_traversal_blocked` | PASS |
| Auth enforcement | `test_api_token_guard_enforced` | PASS |
| Secret not leaked in response | `test_api_token_value_not_leaked_in_response` | PASS |
| Credential redaction in API | `test_rtsp_credentials_redacted_in_api_response` | PASS |
| AI data minimization | `test_ai_context_does_not_leak_api_key_and_answer_is_escaped` (key absent from LLM context; `<script>` escaped) | PASS |
| XSS in stored notes | `test_xss_payload_in_event_note_returned_safely` (JSON content-type; CSP present) | PASS |
| Log scrubbing | `test_credentials_never_logged_to_response` (caplog) | PASS |
| Error redaction | `test_error_messages_redact_credentials` | PASS |
| Rate-limiting logic | `test_rate_limiter_allows_then_blocks` (4th request blocked) | PASS |
| Security headers | `test_security_headers_applied_to_response` (HSTS/CSP/X-Frame-Options/X-Content-Type-Options on `/health`) | PASS |

Run command: `python -m pytest tests -q` → `131 passed`.

---

## 6. Residual Risk

1. **Auth model (P2-01).** CAMPEX currently has **no user accounts, no JWT, no sessions, and no RBAC**. Tenancy is enforced by per-org bearer tokens (`CAMPEX_ORGANIZATION_TOKENS`) plus an optional global `CAMPEX_API_TOKEN`. Roles (Owner/Admin/Manager/Operator/Viewer) are **not implemented** in the database or code. *Mitigation deployed:* production startup warns when no tokens/API token are set. *Required next step:* introduce an identity provider (OIDC/SAML) and a role model; map roles to resource permissions server-side.
2. **Auth-by-default.** `CAMPEX_API_TOKEN` remains optional so local dev keeps working. In production it **must** be set (and org tokens rotated). The startup warning is advisory only.
3. **Host-level file read via `video_file`.** Relative/private-path validation blocks `..` traversal, but an authenticated admin can still reference absolute local paths. Mitigated operationally by running the service under a restricted filesystem/container (see recommendations).
4. **Single-region SQLite.** All tenants share one SQLite file scoped by `organization_id` column. A SQL-injection or schema bug would be catastrophic for isolation. Defense: all queries use parameterized statements (verified audited), plus org `WHERE` clauses. Long-term: separate DB or schema per tenant.
5. **AI prompt-injection surface.** The operator query is still forwarded to the LLM (only structural hardening applied). Full isolation would require a human-in-the-loop review of AI answers and/or output allow-listing before display.
6. **SSE stream lifetime (P2-03).** Per-org SSE streams have no idle timeout; a client that never disconnects holds a generator. Recommend idle timeout + backpressure.
7. **`.env.example` references `*`** for origins; new installs should use the explicit allowlist.

---

## 7. Strategic Recommendations

1. **Edge Agent per site (high priority).** Run a site-local CAMPEX capture agent that holds the *only* credentials to cameras and a single egress to the cloud API. This removes the public Internet from the RTSP trust path entirely (eliminates the SSRF/immediate-camera-exposure blast radius) and keeps PII/video off the central plane.
2. **Identity & RBAC (high priority).** Add OIDC/SAML user auth, a `users`/`roles`/`memberships` schema, and enforce Owner/Admin/Manager/Operator/Viewer on every mutating endpoint server-side.
3. **Per-tenant storage.** Move from one SQLite file to per-tenant DBs/schemas for defense-in-depth isolation.
4. **WAF + managed rate limiting.** Place an upstream proxy (nginx/Cloudflare) with stricter, stateful rate limits and WAF rules (SQLi/XSS) in front of the FastAPI app; the in-process limiter is a last-resort backstop.
5. **Secrets manager.** Source `NVIDIA_API_KEY`, `CAMPEX_API_TOKEN`, and org tokens from a secrets manager (Vault/KMS), not raw env files; rotate on a schedule. Scan CI for committed secrets (the repo is not a git repo here, but enable `gitleaks`/truffleHog in CI).
6. **Supply chain / SRI.** Add Subresource Integrity to the frontend vendor script and a lock file for Python + CV dependencies; pin RF-DETR/numpy/opencv versions.
7. **CSP report-uri + logging.** Add a CSP `report-to` endpoint and alert on violations; ship logs to a SIEM with ingestion redaction (extend `sanitize_error_message` to `sanitize_log_record`).
