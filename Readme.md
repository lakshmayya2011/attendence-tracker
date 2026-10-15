# Employee Attendance & Analytics API

A REST API for managing employees, recording attendance, correcting attendance records with an audit trail, and generating monthly and department-level analytics. It is implemented in **Python, FastAPI, Pydantic, PyMongo, and MongoDB** and follows the supplied `openapi.yaml` contract and data-model notes.

> **Implementation status and security boundary:** This is an assignment/demo service, not a production-ready HR system. Employee creation, attendance operations, analytics, and the `/admin/explain` endpoint currently do **not** implement user authentication or role-based authorization. Anyone who can reach the service can call these routes. The README documents this explicitly rather than implying that controls not present in the code are implemented. Run it locally or behind a properly secured private gateway until authentication and authorization are added.

## Contents

1. [Project goals and capabilities](#1-project-goals-and-capabilities)
2. [Technology stack](#2-technology-stack)
3. [Architecture](#3-architecture)
4. [Repository layout](#4-repository-layout)
5. [Prerequisites](#5-prerequisites)
6. [Run from a clean clone](#6-run-from-a-clean-clone)
7. [Configuration and secrets](#7-configuration-and-secrets)
8. [API reference and examples](#8-api-reference-and-examples)
9. [Data model](#9-data-model)
10. [Business rules](#10-business-rules)
11. [MongoDB indexes and query design](#11-mongodb-indexes-and-query-design)
12. [Security review: implemented controls](#12-security-review-implemented-controls)
13. [Security deviations, rationale, risks, and remediation](#13-security-deviations-rationale-risks-and-remediation)
14. [Testing and verification](#14-testing-and-verification)
15. [Troubleshooting](#15-troubleshooting)
16. [Operational and deployment guidance](#16-operational-and-deployment-guidance)
17. [Known limitations and future enhancements](#17-known-limitations-and-future-enhancements)
18. [Submission checklist](#18-submission-checklist)

---

## 1. Project goals and capabilities

The API provides these core capabilities:

- Create employee records and list employees with optional department filtering and pagination.
- Record employee punch-in and punch-out events.
- Handle overnight shifts and assign early-morning punches to the correct shift date.
- Correct attendance records through a regularization endpoint, recording changed fields and correction metadata in an audit history.
- Search attendance records with employee/date filters and bounded pagination.
- Calculate employee-monthly summaries, department summaries, a late-arrival leaderboard, and daily department trends.
- Use MongoDB aggregation pipelines for analytics instead of loading all attendance documents into Python.
- Explain supported MongoDB query plans using execution statistics.
- Create required indexes automatically when the application starts.

### What this service is not

This project is not a complete workforce-management product. It does not currently include a user login system, manager/HR role management, a frontend application, notifications, payroll integration, a formal retention policy, or a production audit-log export pipeline. Those must not be assumed to exist just because the API supports attendance and analytics.

## 2. Technology stack

| Component | Purpose |
|---|---|
| Python 3.11+ | Runtime and business logic |
| FastAPI | REST routes, HTTP responses, interactive API documentation |
| Pydantic v2 | Request parsing and input validation |
| PyMongo | MongoDB client, atomic operations, indexes, aggregation pipelines |
| MongoDB 6.0+ (MongoDB 7 recommended) | Document storage, uniqueness constraints, queries, analytics |
| python-dotenv | Loads local `.env` settings for development |
| pytest | Automated business-rule tests |
| HTTPX | HTTP test client dependency where used by tests |

The `requirements.txt` file is the dependency source of truth. For reproducible production builds, pin exact tested versions and use a lock file or dependency-management tool rather than relying only on broad version ranges.

## 3. Architecture

```text
Browser / API client / curl
            |
            | HTTP request
            v
       FastAPI app
       app/main.py
            |
            +--> Pydantic request validation
            |
            +--> Business rules
            |      - date/time interpretation
            |      - late/overtime calculation
            |      - attendance correction
            |
            +--> PyMongo
                   |
                   v
             MongoDB database
              |             |
              v             v
          employees    attendance_logs
              |             |
              +------ indexes and unique constraints
                            |
                            +--> aggregation pipelines for analytics
                            +--> explain execution statistics
```

### Request lifecycle

1. A client calls an HTTP route.
2. FastAPI parses the request and Pydantic validates fields and formats.
3. The route applies domain/business rules.
4. PyMongo reads or writes the relevant MongoDB collection.
5. MongoDB indexes enforce key uniqueness and support common query paths.
6. The route serializes the public response, converting stored datetimes to the documented API timestamp representation where applicable.

### Why a single application file?

The assignment specifies `app/main.py` as the application entry point and expects the API to be easy to launch. The implementation therefore keeps the routes and helper logic in that file. For a larger maintained service, separate routers, schemas, services, repositories, security dependencies, and configuration modules would improve testability and code ownership.

## 4. Repository layout

```text
.
├── app/
│   ├── __init__.py
│   └── main.py                 # FastAPI routes, validation models, business logic
├── sample_data/
│   ├── employees.json          # Example employee documents
│   └── attendance_logs.json    # Example attendance documents
├── tests/
│   └── test_business_rules.py  # Automated business-rule tests
├── .env.example                # Safe configuration template; no real secrets
├── .gitignore                  # Excludes local environment/secrets and generated files
├── DATA_MODEL.md               # Collection/document design notes
├── DECISIONS.md                # Selected implementation trade-offs
├── REVIEW.md                   # Starter-code review and observations
├── openapi.yaml                # API contract supplied for the assignment
├── requirements.txt            # Python dependencies
├── sample_seed.py               # Optional sample-data loader (destructive; see warning)
└── README.md                    # This document
```

## 5. Prerequisites

- Python 3.11 or newer.
- Git.
- A MongoDB instance reachable from the computer running the API. MongoDB Atlas is suitable; a local MongoDB installation also works.
- Network access from the API process to MongoDB.

MongoDB Atlas cluster features and free-tier limits may change. Use the current Atlas UI/documentation for account-specific setup.

## 6. Run from a clean clone

The steps below are intended for a reviewer who has cloned the repository and is starting from a clean environment.

### 6.1 Clone the repository — values you must replace

The commands below contain placeholders. **Do not copy them literally without replacing the values in angle brackets.**

| Placeholder | Replace it with | Example only |
|---|---|---|
| `<PUBLIC_REPOSITORY_URL>` | The HTTPS or SSH clone URL of the GitHub repository where you uploaded this project | `https://github.com/YOUR-GITHUB-USERNAME/employee-attendance-api.git` |
| `<REPOSITORY_DIRECTORY>` | The folder Git creates after cloning; usually the repository name | `employee-attendance-api` |

After replacing the placeholders, run commands like these (the URL and folder name below are examples, not your actual repository):

```bash
git clone https://github.com/YOUR-GITHUB-USERNAME/employee-attendance-api.git
cd employee-attendance-api
```

Replace `YOUR-GITHUB-USERNAME` with your GitHub username and use the repository's real clone URL. If the repository is private, make sure your Git credentials have access.

### 6.2 Create and activate a virtual environment

**Windows PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use a permitted execution-policy approach for your own machine, or invoke the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Windows Command Prompt:**

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
```

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 6.3 Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 6.4 Configure MongoDB — exactly what you must replace

The application cannot connect to your database until you configure the database URI. **Do not leave example values or placeholders in the real `.env` file.**

1. In the repository root, copy `.env.example` to a file named exactly `.env`.
   - Windows PowerShell: `Copy-Item .env.example .env`
   - macOS/Linux: `cp .env.example .env`
2. Open `.env` in VS Code.
3. Set the two variables below.

For a local MongoDB installation:

```dotenv
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

For MongoDB Atlas, replace each item in this template:

```dotenv
MONGO_URI="mongodb+srv://<DB_USERNAME>:<URL_ENCODED_DB_PASSWORD>@<CLUSTER_HOST>/?retryWrites=true&w=majority"
MONGO_DB=attendance_db
```

| Placeholder | What to put there | Where to find it |
|---|---|---|
| `<DB_USERNAME>` | The MongoDB **database user** username, not necessarily your Atlas website login | Atlas → Database Access |
| `<URL_ENCODED_DB_PASSWORD>` | That database user's password. URL-encode reserved URI characters such as `@`, `:`, `/`, `?`, `#`, and `%` if present | The password you set when creating the database user; Atlas may not show it again |
| `<CLUSTER_HOST>` | The cluster hostname from the Atlas connection string, for example `cluster0.xxxxx.mongodb.net` | Atlas → Database → Connect → Drivers |

The angle-bracketed strings are instructions, **not valid credentials**. Replace them with your actual values and do not include the `<` or `>` characters. Keep `MONGO_DB=attendance_db` unless you intentionally want to use another database. Make sure the Atlas database user has the required permissions and Atlas Network Access allows connections from the machine running the API.

**Never send your real URI, username/password, or `.env` contents in chat, screenshots, issue trackers, or Git commits.** If a real credential has already been exposed, rotate it.

### 6.5 Start the application

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For local development only, automatic reload can be enabled:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The application creates its indexes at startup. If MongoDB is unreachable or the database user lacks permission to create indexes, startup or subsequent requests may fail; check the terminal output and database permissions.

### 6.6 Verify it is running

- Health endpoint: <http://127.0.0.1:8000/health>
- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

`/health` returns `{"status":"ok"}` when the application can ping MongoDB. If the database ping fails, it returns HTTP `503 Service Unavailable`.

> Bind to `127.0.0.1` for local development. Do not change to `0.0.0.0` on an untrusted network unless you have deliberately configured firewalling, authentication, TLS termination, and access restrictions.

## 7. Configuration and secrets

### Environment variables

| Variable | Required | Meaning | Example |
|---|---:|---|---|
| `MONGO_URI` | Yes for the intended database | MongoDB connection URI | `mongodb://localhost:27017` |
| `MONGO_DB` | No; defaults to `attendance_db` | Database name | `attendance_db` |

The application calls `load_dotenv()` to support a local `.env` file. Environment variables set by the process environment take precedence under the normal `python-dotenv` behavior because `load_dotenv()` does not override already-set values by default.

### Atlas configuration checklist

1. Create a database user specifically for this application. Do not use the Atlas account owner as the application credential.
2. Grant only the minimum database/collection permissions needed for the application's reads, writes, and index creation. If indexes are created at startup, the deployment identity needs the corresponding permission; alternatively, create indexes through a controlled migration and remove index-management permission from the runtime identity.
3. Restrict Atlas Network Access to the API host's known outbound IP or a private networking solution.
4. Use a strong, unique password. URL-encode reserved characters in a username/password embedded in a MongoDB URI.
5. Keep the URI in `.env` locally or in a managed secret store in deployment.
6. Rotate credentials if they were accidentally committed, pasted into a public location, or exposed in a screenshot. Removing the file from the latest commit alone is not enough if the secret remains in Git history.

### Secret-handling rules

- Commit `.env.example`, never the real `.env`.
- Do not hard-code credentials or print the full URI in logs.
- Do not send database passwords in screenshots or support requests.
- Verify `.gitignore` includes `.env`, `.env.*` (while retaining `.env.example` if your ignore pattern would otherwise match it), `.venv/`, `__pycache__/`, and test/cache artifacts.
- Before publishing, run `git status --short` and inspect `git diff --cached` for accidental secrets.

## Before running any example: replace these values

Use this quick checklist whenever you copy a command or JSON example from this README:

| Example value / placeholder | Must you replace it? | Rule |
|---|---|---|
| `<PUBLIC_REPOSITORY_URL>` | **Yes** | Replace with your actual GitHub clone URL. |
| `<REPOSITORY_DIRECTORY>` | **Yes** | Replace with the actual folder name created by `git clone`. |
| `<DB_USERNAME>` | **Yes for Atlas** | Use the MongoDB database user's username. |
| `<URL_ENCODED_DB_PASSWORD>` | **Yes for Atlas** | Use the database user's password, URL-encoding reserved characters. |
| `<CLUSTER_HOST>` | **Yes for Atlas** | Use the hostname from your Atlas connection string. |
| `EMP1001` | **Yes, unless that employee exists** | Replace with an existing employee code in your database. The example is not automatically created. |
| `127.0.0.1:8000` | Usually no for local testing | Change it only if the API uses a different host or port. |
| `attendance_db` | Usually no | Must match the database name configured in `.env`. |
| `2026-01-05` and other sample dates | Replace when testing your own scenario | Dates must use `YYYY-MM-DD`; use dates that make sense for the test. |
| `punched_at` | Omit for a current-time test if optional | If supplied, use an integer Unix epoch timestamp in **milliseconds**. Never use `10` as a timestamp. |

**Important:** A successful employee creation does not guarantee that the employee exists in a different database. Make sure the API and your test requests are using the same `.env` configuration and database.

## 8. API reference and examples

The interactive Swagger documentation at `/docs` is the most direct way to see the request schemas, required fields, status codes, and response shapes exposed by the running application. The checked-in `openapi.yaml` is the supplied contract; keep it aligned with actual behavior if you change the implementation.

**Timestamp convention:** Instants accepted or returned by relevant API fields use integer Unix epoch **milliseconds**. Do not send seconds, a date string, or a floating-point timestamp where epoch milliseconds are expected. Calendar dates use `YYYY-MM-DD`; months use `YYYY-MM`; shift times use 24-hour `HH:MM`.

Examples below use `curl`. On Windows, PowerShell's `curl` may be an alias; use `curl.exe` or Swagger UI if quoting differs.

### 8.1 Health check

```bash
curl -i http://127.0.0.1:8000/health
```

Expected healthy response: HTTP `200` and `{"status":"ok"}`. Database connectivity failure should return `503`.

### 8.2 Create an employee

```bash
curl -i -X POST http://127.0.0.1:8000/employees \
  -H 'Content-Type: application/json' \
  -d '{
    "emp_code": "EMP1001",
    "name": "Asha Rao",
    "email": "asha@example.com",
    "department": "Engineering",
    "shift_start": "09:30",
    "shift_end": "18:30",
    "joined_on": "2026-01-05"
  }'
```

A successful create returns HTTP `201 Created`. An already-used employee code should be rejected with HTTP `409 Conflict`. Invalid request data is rejected by validation, normally with HTTP `422 Unprocessable Entity`.

### 8.3 List employees

```bash
curl -i 'http://127.0.0.1:8000/employees?page=1&page_size=20'
curl -i 'http://127.0.0.1:8000/employees?department=Engineering&page=1&page_size=20'
```

Pages are 1-based. The page size defaults to 20 and is capped at 100.

### 8.4 Punch in

First create the employee using `POST /employees`, or use an employee code that already exists in this database. In the example below, replace `EMP1001` with that employee's real `emp_code`. For the employee created during manual testing in this project, the code was `EMP9001`; use it only if that employee exists in the database you configured.

```bash
curl -i -X POST http://127.0.0.1:8000/attendance/punch-in \
  -H 'Content-Type: application/json' \
  -d '{"emp_code":"EMP1001","status":"PRESENT"}'
```

**Values to replace:**

- `EMP1001` → an existing employee's exact `emp_code` in your configured database.
- `PRESENT` → a status accepted by the request schema. Keep `PRESENT` for this basic example if it is allowed by your API.
- `127.0.0.1:8000` → change this only if you started the API on a different host or port.
- `punched_at` is intentionally omitted, so the endpoint can use its default current-time behavior if the field is optional. Do **not** use `"punched_at": 10`: timestamps must be integer Unix epoch **milliseconds**, not seconds or an arbitrary small number. If you need a fixed timestamp, obtain a real epoch-millisecond value for the intended instant and follow the schema in `/docs`.

Expected success according to the API contract: HTTP `201 Created`. If you receive `422`, inspect the validation message and confirm the JSON field names and types. If the employee is not found, verify that you created it in the same MongoDB database the API is currently using.

A repeated punch-in for an attendance date that already has a record should not create a second record; the unique `(emp_code, date)` index is a final integrity guard.

### 8.5 Punch out

Replace `EMP1001` with the exact `emp_code` used for the punch-in. Punch-out normally must follow a successful punch-in for the relevant attendance date.

```bash
curl -i -X POST http://127.0.0.1:8000/attendance/punch-out \
  -H 'Content-Type: application/json' \
  -d '{"emp_code":"EMP1001"}'
```

**Values to replace:**

- `EMP1001` → the employee code used for the successful punch-in.
- `127.0.0.1:8000` → change only if your API is running elsewhere.
- Do not add a made-up timestamp. If the schema supports `punched_at`, it must be a valid integer epoch timestamp in milliseconds.

If you use `EMP9001` for punch-in, use `EMP9001` here too.

Punch-out requires an applicable attendance record and an unclosed punch-in. If the record is missing or the punch-out is invalid for the current state, the API should return an appropriate client error rather than silently creating a malformed record.

### 8.6 Search attendance

```bash
curl -i 'http://127.0.0.1:8000/attendance?page=1&page_size=20'
curl -i 'http://127.0.0.1:8000/attendance?emp_code=EMP1001&page=1&page_size=20'
curl -i 'http://127.0.0.1:8000/attendance?date_from=2026-07-01&date_to=2026-07-31&page=1&page_size=20'
```

Use valid date bounds and page parameters. Large, unbounded data exports should be implemented as a separate authorized export workflow rather than bypassing pagination.

### 8.7 Regularize an attendance record

The exact editable fields are defined by the request schema in `/docs`. Example:

```bash
curl -i -X PATCH http://127.0.0.1:8000/attendance/EMP1001/2026-07-06 \
  -H 'Content-Type: application/json' \
  -d '{
    "punch_in": 1783310280000,
    "reason": "Corrected after manager review",
    "regularized_by": "manager01"
  }'
```

Only fields accepted by the regularization schema should be changed. Derived fields such as lateness, overtime, and work duration should be recalculated server-side rather than trusted from a client. The implementation appends an audit-history entry for successful corrections and uses a conditional update to reduce the chance of overwriting a concurrent change.

**Important authorization limitation:** `regularized_by` is supplied in the request, not established by an authenticated identity in this version. Therefore, it is an audit *claim*, not proof of who made the change. Before production use, derive the actor from a verified identity and enforce manager/HR permissions on the server.

### 8.8 Employee monthly analytics

```bash
curl -i 'http://127.0.0.1:8000/analytics/employees/EMP1001/monthly?month=2026-07'
```

### 8.9 Department summary

```bash
curl -i 'http://127.0.0.1:8000/analytics/departments/summary?month=2026-07'
curl -i 'http://127.0.0.1:8000/analytics/departments/summary?month=2026-07&department=Engineering'
```

### 8.10 Late-arrival leaderboard

```bash
curl -i 'http://127.0.0.1:8000/analytics/leaderboard/late?month=2026-07&limit=10'
```

The limit is bounded by the route's validation. Analytics output can expose employee attendance patterns and should be protected by authorization in a real deployment.

### 8.11 Department trend

```bash
curl -i 'http://127.0.0.1:8000/analytics/departments/Engineering/trend?from=2026-07-01&to=2026-07-31'
```

The trend response includes daily attendance measures and a rolling seven-day average where applicable. Verify the requested date range and department spelling.

### 8.12 Explain query plans

```bash
curl -i 'http://127.0.0.1:8000/admin/explain/attendance_list?date_from=2026-07-01&date_to=2026-07-31&page=1&page_size=20'
curl -i 'http://127.0.0.1:8000/admin/explain/employee_monthly?emp_code=EMP1001&month=2026-07'
curl -i 'http://127.0.0.1:8000/admin/explain/department_summary?month=2026-07'
curl -i 'http://127.0.0.1:8000/admin/explain/late_leaderboard?month=2026-07&limit=10'
curl -i 'http://127.0.0.1:8000/admin/explain/department_trend?department=Engineering&from=2026-07-01&to=2026-07-31'
```

This route returns MongoDB explain output including `executionStats`. Inspect the winning plan, `nReturned`, `totalKeysExamined`, and `totalDocsExamined`; index use may appear as `IXSCAN`, while a `COLLSCAN` indicates a collection scan. A collection scan is not automatically a defect for every small dataset, but should be investigated for important high-volume queries.

**Security warning:** Despite the `/admin` path name, this endpoint is not protected by authentication or authorization in this version. It can reveal query structure, collection names, and performance characteristics. Do not expose it publicly. In production, require an administrator role, or disable/remove it from the public application.

## 9. Data model

The application uses two primary MongoDB collections.

### 9.1 `employees`

Conceptual fields include:

| Field | Meaning |
|---|---|
| `emp_code` | Stable employee identifier, e.g. `EMP1001`; unique |
| `name` | Employee display name |
| `email` | Employee email address |
| `department` | Department used for filtering and grouping |
| `shift_start` | Local shift start as `HH:MM` |
| `shift_end` | Local shift end as `HH:MM` |
| `joined_on` | Calendar date as `YYYY-MM-DD` |
| `created_at` | Creation instant stored as a BSON date and exposed as epoch milliseconds |

The exact schema and validation bounds are in `EmployeeIn` in `app/main.py` and in the OpenAPI contract.

### 9.2 `attendance_logs`

Conceptual fields include:

| Field | Meaning |
|---|---|
| `emp_code` | Employee identifier |
| `date` | Attendance/shift calendar date, `YYYY-MM-DD` |
| `status` | Attendance status such as `PRESENT`, `WFH`, `ON_DUTY`, `ABSENT`, or `LEAVE` |
| `punch_in` | Punch-in instant, stored as BSON date |
| `punch_out` | Punch-out instant, stored as BSON date when available |
| `late_minutes` | Derived late-arrival minutes |
| `overtime_minutes` | Derived overtime minutes |
| `work_hours` | Derived duration rounded according to the business rules |
| `corrections` | Correction-history entries appended by regularization operations |

Refer to `DATA_MODEL.md` and the live route schemas for the definitive field definitions. MongoDB `_id` values are omitted from the public employee response; public attendance serializers expose only the intended API fields.

### Why keep calendar dates separate from instants?

`date` represents the attendance day, not a point on the UTC timeline. Shift times such as `09:30` are local wall-clock values. Punch-in/out are instants. Mixing these concepts can assign overnight shifts to the wrong day or create timezone bugs. This implementation uses IST (UTC+05:30) to interpret attendance/shift calendar rules and stores instants as UTC-aware BSON datetimes.

## 10. Business rules

The code is the final authority; these are the current intended rules represented in the implementation.

- **Timezone:** Attendance calendar calculations use India Standard Time (IST, UTC+05:30). Instants are converted to UTC for storage.
- **API timestamps:** Epoch milliseconds are used at the API boundary for instants. Timestamp precision is truncated to whole seconds before calculations.
- **Shift dates:** A punch during the early-morning portion of an overnight shift, before the configured shift end, is associated with the previous shift date.
- **Late arrival:** Late minutes are floored from the shift start; the employee is considered late only when arrival is strictly more than 10 minutes after shift start.
- **Overtime:** Overtime is counted only when the floored excess over shift end reaches at least 30 minutes.
- **Work duration:** Work hours are rounded to two decimal places using half-up rounding. `half_day` is true when the rounded duration is below `4.50` hours.
- **Present statuses:** `PRESENT`, `WFH`, and `ON_DUTY` count as present; `ABSENT` and `LEAVE` do not.
- **Monthly attendance:** Present-day totals count weekdays only. Late and overtime totals include weekend attendance records.
- **Department headcount:** Employees who joined on or before the relevant period end are included, even if they have no attendance record in that period.
- **Pagination:** Page numbers start at 1; the default page size is 20; the maximum page size is 100.
- **Uniqueness:** An employee code is unique, and there can be at most one attendance record per employee and attendance date.
- **Correction:** Editable source fields are accepted; derived metrics are recalculated by the server. A successful correction records changed fields and correction metadata.

## 11. MongoDB indexes and query design

Indexes are created idempotently at startup by `ensure_indexes()`.

| Collection | Index purpose | Why it exists |
|---|---|---|
| `employees(emp_code)` unique | Employee identity | Prevent duplicate employee codes and speed up direct lookup |
| `employees(department, joined_on, emp_code)` | Department and period/headcount access | Supports department-filtered and date-aware queries |
| `employees(joined_on)` | Join-date filtering | Supports employee eligibility/headcount calculations |
| `employees(department, emp_code)` | Department listing | Supports filtered listing/sorting paths |
| `attendance_logs(emp_code, date)` unique | Attendance identity | Enforces one record per employee per attendance date |
| `attendance_logs(date DESC, emp_code ASC)` | Attendance date listing | Supports date-oriented listing and ordering |
| `attendance_logs(emp_code, date DESC)` | Employee history | Supports retrieving an employee's recent attendance |
| `attendance_logs(emp_code, punch_in DESC)` | Employee/punch lookup | Supports punch-related lookup paths |
| `attendance_logs(status, date, emp_code)` | Status/date filters | Supports attendance status/date analysis |

### Why both application checks and unique indexes?

A pre-check alone is vulnerable to races: two requests may both observe that a record is absent and then both try to insert it. A unique index is enforced by MongoDB and remains effective across concurrent requests. Application-level checks can return a friendlier error, while the database constraint is the final integrity barrier.

### Aggregation pipelines

Monthly summaries, department summaries, leaderboards, and department trends are computed in MongoDB using aggregation pipelines. This reduces the need to transfer every raw attendance document to the application process and lets the database use indexes and server-side operators. Performance still needs to be measured with representative data; an index is not proof that every pipeline is optimal.

## 12. Security review: implemented controls

This section distinguishes **controls present in the code** from controls that are only recommended for a real deployment.

### 12.1 Input validation

**Implemented:** FastAPI/Pydantic models validate request-body shape and selected field formats/ranges. Examples include employee-code format, email format, `HH:MM` shift times, ISO calendar dates, and constrained pagination/leaderboard limits. Invalid request payloads normally receive HTTP `422`.

**Why it matters:** Rejects malformed input early and reduces inconsistent stored data. Validation is not a replacement for authorization, business-rule checks, safe database query construction, or output handling.

### 12.2 Database uniqueness and race resistance

**Implemented:** Unique MongoDB indexes protect employee codes and the `(emp_code, date)` attendance key. Punch and correction operations use database-side conditions/updates where applicable to avoid some check-then-write races and accidental overwrites.

**Why it matters:** Data integrity must be enforced by the database as well as by application logic. Concurrent requests are normal in an API.

### 12.3 Bounded pagination and query parameters

**Implemented:** Listing endpoints use pagination and cap page size at 100; leaderboard limits are also constrained.

**Why it matters:** Prevents clients from requesting an arbitrarily large page through these parameters. It is only a partial resource-consumption defense: request-rate limits, query timeouts, response-size limits, and monitoring are not substitutes for one another.

### 12.4 Controlled public serialization

**Implemented:** Public serializers shape employee/attendance responses and avoid returning internal MongoDB `_id` values in normal public employee output. Derived attendance metrics are recalculated by server logic rather than accepted as trusted client values during regularization.

**Why it matters:** Avoids unintentionally exposing database implementation fields and prevents clients from directly setting calculated values that should be authoritative on the server.

### 12.5 Audit trail for corrections

**Implemented:** Successful regularization appends correction metadata/history describing the correction and changed fields. The update uses a conditional/optimistic-concurrency approach to reduce the chance of silently overwriting a concurrent update.

**Limitations:** The audit history is stored in the same operational database and is not a tamper-proof external audit system. The `regularized_by` value is client-supplied in this version, so it is not a trustworthy identity assertion. There is no demonstrated role check that restricts corrections to managers or HR users.

### 12.6 Database outage handling

**Implemented:** `/health` pings MongoDB and returns `503` when a PyMongo database error prevents the health check from succeeding. The explain handler also translates explain failures to a service error rather than returning a raw traceback.

**Why it matters:** Callers and health probes can distinguish a service whose database dependency is unavailable from a healthy service. More complete production error handling, structured logs, and alerting remain future work.

### 12.7 Secrets configuration

**Implemented as a configuration pattern:** MongoDB credentials are read from environment variables and can be supplied through a local `.env` file; `.env.example` is intended to contain placeholders only.

**Required repository practice:** Keep real `.env` files out of Git, restrict database credentials, rotate exposed credentials, and check the Git history before publishing. Configuration support does not itself guarantee that a developer has configured secrets safely.

### 12.8 Query planning visibility

**Implemented:** The explain endpoint exposes MongoDB `executionStats` for supported query/pipeline paths.

**Security caveat:** Explain output is diagnostic information and may disclose query structure and collection names. The route is currently unauthenticated and should be private or disabled until an admin authorization layer exists.

## 13. Security deviations, rationale, risks, and remediation

Some production security controls are not implemented in this assignment. This is documented as a limitation, not described as a security feature. These choices make local evaluation simpler but are not acceptable defaults for an internet-facing HR system.

| Deviation / missing control | Why it may be absent in this assignment | Risk | Recommended remediation before production |
|---|---|---|---|
| No authentication | The supplied assignment API contract focuses on attendance/business behavior and does not define a login or identity-provider flow. | Any reachable caller may create employees, alter attendance, or read employee/attendance data. | Add an established identity provider or OAuth 2.0/OIDC integration; validate signed access tokens, issuer, audience, expiry, and scopes. Avoid inventing a custom password system unless there is a strong reason. |
| No role-based authorization | The assignment does not provide roles or ownership rules. | Employees, managers, HR staff, and administrators are not separated by permissions. | Enforce deny-by-default authorization for every route and action. Define roles such as employee, manager, HR, and admin; check department/employee scope on every read and write. |
| `/admin/explain` is not actually admin-protected | Route exists to satisfy the diagnostic contract and support performance review. | Public callers may inspect database query plans and operational details; the endpoint can also consume database resources. | Restrict to admin-only access on a private network, or disable/remove it from public builds. Add rate limits and audit access. |
| `regularized_by` is client-supplied | No authenticated principal is implemented to populate the actor identity. | A caller may impersonate a manager in the audit entry. | Derive actor ID from the validated access token/session; ignore any client-supplied actor field. Store actor, timestamp, reason, before/after values, request ID, and authorization context. |
| No application-level rate limiting | The starter contract is a simple API and has no rate-limit service configured. | Automated abuse, scraping, repeated expensive analytics, and resource exhaustion. | Add gateway or application rate limits by authenticated identity and IP; set concurrency, body-size, timeout, and per-route quotas. Use a shared store if horizontally scaled. |
| No application TLS configuration | Local development uses `http://127.0.0.1:8000`; TLS is typically terminated by a reverse proxy in deployment. | Traffic may be exposed if sent over an untrusted network without TLS. | Terminate HTTPS at a trusted proxy/load balancer, enforce modern TLS, redirect HTTP to HTTPS, and configure trusted proxy headers correctly. Keep MongoDB Atlas TLS enabled. |
| Atlas allowlist may be broad during setup | A developer may temporarily use `0.0.0.0/0` when a home ISP changes the public IP and the app cannot connect otherwise. | Any internet host can attempt to connect to the cluster; authentication still applies but the exposed attack surface is much larger. | Remove `0.0.0.0/0`; use a specific outbound IP, VPN/private endpoint, or controlled egress gateway. If the broad rule was used, replace it as soon as testing ends and rotate credentials if exposure is suspected. |
| No formal CORS policy configured | The API is exercised through Swagger/curl in a local assignment; no browser frontend origin has been specified. | If a browser client is added, permissive or accidental cross-origin behavior may create unwanted access patterns; CORS is not an authentication mechanism. | Add `CORSMiddleware` only for the exact frontend origins and methods/headers required. Do not use wildcard origins with credentialed requests. Remember that CORS does not protect the API from curl or other non-browser clients. |
| No CSRF design | No cookie-based browser authentication is implemented. | If cookie authentication is introduced without CSRF protection, state-changing routes may be vulnerable to cross-site request forgery. | If using cookies, use `Secure`, `HttpOnly`, and appropriate `SameSite` attributes plus CSRF tokens/origin checks for unsafe methods. If using bearer tokens, design token storage and XSS protections carefully. |
| No explicit request-body size limit | The implementation relies on normal framework/server behavior. | Very large payloads can consume memory and CPU. | Set body-size limits at proxy and application layers; reject unsupported content types and oversized requests. |
| No centralized structured security logging/alerting | Basic assignment behavior is prioritized; a production observability pipeline is not included. | Abuse, privilege misuse, and repeated failures may go undetected; debugging may be difficult. | Emit structured logs with request/correlation IDs and actor IDs; redact credentials and sensitive data. Alert on repeated auth failures, forbidden operations, unusual export volume, and database errors. |
| Correction history is not tamper-proof | Audit entries are stored in the same MongoDB collection/document as the record. | A sufficiently privileged database user could modify or remove both the record and its history. | Use restricted database roles, append-only audit storage, immutable/retention-locked external logging where required, and independent audit monitoring. |
| No retention/deletion policy | The assignment does not specify HR data retention rules. | Personal data may be retained longer than necessary or deleted without meeting legal/business requirements. | Define retention, legal holds, access logging, deletion/rectification processes, and backups consistent with applicable law and company policy. |
| No field-level privacy policy | The assignment uses employee names, emails, department, and attendance records. | Attendance and employment data are sensitive operational/personal information. | Minimize fields collected, restrict analytics by role and department, mask data in logs, document purpose, and review privacy/legal requirements for the deployment jurisdiction. |
| No dependency scanning/CI security gate | No CI pipeline is included in the starter deliverable. | Vulnerable dependencies or accidental secret commits may go unnoticed. | Add automated tests, dependency vulnerability scanning, static analysis, secret scanning, and a protected branch/review process. |
| No deployment hardening/container policy | The deliverable is intended to run directly through Uvicorn for evaluation. | A public deployment may expose debug/reload behavior, use excessive privileges, or have weak network boundaries. | Disable reload in production, run as a non-root user, patch OS/Python dependencies, use a hardened container, restrict egress, and manage configuration through secrets. |

### Why these are not “security rules we can safely ignore”

The API is intentionally easy to start for assignment review. That is a usability/evaluation trade-off, **not** a justification to deploy it without access control. Employee attendance data can reveal work patterns and other personal information. If the service is accessible to anyone besides the developer/evaluator, first add authentication, authorization, network restriction, HTTPS, and monitoring.

### Security threat model: what to test

Before production, add tests for at least:

- Unauthenticated calls are rejected when authentication is enabled.
- An ordinary employee cannot regularize another employee's record.
- A manager cannot access departments outside their assigned scope.
- A non-admin cannot call `/admin/explain`.
- A caller cannot spoof `regularized_by` or other actor metadata.
- Duplicate create/punch operations remain safe under concurrent requests.
- Invalid dates, malformed timestamps, oversized bodies, and extreme pagination values are rejected.
- Error responses do not leak connection strings, credentials, stack traces, or raw internal exceptions.
- Logs do not contain passwords, MongoDB URIs, tokens, or unnecessary personal data.
- Analytics access is restricted according to the caller's role and data scope.

## 14. Testing and verification

### Run automated tests

From the repository root with the virtual environment activated:

```bash
python -m pytest -q
```

To see individual test names and output:

```bash
python -m pytest -v
```

The current test module focuses on business-rule behavior. Do not interpret a passing unit/business-rule suite as proof that MongoDB integration, every route, authorization, load, or deployment security has been tested.

### Manual smoke-test checklist

Use `/docs` or `curl` and record the actual status code/body for each test:

- [ ] `GET /health` succeeds when MongoDB is reachable.
- [ ] `GET /health` returns `503` when the database dependency is unavailable.
- [ ] Valid `POST /employees` returns `201`.
- [ ] Duplicate `emp_code` is rejected with `409`.
- [ ] `GET /employees` returns the created employee.
- [ ] Invalid employee input returns a validation error (`422`).
- [ ] Valid punch-in creates an attendance record.
- [ ] Duplicate punch-in cannot create a second `(emp_code, date)` record.
- [ ] Punch-out updates the expected record and calculates derived values.
- [ ] Punch-out without a valid open punch-in is rejected.
- [ ] Attendance filters and pagination return expected records.
- [ ] Regularization changes only allowed fields and appends a correction-history entry.
- [ ] Regularization recalculates derived fields rather than trusting client values.
- [ ] Monthly and department analytics are checked against a small known dataset.
- [ ] Department trend returns expected calendar dates, including gap/working-day rules defined by the contract.
- [ ] Explain endpoints return execution statistics for supported query names.

### Important testing caveats

- Results depend on the exact MongoDB dataset. A test using one employee does not prove analytics are correct for multiple departments, employees with no attendance, weekends, overnight shifts, or boundary timestamps.
- Integration tests should use a dedicated disposable test database. Do not run destructive seed scripts against a database containing real or evaluator data.
- Include boundary tests around 10-minute lateness, 30-minute overtime, half-day rounding, month boundaries, year boundaries, and overnight shifts.
- Add concurrent tests for duplicate employee creation, simultaneous punch-ins, and concurrent regularization.

### Sample seed script warning

`sample_seed.py` deletes all documents in the configured `employees` and `attendance_logs` collections before inserting sample data. Run it **only** against a disposable database that you can lose. Do not run it against a shared Atlas database, evaluator database, or any database with data you need to preserve.

## 15. Troubleshooting

### `ServerSelectionTimeoutError` or health returns `503`

1. Confirm the MongoDB service/Atlas cluster is running.
2. Confirm `MONGO_URI` is correct and contains no accidental spaces or placeholders.
3. Confirm `.env` is named exactly `.env`, not `.env.txt` or `.env.env`.
4. Confirm the application is being started from the repository root so `load_dotenv()` can find the file.
5. In Atlas, confirm the database user exists and has the necessary privileges.
6. Confirm Atlas Network Access permits the API machine's current outbound IP. Prefer a specific IP/private connection over `0.0.0.0/0`.
7. URL-encode reserved characters in the username/password portion of the URI.
8. Restart Uvicorn after configuration changes.

A safe connectivity check (does not print the URI) is:

```bash
python -c "from dotenv import load_dotenv; import os; from pymongo import MongoClient; load_dotenv(); c=MongoClient(os.getenv('MONGO_URI'), serverSelectionTimeoutMS=5000); print(c.admin.command('ping')); c.close()"
```

Never add `print(os.getenv('MONGO_URI'))` to troubleshooting logs.

### `ModuleNotFoundError`

Activate the intended virtual environment, then run:

```bash
python -m pip install -r requirements.txt
```

Use `python -m uvicorn ...` to ensure Uvicorn is launched from the same Python environment.

### `Address already in use`

Another process is using port 8000. Stop that process or choose another port, then use the same port in the browser URL.

### `409 Conflict` while creating an employee

The employee code already exists. Use a new test code, or inspect the existing record. Do not delete records blindly just to make a test pass.

### An index creation error at startup

Check the database user's index privileges and existing data. A unique index cannot be created if duplicate values already exist. Investigate and resolve duplicates deliberately rather than dropping constraints without understanding the impact.

### Analytics output seems empty or surprising

Check that the selected month/date range contains records, that dates are in the expected `YYYY-MM-DD` format, that the department name matches exactly, and that the employee's `joined_on` date is within the relevant period. Compare the output with a small hand-calculated dataset.

## 16. Operational and deployment guidance

For a real deployment, place the application behind a maintained HTTPS reverse proxy or managed API gateway. Keep the database on a private/restricted network and never expose MongoDB directly to the public internet.

Recommended production baseline:

1. Add authentication and route-level authorization before exposing the service.
2. Protect or remove `/admin/explain`.
3. Restrict database network access and use a least-privilege database identity.
4. Terminate HTTPS and configure trusted proxy behavior correctly.
5. Disable development reload and avoid debug mode in production.
6. Configure request size limits, timeouts, rate limits, concurrency limits, and database connection settings.
7. Add structured logs, metrics, health/readiness probes, alerting, and secret redaction.
8. Back up the database, test restore procedures, and document retention/deletion policy.
9. Pin and scan dependencies; run unit, integration, and security tests in CI.
10. Separate development, test, staging, and production databases/credentials.
11. Use migration/versioning procedures for indexes and schema changes in environments where automatic runtime index creation is not appropriate.
12. Document incident response and rotate secrets immediately after suspected exposure.

### Health and readiness

The current `/health` endpoint checks MongoDB connectivity. In larger deployments, separate liveness (process is alive) from readiness (dependencies are usable) so a database outage does not necessarily cause an orchestrator to repeatedly restart a healthy application process. Do not expose detailed internal dependency errors to untrusted clients.

## 17. Known limitations and future enhancements

Prioritize these in order:

### Priority 0 — required before exposure beyond local evaluation

- Authentication using a standard identity provider/OIDC flow.
- Role-based and resource-level authorization for employees, managers, HR, and admins.
- Protect or disable `/admin/explain`.
- Restrict MongoDB Atlas network access; remove broad temporary allowlist rules.
- HTTPS, secret management, and safe production configuration.

### Priority 1 — correctness and auditability

- Add integration tests using an isolated MongoDB test database.
- Add concurrency tests for duplicate creation, punch-in/out, and regularization.
- Derive audit actor identity from authentication and strengthen audit immutability.
- Add request IDs and structured, redacted logs.
- Define data retention, correction approval, and privacy/access policies.
- Add contract tests to compare actual routes/responses with `openapi.yaml`.

### Priority 2 — reliability and performance

- Add rate limits, request-size limits, timeouts, and graceful shutdown behavior.
- Add performance tests with realistic dataset sizes and track query-plan regressions.
- Review indexes with real query patterns and remove redundant indexes only after measurement.
- Add metrics and alerts for latency, error rates, database connectivity, and slow queries.
- Use managed migrations for index/schema changes where required.

### Priority 3 — product capabilities

- Employee self-service and manager/HR dashboards with scoped permissions.
- Attendance correction approval workflow and notifications.
- CSV/report export with authorization, audit trail, and limits.
- Holiday calendar, configurable work weeks, leave management, and organization-specific shift policies.
- Localization/timezone configuration if the service expands beyond IST.
- Backup/restore runbooks, disaster recovery, and data-retention automation.

## 18. Submission checklist

Before sharing the repository with a reviewer:

- [ ] The repository contains `app/main.py`, `requirements.txt`, `openapi.yaml`, and the documentation files.
- [ ] `.env.example` contains placeholders only.
- [ ] `.env`, credentials, database URIs, and tokens are not tracked by Git.
- [ ] `.gitignore` excludes local virtual environments, `.env`, Python cache files, and test caches.
- [ ] The reviewer can install dependencies from a clean clone.
- [ ] The reviewer can configure their own MongoDB URI and start the application using the documented command.
- [ ] `/health` and `/docs` work after startup.
- [ ] `python -m pytest -q` has been run and its actual result recorded honestly.
- [ ] Manual endpoint tests have been completed and failures documented rather than hidden.
- [ ] The sample seeder's destructive behavior is clearly understood; it is not run against important data.
- [ ] Security limitations are disclosed: especially no authentication/authorization and the unprotected explain route.
- [ ] The README does not claim security controls, tests, or deployment hardening that have not actually been implemented and verified.

---

## Design and security references

These references provide general guidance for the recommended production hardening work; they do not imply that every referenced control is implemented in this repository.

- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Pydantic documentation](https://docs.pydantic.dev/)
- [MongoDB security checklist](https://www.mongodb.com/docs/manual/administration/security-checklist/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

