# Local API contract, version 1

The backend runs at `http://127.0.0.1:8000`. `GET /openapi.json` exposes the
executable schemas. Interactive documentation is disabled to avoid loading
external assets. Application endpoints use `/api/v1` and return JSON.
SQLite persistence is implemented; IMAP retrieval and frontend integration
remain later milestones.

## Shared values

- Categories: Recruitment, LinkedIn, Personal, Transaction, Newsletter,
  Promotion, Spam, Other. Priorities: High, Medium, Low. Values are
  case-sensitive; category and priority are independent.
- Unclassified is a filter/statistics bucket, not a human label. It means no
  human category and no predicted category. Other is a real category.
- IDs are stable opaque ASCII tokens matching `[A-Za-z0-9_-]{1,128}`. Clients
  must not derive mailbox identifiers from them. Demo IDs are `demo-01`
  through `demo-10`; future ingestion must assign IDs independently of IMAP UIDs.
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
| `limit` | 50 | Integer, 1–100 |
| `offset` | 0 | Integer, 0–1,000,000 |

Omit category/priority to select all; do not send the frontend's `All` value.
Unknown query fields are rejected. Search includes sender, address, subject,
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

## Sync foundation

`GET /api/v1/sync` reports availability and the last request outcome:

```json
{
  "available": true,
  "demo": true,
  "state": "idle",
  "startedAt": null,
  "completedAt": null,
  "imported": 0,
  "errorCode": null
}
```

Available/demo reflect the current configuration. State is idle before any
request, succeeded after demo sync, or unavailable after an IMAP request.
The last outcome and timestamps persist across restarts, including when
availability changes.

`POST /api/v1/sync` requires a JSON object:

```json
{"mode": "recent", "limit": 50}
```

Mode is recent or unread, default recent. Limit is a JSON integer from 1–100,
default 50; strings, fractions, and booleans are rejected. An empty object
uses defaults. Account, host, credentials, and mailbox are not request fields.

In explicit demo mode, return 200 with the status shape above, state succeeded,
demo true, timestamps, and imported 0. This is a no-op: no mailbox contact,
reseeding, or message flag changes. Otherwise, record an unavailable outcome
and return 503 with code sync_unavailable. Configured IMAP credentials do not
enable real sync yet. No scheduler or background worker is introduced.

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
| 413 | Body exceeds 4096 bytes / request_too_large |
| 415 | Write body is not JSON / json_required |
| 422 | Invalid request / validation_error |
| 500 | Sanitized unexpected failure / internal_error |
| 503 | Sync unavailable or temporary storage failure |

## Frontend adapter mapping for task 4

The fixture adapter remains the default. Browser labels are demo-only and
are not automatically imported into SQLite.

- Replace bulk getEmails/client filtering with list queries, paging, and
  detail fetching. Format receivedAt into the display-only received value.
- Use each record's humanLabel instead of bulk getLabels. Extend the current
  frontend label type to support partial labels and map explicit nulls.
- PATCH changed fields and source; use the returned server timestamp and
  label rather than browser-generated confirmedAt.
- Map statistics.categories to existing chart rows and retain statistics.total.
- Use server needsReview so the configured threshold is authoritative.
- Read sync status, distinguish demo no-ops, and refresh inbox/aggregates after
  future real imports. Retain failure/retry states.
- Keep mailbox credentials out of frontend variables, storage, and logs.
