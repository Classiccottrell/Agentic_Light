---
name: server-review
description: Use when reviewing, writing, or auditing backend/server code and APIs - error handling at trust boundaries, input validation, auth/authz, idempotency, logging, resource cleanup, N+1 queries, outbound-call timeouts/retries, HTTP API design shape, injection risks, SSRF, rate/resource limiting, concurrency and transaction correctness, data exposure, or deciding what needs a test. Stack-agnostic; applies to any language/framework doing server-side or API work.
---

# Server & API Review

## Overview

Server code fails differently than UI code: the cost of a missed edge case is
a data leak, a double charge, or an outage, not a misaligned button. This
skill is a checklist-driven audit method for backend/API code — no framework
or language assumed, since "server work" spans too many stacks to lock into
one.

## When to Use

- Reviewing a PR that touches a server, API, worker, or backend service
- Writing new backend/API code and self-checking before it ships
- Auditing an existing service for correctness/security gaps
- Deciding what a change actually needs a test for

**When NOT to use:** pure frontend/UI work with no server component; a
one-line config or docs change with no logic.

## Method

Run the code-review checklist first, then the HTTP API design pass. Only
apply the sections relevant to what changed — a pure internal library change
doesn't need the API design pass; a new list endpoint needs both.

### 1. Code-review checklist

- **Error handling at trust boundaries** — every point where data crosses
  from an untrusted caller (HTTP request, message queue, another service,
  file upload) is handled by the appropriate boundary/middleware, not left
  to throw raw uncaught. Errors surfaced to a caller don't leak stack
  traces, internal paths, or query text.
- **Input validation** — validated at the boundary, not assumed valid
  downstream because "the frontend already checks it." Type, range,
  length, and shape all checked before use, not just presence.
- **Auth / authz** — authentication (who is this) and authorization (are
  they allowed to do *this specific thing to this specific resource*) are
  separate checks. A missing per-resource ownership check (an ID from the
  request used to fetch/mutate another user's row) is the single most
  common real-world authz bug — check for it explicitly.
- **Idempotency for retryable operations** — anything a client, queue, or
  load balancer might retry (payment capture, order creation, webhook
  delivery) is safe to receive twice. An idempotency key, a natural unique
  constraint, or an upsert — not "retries are rare so it's fine."
- **Logging without leaking secrets** — request/response logs, error logs,
  and tracing spans never contain passwords, tokens, API keys, full card
  numbers, or other secrets, even in a debug path that "shouldn't run in
  prod."
- **Resource cleanup** — connections, file handles, locks, and
  transactions are released on every exit path, including the error path.
  A `finally`/`defer`/`using`/context-manager equivalent, not a cleanup
  call only on the happy path.
- **N+1 query patterns** — a loop that issues one query per iteration
  against a data store. Batch-fetch or join instead, especially in list
  endpoints and anything iterating over a collection from an earlier
  query.
- **Timeout / retry policy on outbound calls** — every network call to
  another service, database, or third-party API has an explicit timeout
  (no unbounded wait). Retries are operation-aware: only idempotent
  operations retry, with a bounded policy (no infinite loop, no
  retry-storm risk on a downstream outage) — a configured timeout alone is
  often sufficient for non-idempotent calls.
- **Injection** — SQL, command, template, and log injection: untrusted
  input never concatenated into a query/command/shell string; parameterized
  queries or an equivalent escape path used instead.
- **SSRF** — any server-side call to a URL built from user input
  (webhooks, image-fetch-by-URL, link previews) validates/allowlists the
  target and blocks internal/private address ranges.
- **Rate / resource limiting** — endpoints and expensive operations
  (uploads, search, bulk export) have a rate or concurrency limit; nothing
  unbounded is reachable by an untrusted caller.
- **Concurrency / transaction correctness** — operations that read-then-write
  shared state use a transaction, lock, or optimistic-concurrency check
  (not a race-prone read-modify-write); transaction boundaries match the
  actual unit of work.
- **Data exposure** — responses return only the fields the caller is meant
  to see, not a whole internal row/object serialized as-is (e.g. password
  hashes, internal flags, other users' data via an over-broad join).

### 2. HTTP API design pass

The checks below assume an HTTP/REST-shaped API. An RPC, GraphQL, or
queue-based API needs its own equivalent checks (status-code conventions
don't apply; error-shape and versioning concerns still do) — not covered
here.

- **Consistent error response shape** — one error envelope across the
  API (status code + machine-readable code + message), not a different
  shape per endpoint or per exception type.
- **Versioning approach stated somewhere** — even if it's "no versioning
  yet, breaking changes require a major bump," the decision is explicit
  and documented, not implicit.
- **Pagination for list endpoints** — any endpoint that can return an
  unbounded collection paginates (cursor or offset), rather than
  returning "all rows" and hoping the table stays small.
- **Idempotency keys for POST-that-creates** — a POST that creates a
  resource and might be retried accepts a client-supplied idempotency key
  (or has an equivalent unique-constraint guard) so a retry doesn't create
  a duplicate.
- **Sensible HTTP status codes** — 2xx only on real success, 4xx for
  caller error, 5xx for server error, and the specific code (401 vs 403,
  404 vs 410, 409 for conflict) chosen deliberately, not defaulted to 200
  or 500 for everything.

### 3. Testing strategy

Test business logic and edge cases at trust boundaries: validation
rejection paths, authz denial paths, idempotency retries, the N+1-prone
loop rewritten as a batch query, error-response shape for each failure
mode. These are where regressions are expensive and silent.

Don't test framework glue (a router wiring a path to a handler), trivial
getters/setters, or a straight pass-through to a well-tested library call.
100% coverage is not the goal — coverage of the paths that can actually go
wrong is. If a test would only ever fail when the framework itself is
broken, it's not pulling weight.
