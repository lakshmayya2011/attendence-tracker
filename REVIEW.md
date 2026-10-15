# Starter Code Review

This review compares the original supplied `app/main.py` with the corrected implementation. The examples below describe concrete failure modes rather than style preferences.

| # | Where | Defect and symptom | Correction |
|---:|---|---|---|
| 1 | `health()` | Always returned `200`, even if MongoDB was unreachable. A readiness poll could treat a broken service as ready. | Execute MongoDB `ping`; return `503` on database errors. |
| 2 | `create_employee()` | Check-then-insert was racy: two concurrent requests could both pass `find_one`. | Unique index on `emp_code`; catch `DuplicateKeyError` and return `409`. |
| 3 | `create_employee()` | `created_at=datetime.now()` was timezone-naive. | Store an explicit UTC datetime and expose it as epoch milliseconds. |
| 4 | `EmployeeIn` | Missing contract validation for employee code, email shape/length, field lengths, date format, shift format, and equal start/end times. | Add Pydantic constraints and calendar validation. |
| 5 | `list_employees()` | `skip = page * page_size` skipped page 1's first page; page 1 should skip zero records. | Use `(page - 1) * page_size`; constrain page and page size. |
| 6 | `list_employees()` | `total` counted the entire collection instead of the filtered department set. | Count using the same filter as the result query. |
| 7 | `list_employees()` | Results had no required `emp_code` ascending sort. | Sort in MongoDB by `emp_code` ascending. |
| 8 | `compute_late_minutes()` | Naively replacing the timestamp's hour/minute ignored IST, overnight shift dates, and timezone-aware instants. | Derive the correct attendance date and compare UTC instants for the IST shift start. |
| 9 | `compute_late_minutes()` | Grace logic depended on a simple integer calculation and did not enforce truncation to whole seconds before calculations. | Truncate first; late only when elapsed time is strictly greater than 600 seconds; floor elapsed minutes from shift start. |
| 10 | `compute_work_hours()` | Python `round()` uses ties-to-even and binary floats, not decimal half-up rounding. | Use `Decimal` and `ROUND_HALF_UP` at two decimal places. |
| 11 | `compute_overtime()` | Always built shift end on `date_str` and therefore handled overnight shifts incorrectly; naive/aware datetime combinations could also fail. | Calculate shift end on the next day for overnight shifts and compare aware UTC instants. |
| 12 | `punch_in()` | Did not return `404` for an unknown employee before reading `emp["shift_start"]`, which could produce a `500`. | Explicitly check employee existence. |
| 13 | `punch_in()` | `datetime.fromtimestamp()` / `datetime.now()` used the machine's local timezone; milliseconds were not normalized to whole seconds. | Validate epoch milliseconds, convert to UTC, truncate to seconds, and calculate the IST attendance date. |
| 14 | `punch_in()` | Duplicate detection used check-then-insert, so simultaneous requests could create duplicate records. | Enforce a unique compound index on `(emp_code, date)` and map duplicate-key errors to `409`. |
| 15 | `punch_in()` | Accepted arbitrary statuses and did not enforce the presence-status allowlist. | Accept only `PRESENT`, `WFH`, or `ON_DUTY`. |
| 16 | `list_attendance()` | Loaded all matching documents into Python, sorted them in memory, and paginated afterward; this does not scale to 100,000 records. | Use indexed MongoDB filters, sort, skip, limit, and `count_documents`. |
| 17 | `list_attendance()` | Did not validate date format/order, pagination bounds, or status values. | Validate filters and return `422` for invalid inputs. |
| 18 | API serialization | Starter endpoints exposed inconsistent fields and MongoDB `ObjectId` handling; the contract says `_id` is internal and instants are epoch milliseconds. | Centralize response serialization and emit only contract fields. |
| 19 | All data operations | No required indexes were created at startup, so uniqueness and query-performance requirements were unmet. | Create idempotent unique and query indexes on startup. |
| 20 | Missing endpoints | Punch-out, regularization, all analytics, and explain were absent. | Implement all paths in `openapi.yaml`, including MongoDB aggregation pipelines and execution-stats explain output. |

## Reviewed and intentionally retained

- Keeping the application in `app/main.py` is intentional: the assignment explicitly requires it.
- Using MongoDB BSON dates for instants and strings for calendar dates is correct per `DATA_MODEL.md`.
- A `history` array is appropriate for this assignment's audit trail, provided each correction appends atomically and concurrent updates are guarded.
- The sample data is intentionally small and does not cover every hidden edge case; it is not itself a defect.
- The supplied sample seeding script is destructive (`delete_many({})`). It is retained as a development utility but prominently documented as unsafe for any database whose data must be preserved.

## Verification still required before submission

Run integration tests against MongoDB 6.0+ (preferably 7.0), including simultaneous punch-in/punch-out/regularization requests and explain plans on a representative 100,000-record dataset. A code review alone does not prove these conditions pass.
