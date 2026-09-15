# Approval Pack

[![CI](https://github.com/VsevaTech/approval-pack/actions/workflows/ci.yml/badge.svg)](https://github.com/VsevaTech/approval-pack/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

**Know exactly what was approved — and which version.**

Most approvals in small companies happen in a chat window:

> — Ок
> — Согласовано
> — Да, делаем
> — Approved

Three weeks later nobody can say *which* version of the budget, the contract,
the landing page or the exception that "Approved" referred to. The document has
been edited since. The thread has scrolled away. The person who said yes
remembers a different number.

Approval Pack fixes the narrow part of that problem that is actually fixable:
it **freezes the exact content** you asked about, hashes it with SHA-256, hands
you a single unguessable link to send, and records the reviewer's decision
against that hash. Afterwards the snapshot cannot change, and anyone holding the
evidence file can prove which bytes were approved.

> ⚠️ **Approval Pack is not an electronic signature.** It is not a qualified or
> advanced e-signature, and it is not a certified document-workflow system. It
> creates an internal, verifiable record of "this content, this decision, this
> time" — nothing more. See [Limitations](#limitations).

---

## Table of contents

- [Quick start](#quick-start)
- [The flow](#the-flow)
- [Demo walkthrough](#demo-walkthrough)
- [Architecture](#architecture)
- [Security model](#security-model)
- [Evidence format](#evidence-format)
- [Configuration](#configuration)
- [Tests](#tests)
- [Limitations](#limitations)
- [License](#license)

---

## Quick start

### With Docker (recommended)

```bash
git clone https://github.com/VsevaTech/approval-pack.git
cd approval-pack
docker compose up --build
```

Open <http://localhost:8000>.

### Without Docker

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # optional — defaults work as-is
uvicorn app.main:app --reload
```

Open <http://localhost:8000>. The SQLite database and the snapshot directory are
created on first start; there is no migration step and nothing to configure.

---

## The flow

```
create approval
  → add text or a file
  → immutable snapshot + SHA-256
  → cryptographically random review link
  → send the link to the reviewer
  → reviewer opens the snapshot (no account, no registration)
  → Approve / Reject
  → decision recorded against the hash
  → downloadable evidence
```

Statuses: `PENDING` → `APPROVED` | `REJECTED`, or `EXPIRED` if the optional
deadline passes before anyone decides.

Rules the app enforces:

| Rule | Where |
| --- | --- |
| A comment is mandatory when rejecting, optional when approving | `app/services.py` |
| A decision can be recorded exactly once | `AlreadyDecidedError`, HTTP 409 |
| An expired approval cannot be decided | `ExpiredError`, HTTP 410 |
| Once decided, the snapshot and its hash are frozen | `app/immutability.py` |
| The hash recorded at decision time is stored separately and compared | `app/evidence.py` |

---

## Demo walkthrough

Seed the sample approval from the task description:

```bash
python examples/seed_demo.py
```

```
Demo approval created.
  Approval ID : 0305aa083a1a45a7b13cca0c328d2fbb
  Status      : PENDING
  SHA-256     : e80ff9799b4803ed1297cfdd6179d9eaa2d94dc36102297173882ff23c9c6593
  Owner page  : http://localhost:8000/approvals/0305aa08...
  Review link : http://localhost:8000/review/xu0tij3EPELbimrFJAQlxDaXIVd7cWkGH4g-jCv3HkU
```

Then:

1. Copy the review link.
2. Open it in an incognito window or a different browser — no login is involved.
   The reviewer sees the frozen content, its hash, and two buttons:

   ```
   Marketing campaign proposal                      [ PENDING ]
   Q4 campaign. Please confirm the budget and the launch date.

   ┌─ What you are asked to approve ───────────────────────────┐
   │  Budget: EUR 2,500                                        │
   │  Launch date: 1 October                                   │
   └───────────────────────────────────────────────────────────┘
   SHA-256 e80ff9799b4803ed1297cfdd6179d9eaa2d94dc36102297173882ff23c9c6593

   Your name  [ Anna Weber        ]   Your email [ anna@example.com ]
   Comment    [ Approved — budget and date confirmed.            ]

   [ Approve ]  [ Reject ]
   Recorded: your decision, the time, your name/email if entered,
   your comment, and the SHA-256 of this exact version.
   ```

3. Press **Approve**, optionally leaving a name and a comment.
4. Back on the owner page, the status is now `APPROVED` and the version check
   reads `MATCH`.
5. Download the evidence (`Download JSON`).
6. Verify the hash yourself, against the content you still have on disk:

```bash
printf 'Budget: EUR 2,500\nLaunch date: 1 October' > approved.txt
sha256sum approved.txt
# e80ff9799b4803ed1297cfdd6179d9eaa2d94dc36102297173882ff23c9c6593

python examples/verify_evidence.py evidence.json --file approved.txt
# OK  decision hash == snapshot hash (the decided version is this version)
# OK  the file you have is exactly what was approved
```

`examples/verify_evidence.py` has no dependencies beyond the standard library,
so whoever receives an evidence file can check it without installing anything.

---

## Architecture

A deliberately small, single-process application. No queue, no cache, no
external identity provider — none of them would earn their keep here.

```
app/
  main.py            FastAPI app factory, security headers, owner login
  config.py          Pydantic settings (APPROVAL_PACK_* env vars)
  models.py          SQLAlchemy 2.0 models: Approval, Decision
  services.py        All business rules live here, framework-free
  security.py        Tokens, hashing, filename sanitising, upload allowlist
  storage.py         Snapshot files on disk, addressed by approval id
  immutability.py    ORM guard freezing a decided approval
  evidence.py        JSON + HTML evidence records
  routers/
    approvals.py     Owner area: create, list, inspect, evidence
    review.py        Public tokenised review + decision
  templates/         Jinja2, autoescaped
  static/            CSS + ~40 lines of progressive enhancement, no CDN
tests/               119 tests
examples/            Demo seed + dependency-free evidence verifier
```

Request flow for a decision:

```
POST /review/{token}/decision
  → ApprovalService.get_by_token()      indexed lookup + constant-time compare
  → ApprovalService.record_decision()   status checks, comment rule
  → Decision row stores snapshot_sha256 as shown to the reviewer
  → Approval.status becomes APPROVED/REJECTED (final)
  → immutability guard refuses every later write to the snapshot
```

**Layering.** `services.py` knows nothing about HTTP; the routers do nothing but
translate. That is why most of the test suite drives the service directly and
runs in milliseconds, with a smaller HTTP layer on top.

**Storage.** SQLite by default (`APPROVAL_PACK_DATABASE_URL`); the models use
plain SQLAlchemy 2.0 typing, so PostgreSQL works by changing the URL. Uploaded
files live on disk rather than in the database, named `<approval_id><ext>`.

---

## Security model

**Review tokens.** `secrets.token_urlsafe(32)` — 256 bits from the OS CSPRNG,
43 URL-safe characters. Unpredictable and not enumerable. A token is a *bearer
capability*: whoever holds the link can record the decision, which is exactly
how a "send this to the reviewer" flow has to work.

**No sequential identifiers.** Primary keys are UUID4 hex strings and never
appear in a public URL. The public surface only ever exposes the token.

**Uploads.** Extension allowlist (`txt md csv json pdf png jpg jpeg gif webp
docx xlsx pptx`). Everything scriptable — `html`, `htm`, `xhtml`, `js`, `mjs`,
`svg`, `xml` — is refused, and so is anything not in the list. Size is capped
(`APPROVAL_PACK_MAX_UPLOAD_BYTES`, 5 MiB by default) and the request body is
read with a hard ceiling, so an oversized upload never reaches the disk.

**Uploaded files can never execute.** The client's `Content-Type` is discarded;
the served type comes from our own allowlist. Downloads go out as
`Content-Disposition: attachment` with `X-Content-Type-Options: nosniff` and
`Content-Security-Policy: default-src 'none'; sandbox`. Inline rendering is
permitted only for a short list of media types that cannot carry script
(`png`, `jpeg`, `gif`, `webp`, `pdf`) — never `text/html`, never `image/svg+xml`.

**Filenames.** `sanitize_filename()` strips POSIX and Windows path separators,
NFKD-folds unicode to ASCII, keeps only `[A-Za-z0-9._-]`, collapses dot runs so
`..` cannot survive, and bounds the length. It is used for display only.

**Path traversal.** The on-disk name is `<approval_id><allowlisted_ext>` — no
byte of user input reaches the path. `SnapshotStorage.path_for()` additionally
rejects separators and `..`, and `resolve_within()` verifies the resolved path
is inside the storage directory. Three independent layers; the tests attack all
of them.

**Immutability.** After a decision, `app/immutability.py` raises
`SnapshotImmutableError` on any attempt to change the title, description,
snapshot, hash, token, timestamps or status — at the ORM flush level, so it
holds regardless of which code path tried. Decisions cannot be deleted either.
And if someone edits the database underneath the application, the recomputed
hash stops matching: the owner page shows the integrity check as failed, and the
evidence still carries the hash that was actually approved.

**XSS.** Jinja2 autoescaping is on; snapshot text is rendered inside `<pre>` as
escaped text. The app ships a strict CSP (`default-src 'self'`, no
`unsafe-inline`, `object-src 'none'`, `frame-ancestors 'none'`), and nothing is
loaded from a CDN — the only script is `app/static/app.js`, served from our own
origin.

**Works without JavaScript.** Every page is server-rendered and every action is
a plain HTML form post. `app.js` adds two conveniences on top: a copy button for
the review link, and an async decision submit that swaps in the fragment the
server returns. It sends `HX-Request: true`, the convention htmx uses, so htmx
can replace the file without touching the server.

**Owner area.** Set `APPROVAL_PACK_OWNER_PASSWORD` to require a shared password
for creating and listing approvals (session cookie: HMAC-signed, `HttpOnly`,
`SameSite=Lax`, `Secure` over HTTPS). Left empty, the owner area is open — fine
on `localhost`, not fine on a public host. Review links are never affected:
reviewers must not need an account.

**What is deliberately absent:** React, Redis, Celery, Kafka, OAuth. None of
them are needed to freeze a snapshot and record one decision.

---

## Evidence format

`GET /approvals/{id}/evidence.json` and `/evidence.html`, both served as
downloads. The JSON is versioned (`approval-pack/evidence/v1`):

```json
{
  "schema": "approval-pack/evidence/v1",
  "approval_id": "0305aa083a1a45a7b13cca0c328d2fbb",
  "title": "Marketing campaign proposal",
  "status": "APPROVED",
  "decision": "APPROVED",
  "created_at": "2026-09-15T07:17:46.691612+00:00",
  "decided_at": "2026-09-15T07:18:11.479942+00:00",
  "reviewer": { "name": "Anna Weber", "email": "anna@example.com" },
  "comment": "Approved — budget and date confirmed.",
  "snapshot": {
    "kind": "TEXT",
    "media_type": "text/plain; charset=utf-8",
    "size_bytes": 40,
    "sha256": "e80ff9799b4803ed1297cfdd6179d9eaa2d94dc36102297173882ff23c9c6593"
  },
  "decided_snapshot_sha256": "e80ff9799b4803ed1297cfdd6179d9eaa2d94dc36102297173882ff23c9c6593",
  "disclaimer": "Approval Pack records an immutable snapshot ..."
}
```

`snapshot.sha256` is the hash of the stored content; `decided_snapshot_sha256`
is the hash captured when the reviewer pressed the button. **Their equality is
the product.** The HTML evidence renders the same fields as a printable page
with an explicit `MATCH` / `MISMATCH` verdict, with no scripts and no external
references.

---

## Configuration

Every setting is an environment variable prefixed `APPROVAL_PACK_`; see
[`.env.example`](.env.example). All of them have working defaults.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APPROVAL_PACK_BASE_URL` | `http://localhost:8000` | Base URL used to build review links |
| `APPROVAL_PACK_DATABASE_URL` | `sqlite:///./data/approval_pack.db` | Any SQLAlchemy URL |
| `APPROVAL_PACK_STORAGE_DIR` | `./data/snapshots` | Uploaded snapshot files |
| `APPROVAL_PACK_MAX_UPLOAD_BYTES` | `5242880` | Upload ceiling |
| `APPROVAL_PACK_MAX_TEXT_CHARS` | `200000` | Text snapshot ceiling |
| `APPROVAL_PACK_REVIEW_TOKEN_BYTES` | `32` | Entropy per review token |
| `APPROVAL_PACK_OWNER_PASSWORD` | *(empty)* | Password for the owner area; empty = open |
| `APPROVAL_PACK_SECRET_KEY` | `change-me` | Signs the owner session cookie |

Set `APPROVAL_PACK_BASE_URL` to the URL reviewers will actually open — otherwise
the links you copy point at localhost.

---

## Tests

```bash
pytest          # 119 tests
ruff check .
```

Covered, among other things: approval creation, review-token uniqueness and
entropy, SHA-256 of text and of binary content, approve, reject, reject without
a comment, expiry, a second decision attempt, modification after a decision
(service layer, ORM layer and raw-SQL tampering), evidence in both formats,
invalid tokens, upload size and type validation, filename sanitising, path
traversal, XSS escaping, security headers, clean start with an empty database.

The test that matters most is the hash chain, in `tests/test_evidence.py`:

```
create snapshot → calculate hash → approve → evidence hash == original hash
```

It is asserted for text snapshots, for file snapshots, and for a snapshot that
was edited *before* the decision (the evidence must pin the version actually
shown to the reviewer, not the first one).

CI runs on every push and pull request: `ruff check .` and `pytest` on Python
3.12 and 3.13, a clean-start smoke test against an empty directory, a Docker
image build that boots the container and polls `/healthz`, and a
`docker compose up --build` job that drives the whole product flow — seed the
demo approval, approve it through its review link, download the evidence, and
assert both hashes equal the SHA-256 of the approved bytes.

---

## Limitations

Worth being explicit about, because an approval tool that overstates itself is
worse than none:

- **Not an electronic signature.** No certificates, no identity verification, no
  qualified/advanced e-signature status, no legal presumption of anything. If
  you need a legally binding signature, use a service that provides one.
- **Reviewer identity is self-declared.** Whoever opens the link can type any
  name. The link is the only credential, so treat it like a password: anyone you
  forward it to can decide on your behalf.
- **The operator can still tamper with the database.** Approval Pack is not a
  notary and it does not anchor hashes anywhere external. What it guarantees is
  *detection*: edited content stops matching the recorded hash, and any evidence
  file already downloaded carries the original one. For stronger guarantees you
  would need a third-party timestamp authority or an append-only log.
- **Single-tenant, shared-password owner area.** There are no user accounts,
  roles, or per-user approval ownership.
- **No email delivery.** You copy the link and send it yourself.
- **No approval chains.** One approval, one reviewer, one decision. No multi-step
  routing, no quorum, no delegation.
- **SQLite by default**, which is right for the traffic this tool sees; point
  `APPROVAL_PACK_DATABASE_URL` at PostgreSQL if you need concurrent writers.
- **No rate limiting** on the review endpoint. Guessing a 256-bit token is not a
  realistic attack, but put the service behind a reverse proxy anyway if it is
  publicly reachable.

---

## License

MIT — see [LICENSE](LICENSE).
