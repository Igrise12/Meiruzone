# Local API contract, version 1

The backend runs at `http://127.0.0.1:8000`. `GET /openapi.json` exposes the
executable schemas. Interactive documentation is disabled to avoid loading
external assets. Application endpoints use `/api/v1` and return JSON.
SQLite persistence, safe IMAP retrieval, and the frontend integration are implemented.

## Shared values

- Categories: Recruitment, LinkedIn, Personal, Transaction, Newsletter,
  Promotion, Spam, Other. Priorities: High, Medium, Low. Values are
  case-sensitive; category and priority are independent.
- Unclassified is a filter/statistics bucket, not a human label. It means no
  human category and no predicted category. Other is a real category.
- IDs are stable opaque ASCII tokens matching `[A-Za-z0-9_-]{1,128}`. Clients
  must not derive mailbox identifiers from them. Demo IDs are `demo-01`
  through `demo-10`; ingestion assigns UUID-based IDs independently of IMAP UIDs.
- Dates are timezone-aware ISO 8601 strings serialized in UTC with `Z`.
  `receivedAt` is a timestamp that the frontend formats for display.
- Category confidence is a number from 0 through 100, including fractional
  values. It is not a priority score or a guarantee of calibrated probability.
- A missing prediction or human label is `null`. Unavailable fields inside
  an existing prediction are also `null`. A human label may contain only
  category or only priority, with its other field `null`.
- Resolve effective category and priority independently: human value, then
  predicted value. Missing category becomes Unclassified; missing priority
  remains unavailable.
- `needsReview` requires a predicted category, available confidence strictly
  below the configured threshold, and no human category. A priority-only
  label does not confirm category. Missing predictions/confidence do not
  enter Needs Review. Initial threshold: 70; model validation will tune it later.

## List and detail

`GET /api/v1/emails` accepts these parameters, combined with AND:

| Parameter | Default | Allowed values |
| --- | --- | --- |
| `q` | Empty | Up to 200 characters; trimmed, Unicode case-insensitive literal substring |
| `category` | No filter | A category or Unclassified |
| `priority` | No filter | High, Medium, Low |
| `needsReview` | `false` | Boolean; true selects review items, false applies no review restriction |
| `hasHumanLabel` | `false` | Boolean; true selects any human label, including category-only or priority-only; false applies no label restriction |
| `limit` | 50 | Integer, 1–100 |
| `offset` | 0 | Integer, 0–1,000,000 |

Omit category/priority to select all; do not send the frontend's `All` value.
Unknown query fields are rejected. `hasHumanLabel=true` combines with all other
filters; its `total` supplies the global confirmed-label count when other filters
are omitted. CSV review export pages over this filter independently of UI filters. Search includes sender, address, subject,
plain-text body, effective category, and effective priority. `%`, `_`, and SQL
syntax are literal text. Sort by receivedAt descending, then ID ascending.
`total` counts matching messages before pagination. An offset beyond the
results returns an empty page with the same matching total.

Example: `GET /api/v1/emails?category=Recruitment&needsReview=true&limit=1`

```json
{
  "items": [{
    "id": "demo-01",
    "sender": "Example Recruitment",
    "address": "sender1@example.test",
    "subject": "Synthetic Recruitment message",
    "receivedAt": "2026-10-01T12:00:00Z",
    "read": true,
    "hasAttachments": true,
    "prediction": {
      "category": "Recruitment",
      "priority": "High",
      "confidence": 61,
      "reasonCategory": null,
      "reasonPriority": null,
      "modelVersion": "synthetic-demo",
      "predictedAt": "2026-10-01T12:00:00Z"
    },
    "humanLabel": null,
    "needsReview": true
  }],
  "total": 1,
  "limit": 1,
  "offset": 0
}
```

List items omit body. `GET /api/v1/emails/{id}` returns the same record with
an additional `body` string containing plain text. Render it as escaped text;
do not execute HTML or load referenced resources. An unknown valid ID returns
404; an invalid ID returns 422.

## Labels and corrections

`PATCH /api/v1/emails/{id}/labels` accepts at least one category or priority:

```json
{"category": "Personal", "source": "correction"}
```

Source is manual or correction, defaulting to manual. Omitted label fields
retain previous human values. Explicit null cannot clear labels; deletion
is outside this version. Unknown fields, including client timestamps, are
rejected. Success returns 200 with the saved human label:

```json
{
  "category": "Personal",
  "priority": null,
  "confirmedAt": "2026-10-04T10:00:00Z",
  "source": "correction"
}
```

The server generates confirmedAt. Predictions remain unchanged. Saves are
transactional and immediately affect filters, Needs Review, and statistics.
This version stores the current human label without a feedback history.
Concurrent writes to the same field use the last committed value; independent
category and priority updates preserve each other.

## Category statistics

`GET /api/v1/category-stats` covers the complete local dataset. Count each
message once using its effective category, independently of list filters and
pagination. Return only aggregates:

```json
{
  "total": 10,
  "categories": [
    {"category": "Recruitment", "count": 1, "percentage": 10},
    {"category": "LinkedIn", "count": 1, "percentage": 10},
    {"category": "Personal", "count": 2, "percentage": 20},
    {"category": "Transaction", "count": 1, "percentage": 10},
    {"category": "Newsletter", "count": 1, "percentage": 10},
    {"category": "Promotion", "count": 1, "percentage": 10},
    {"category": "Spam", "count": 1, "percentage": 10},
    {"category": "Other", "count": 0, "percentage": 0},
    {"category": "Unclassified", "count": 2, "percentage": 20}
  ]
}
```

Always return these nine buckets in this order, including zero counts.
Percentages are whole numbers rounded to the nearest integer, with halves
rounded up, so their sum can differ from 100. Counts sum exactly to total.
An empty dataset returns total 0 and nine zero-count/percentage entries.
Refresh statistics after saves, sync, and future prediction updates.

## Sync

`GET /api/v1/sync` reports availability and the last request outcome:

```json
{
  "available": true,
  "demo": true,
  "state": "idle",
  "startedAt": null,
  "completedAt": null,
  "imported": 0,
  "processed": 0,
  "total": 0,
  "skipped": 0,
  "errorCode": null
}
```

Available/demo reflect current configuration. Available means explicit demo mode
or a configured IMAP host, username, and nonempty password; it does not assert
connectivity. Status contains no account, folder, or credentials. The last
outcome and timestamps persist across restarts, including when availability
changes. One backend process/worker owns each database.

| State | Meaning |
| --- | --- |
| idle | No sync has been requested |
| running | Current sync; completedAt is null |
| succeeded | Entire selected window processed without skips, including empty/demo sync |
| partial | One or more skips, or a failure after some messages were processed |
| failed | Failure before any message was processed |
| unavailable | Required IMAP configuration is incomplete |

All counters reset at the start of a run. `total` is the selected UID count
(0 until selection finishes). `processed` counts committed stores, including
updates of existing rows, plus skipped messages. `imported` counts newly
inserted rows only; `skipped` counts unusable or disappeared messages.
During an interrupted run, processed can be less than total. Each successful
message, its scoped identity, and progress counters commit together. Startup
recovers running as partial/failed with errorCode `sync_interrupted`, preserving
committed data and counters.

`POST /api/v1/sync` requires a JSON object:

```json
{"mode": "recent", "limit": 50}
```

Mode is recent or unread, default recent. Limit is a JSON integer from 1–100,
default 50; strings, fractions, and booleans are rejected. An empty object
uses defaults. Account, host, credentials, and mailbox are not request fields.

In explicit demo mode, return 200, state succeeded, demo true, timestamps,
and zero counters. This is a no-op with no mailbox contact or reseeding.
Incomplete configuration records unavailable and returns 503/sync_unavailable.

Real sync is synchronous. It opens the configured folder read-only over
verified TLS, searches highest UIDs excluding Deleted, and additionally requires
UNSEEN for unread mode. A request refreshes at most limit matching messages;
there is no history/backfill cursor. Read state comes from FLAGS. Body fetches
use BODY.PEEK and target text parts, with a combined 64 KiB header budget and
1 MiB encoded text budget per message. Attachment payloads and full raw mail
are never retained. Message-ID is internal metadata, not the deduplication key.

Deduplication uses account/folder/UIDVALIDITY/UID with independent local IDs.
Upserts preserve predictions and human labels. Deleted or moved provider mail
remains locally stored. A UIDVALIDITY change stops sync before message fetching
with `imap_uidvalidity_changed`; see the [recovery and backup instructions](../README.md#sync-real-mail).

Return 200 with the recorded final status for succeeded/partial. Return 503
with the standard error envelope for failed/unavailable; GET reports the saved
outcome. A concurrent POST returns 409/sync_in_progress without resetting the
running status. Retry uses the same bounded window and preserves prior commits.
Partial outcomes carry the failing code, or `imap_message_skipped` for skipped
messages. Error text never includes provider replies or private input.

| Code | Meaning |
| --- | --- |
| sync_unavailable | Configure IMAP locally |
| sync_in_progress | Wait for the active request |
| imap_auth_failed | Login failed |
| imap_tls_error | Verified TLS could not be established |
| imap_timeout | A connection/read operation exceeded 30 seconds |
| imap_connection_failed | Network connection failed |
| imap_mailbox_unavailable | Configured folder could not be opened |
| imap_protocol_error | Unsupported/missing protocol response or persistent UID identity |
| imap_uidvalidity_changed | Folder identifiers changed; preserve the old database |
| imap_message_skipped | Oversized, malformed, deleted, or disappeared selected message |
| storage_unavailable | Local storage operation failed |
| sync_failed | Sanitized unexpected sync failure |
| sync_interrupted | Backend restarted during sync |

## Access and errors

Bind to loopback. Accepted Host names are localhost, 127.0.0.1, and IPv6
loopback. Browser origins must match the configured allowlist exactly;
defaults are `http://localhost:5173` and `http://127.0.0.1:5173`. Reject other
origins, including null, for reads, writes, and preflights. CORS permits GET,
PATCH, POST and Content-Type / X-Meiruzone-Request, without cookies/credentials.

All writes require `Content-Type: application/json` and
`X-Meiruzone-Request: 1`. Bound the actual body to 4096 bytes, including streamed
requests. Origin-less local CLI calls require the same write marker. The
marker protects against browser cross-origin writes; it is not secret or
authentication against programs running on the machine.

API errors use this envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "fields": [{
      "field": "body.category",
      "code": "literal_error",
      "message": "Invalid or missing value."
    }]
  }
}
```

Field paths identify known contract fields only. Never echo input values,
unknown field names, paths, exception details, secrets, or email bodies.
Non-validation errors have an empty fields array.

| Status | Meaning / common code |
| --- | --- |
| 400 | Invalid Host / invalid_host, or rejected CORS preflight |
| 403 | Forbidden origin or missing write marker |
| 404 | Unknown message / email_not_found, or unknown route |
| 405 | Unsupported route method |
| 409 | Sync already running / sync_in_progress |
| 413 | Body exceeds 4096 bytes / request_too_large |
| 415 | Write body is not JSON / json_required |
| 422 | Invalid request / validation_error |
| 500 | Sanitized unexpected failure / internal_error |
| 503 | Sync unavailable or temporary storage failure |

## Frontend integration

The frontend uses native fetch against the local API by default. An explicit
`VITE_DATA_SOURCE=fixtures` keeps synthetic offline development/testing available.
Fixture browser labels are not automatically imported into SQLite. API failures
remain visible and recoverable without substituting demo data.

- List queries perform server-side search/filtering and 50-message pagination;
  only selected details load bodies. UTC receivedAt values format locally.
- Each record's humanLabel supports partial fields/nulls. Newly confirmed or
  changed fields and source are PATCHed, using the returned server timestamp.
  Failed-save drafts survive selection and data refreshes within the page session.
- Effective category/priority resolve human values independently before
  predictions. needsReview comes directly from the backend.
- Treemap counts/percentages and total come from category-stats. Global review
  and confirmed-label counters use unfiltered list totals with limit=1. Saves,
  sync completion, and explicit refresh reload records and aggregates.
- Sync offers recent/unread with limit 50, polls during running operations,
  identifies demo no-ops, and displays persisted partial/failure outcomes.
- CSV export pages over hasHumanLabel=true, keeps predicted and confirmed columns
  separate, escapes spreadsheet formulas, and aborts incomplete downloads.
- No credentials enter frontend settings/storage, API responses, or client logs.
  Configurable API URLs must target loopback; writes use the documented marker.

## Local category training data

`Repository.category_training_examples()` reads the configured SQLite repository
and returns dictionaries containing id, sender, address, subject, body, category,
optional priority, confirmed_at, and source, ordered by ID. Only records with a
non-null human category qualify. Predictions and priority-only labels never
become category ground truth. This is a local Python interface, not an HTTP
export or training operation. The existing schema needs no migration.
