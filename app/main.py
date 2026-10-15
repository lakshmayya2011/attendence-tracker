"""Employee Attendance & Analytics API.

Run from the repository root: uvicorn app.main:app --port 8000
Configuration: MONGO_URI and MONGO_DB (environment variables override .env).
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from bson import json_util

load_dotenv()
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
MIN_EPOCH_MS = 100_000_000_000
MAX_EPOCH_MS = 4_102_444_800_000
PRESENT_STATUSES = ["PRESENT", "WFH", "ON_DUTY"]
ALL_STATUSES = PRESENT_STATUSES + ["ABSENT", "LEAVE"]

client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017"),
    tz_aware=True,
    serverSelectionTimeoutMS=3000,
    connectTimeoutMS=3000,
)
db = client[os.getenv("MONGO_DB", "attendance_db")]
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


def ensure_indexes() -> None:
    """Create idempotent indexes required for integrity and query paths."""
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING), ("emp_code", ASCENDING)], name="ix_employee_department_joined")
    db.employees.create_index([("joined_on", ASCENDING)], name="ix_employee_joined")
    db.employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="ix_employee_department_code")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_employee")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", DESCENDING)], name="ix_attendance_employee_date_desc")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("punch_in", DESCENDING)], name="ix_attendance_employee_punch_in")
    db.attendance_logs.create_index([("status", ASCENDING), ("date", ASCENDING), ("emp_code", ASCENDING)], name="ix_attendance_status_date_employee")


@app.on_event("startup")
def startup() -> None:
    ensure_indexes()


# ------------------------------- validation --------------------------------
def parse_date(value: str, field: str = "date") -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise HTTPException(422, f"{field} must be a valid YYYY-MM-DD date")


def parse_month(value: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value or ""):
        raise HTTPException(422, "month must use YYYY-MM format")
    year, month = map(int, value.split("-"))
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    return start, end


def validate_page(page: int, page_size: int) -> None:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(422, "page must be >= 1 and page_size must be between 1 and 100")


def parse_hhmm(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise HTTPException(422, "shift times must use HH:MM")
    return tuple(map(int, value.split(":")))


def parse_epoch_ms(value: Any, field: str = "punched_at") -> datetime:
    if type(value) is not int or not MIN_EPOCH_MS <= value <= MAX_EPOCH_MS:
        raise HTTPException(422, f"{field} must be an integer epoch-millisecond timestamp in the supported range")
    return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0)


def instant_to_ms(value: Optional[datetime]) -> Optional[int]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)  # PyMongo naive datetimes represent UTC.
    return int(value.timestamp() * 1000)


def truncate_seconds(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def work_hours(punch_in: Optional[datetime], punch_out: Optional[datetime]) -> Optional[float]:
    if punch_in is None or punch_out is None:
        return None
    seconds = Decimal(str((punch_out - punch_in).total_seconds()))
    return float((seconds / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def shift_start_instant(attendance_date: date, shift_start: str) -> datetime:
    h, m = parse_hhmm(shift_start)
    return datetime.combine(attendance_date, time(h, m), IST).astimezone(UTC)


def shift_end_instant(attendance_date: date, shift_start: str, shift_end: str) -> datetime:
    sh, sm = parse_hhmm(shift_start)
    eh, em = parse_hhmm(shift_end)
    end_day = attendance_date + timedelta(days=1) if (eh, em) <= (sh, sm) else attendance_date
    return datetime.combine(end_day, time(eh, em), IST).astimezone(UTC)


def attendance_date_for(punch_in: datetime, shift_start: str, shift_end: str) -> date:
    local = punch_in.astimezone(IST)
    sh, sm = parse_hhmm(shift_start)
    eh, em = parse_hhmm(shift_end)
    if (eh, em) <= (sh, sm) and (local.hour, local.minute) < (eh, em):
        return local.date() - timedelta(days=1)
    return local.date()


def compute_late_minutes(punch_in: datetime, shift_start: str, attendance_date: Optional[date] = None) -> int:
    local = punch_in.astimezone(IST)
    if attendance_date is None:
        attendance_date = local.date()
    start = shift_start_instant(attendance_date, shift_start)
    elapsed = (punch_in - start).total_seconds()
    return int(elapsed // 60) if elapsed > 600 else 0


def compute_overtime(punch_out: datetime, shift_start: str, shift_end: str, attendance_date: date) -> int:
    end = shift_end_instant(attendance_date, shift_start, shift_end)
    elapsed = int((punch_out - end).total_seconds() // 60)
    return elapsed if elapsed >= 30 else 0


def public_employee(doc: dict) -> dict:
    return {"emp_code": doc["emp_code"], "name": doc["name"], "email": doc["email"], "department": doc["department"],
            "shift_start": doc["shift_start"], "shift_end": doc["shift_end"], "joined_on": doc["joined_on"], "created_at": instant_to_ms(doc["created_at"])}


def public_attendance(doc: dict) -> dict:
    return {"emp_code": doc["emp_code"], "date": doc["date"], "status": doc["status"],
            "punch_in": instant_to_ms(doc.get("punch_in")), "punch_out": instant_to_ms(doc.get("punch_out")),
            "work_hours": doc.get("work_hours"), "late_minutes": int(doc.get("late_minutes", 0) or 0),
            "overtime_minutes": int(doc.get("overtime_minutes", 0) or 0), "half_day": bool(doc.get("half_day", False)),
            "history": [{"at": instant_to_ms(h.get("at")), "by": h.get("by", ""), "reason": h.get("reason", ""),
                         "changes": {k: {"from": instant_to_ms(v.get("from")) if k in ("punch_in", "punch_out") else v.get("from"),
                                         "to": instant_to_ms(v.get("to")) if k in ("punch_in", "punch_out") else v.get("to")} for k, v in h.get("changes", {}).items()}}
                        for h in doc.get("history", [])]}


def attendance_recalculated(status: str, pin: Optional[datetime], pout: Optional[datetime], employee: dict, d: date) -> dict:
    if status in ("ABSENT", "LEAVE"):
        return {"status": status, "punch_in": None, "punch_out": None, "work_hours": None, "late_minutes": 0, "overtime_minutes": 0, "half_day": False}
    if pin is None:
        raise HTTPException(422, "presence statuses require punch_in")
    pin = truncate_seconds(pin)
    if pout is not None:
        pout = truncate_seconds(pout)
        elapsed = (pout - pin).total_seconds()
        if elapsed <= 0 or elapsed > 24 * 3600:
            raise HTTPException(422, "punch_out must be after punch_in and no more than 24 hours later")
    hours = work_hours(pin, pout)
    return {"status": status, "punch_in": pin, "punch_out": pout, "work_hours": hours,
            "late_minutes": compute_late_minutes(pin, employee["shift_start"], d),
            "overtime_minutes": compute_overtime(pout, employee["shift_start"], employee["shift_end"], d) if pout else 0,
            "half_day": bool(hours is not None and hours < 4.50)}


# --------------------------------- models -----------------------------------
class EmployeeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field(default="18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: str

    @field_validator("joined_on")
    @classmethod
    def valid_joined_on(cls, v: str) -> str:
        try:
            if date.fromisoformat(v).isoformat() != v: raise ValueError
        except ValueError: raise ValueError("joined_on must be YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def different_shift_times(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start must differ from shift_end")
        return self


class PunchInIn(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @model_validator(mode="before")
    @classmethod
    def null_timestamp_is_not_omission(cls, data):
        if isinstance(data, dict) and "punched_at" in data and data["punched_at"] is None:
            raise ValueError("omit punched_at to use the current time; null is not valid")
        return data

    @field_validator("punched_at")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None and not MIN_EPOCH_MS <= v <= MAX_EPOCH_MS: raise ValueError("punched_at must be epoch milliseconds")
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v):
        if v not in PRESENT_STATUSES: raise ValueError("status must be PRESENT, WFH or ON_DUTY")
        return v


class PunchOutIn(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    emp_code: str
    punched_at: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def null_timestamp_is_not_omission(cls, data):
        if isinstance(data, dict) and "punched_at" in data and data["punched_at"] is None:
            raise ValueError("omit punched_at to use the current time; null is not valid")
        return data

    @field_validator("punched_at")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None and not MIN_EPOCH_MS <= v <= MAX_EPOCH_MS: raise ValueError("punched_at must be epoch milliseconds")
        return v


class RegularizeIn(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @model_validator(mode="before")
    @classmethod
    def null_times_are_not_omission(cls, data):
        if isinstance(data, dict) and any(k in data and data[k] is None for k in ("punch_in", "punch_out")):
            raise ValueError("omit punch timestamps to leave them unchanged; null is not valid")
        return data

    @field_validator("status")
    @classmethod
    def valid_status(cls, v):
        if v is not None and v not in ALL_STATUSES: raise ValueError("invalid status")
        return v

    @field_validator("punch_in", "punch_out")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None and not MIN_EPOCH_MS <= v <= MAX_EPOCH_MS: raise ValueError("timestamp must be epoch milliseconds")
        return v


# -------------------------------- endpoints ---------------------------------
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(503, "database unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC).replace(microsecond=0)
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    return public_employee(doc)


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    q = {"department": department} if department is not None else {}
    total = db.employees.count_documents(q)
    items = [public_employee(d) for d in db.employees.find(q, {"_id": 0}).sort("emp_code", ASCENDING).skip((page - 1) * page_size).limit(page_size)]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    ts = truncate_seconds(parse_epoch_ms(body.punched_at) if body.punched_at is not None else datetime.now(UTC))
    local_date = attendance_date_for(ts, emp["shift_start"], emp["shift_end"])
    fields = attendance_recalculated(body.status, ts, None, emp, local_date)
    doc = {"emp_code": body.emp_code, "date": local_date.isoformat(), **fields, "history": []}
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this attendance date")
    return public_attendance(doc)


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp: raise HTTPException(404, "employee not found")
    ts = truncate_seconds(parse_epoch_ms(body.punched_at) if body.punched_at is not None else datetime.now(UTC))
    rec = db.attendance_logs.find_one({"emp_code": body.emp_code, "punch_in": {"$ne": None, "$lte": ts}}, sort=[("punch_in", DESCENDING)])
    if not rec: raise HTTPException(404, "no punch-in found")
    if rec.get("punch_out") is not None: raise HTTPException(409, "record already punched out")
    pin = rec["punch_in"]
    elapsed = (ts - pin).total_seconds()
    if elapsed <= 0 or elapsed > 24 * 3600: raise HTTPException(422, "punched_at must be after punch_in and within 24 hours")
    d = parse_date(rec["date"])
    calculated = attendance_recalculated(rec["status"], pin, ts, emp, d)
    updated = db.attendance_logs.find_one_and_update(
        {"emp_code": body.emp_code, "date": rec["date"], "punch_out": None},
        {"$set": {k: calculated[k] for k in ("punch_out", "work_hours", "overtime_minutes", "half_day")}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None: raise HTTPException(409, "record already punched out")
    return public_attendance(updated)


@app.get("/attendance")
def list_attendance(emp_code: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                    status: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    validate_page(page, page_size)
    if date_from: parse_date(date_from, "date_from")
    if date_to: parse_date(date_to, "date_to")
    if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must be <= date_to")
    if status and status not in ALL_STATUSES: raise HTTPException(422, "invalid status")
    q: dict[str, Any] = {}
    if emp_code: q["emp_code"] = emp_code
    if status: q["status"] = status
    if date_from or date_to:
        q["date"] = {}
        if date_from: q["date"]["$gte"] = date_from
        if date_to: q["date"]["$lte"] = date_to
    total = db.attendance_logs.count_documents(q)
    docs = db.attendance_logs.find(q).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page - 1) * page_size).limit(page_size)
    return {"items": [public_attendance(d) for d in docs], "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: RegularizeIn):
    d = parse_date(date)
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp or not db.attendance_logs.find_one({"emp_code": emp_code, "date": date}): raise HTTPException(404, "employee or attendance record not found")
    current = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    status = body.status if body.status is not None else current["status"]
    pin = parse_epoch_ms(body.punch_in, "punch_in") if body.punch_in is not None else current.get("punch_in")
    pout = parse_epoch_ms(body.punch_out, "punch_out") if body.punch_out is not None else current.get("punch_out")
    if status in ("ABSENT", "LEAVE") and (body.punch_in is not None or body.punch_out is not None):
        raise HTTPException(422, "ABSENT and LEAVE cannot be supplied with punch times")
    if pin is not None:
        actual_day = attendance_date_for(pin, emp["shift_start"], emp["shift_end"])
        if actual_day != d: raise HTTPException(422, "punch_in must belong to the record attendance date")
    calculated = attendance_recalculated(status, pin, pout, emp, d)
    fields = ["status", "punch_in", "punch_out", "work_hours", "late_minutes", "overtime_minutes", "half_day"]
    changes = {}
    for key in fields:
        old, new = current.get(key), calculated.get(key)
        if key in ("late_minutes", "overtime_minutes"): old = int(old or 0)
        if key == "half_day": old = bool(old or False)
        if old != new:
            changes[key] = {"from": old, "to": new}
    if not changes: raise HTTPException(422, "regularization must change at least one field")
    at = datetime.now(UTC).replace(microsecond=0)
    history_entry = {"at": at, "by": body.regularized_by, "reason": body.reason, "changes": changes}
    # Compare-and-swap protects against concurrent edits; history is appended atomically.
    old_history = current.get("history", [])
    history_filter = {"history": old_history} if "history" in current else {"history": {"$exists": False}}
    compare_filter = {"emp_code": emp_code, "date": date, "status": current["status"], "punch_in": current.get("punch_in"), "punch_out": current.get("punch_out"), **history_filter}
    result = db.attendance_logs.find_one_and_update(
        compare_filter,
        {"$set": calculated, "$push": {"history": history_entry}}, return_document=ReturnDocument.AFTER,
    )
    if result is None: raise HTTPException(409, "record changed concurrently; retry the correction")
    return public_attendance(result)


# ----------------------------- aggregation helpers --------------------------
def month_match(month: str) -> tuple[date, date, str, str]:
    start, end = parse_month(month)
    return start, end, start.isoformat(), end.isoformat()


def weekday_count(start: date, end: date) -> int:
    if end < start: return 0
    days = (end - start).days + 1
    full, rem = divmod(days, 7)
    count = full * 5
    for i in range(rem):
        if (start.weekday() + i) % 7 < 5: count += 1
    return count


def round2(value: Any) -> Optional[float]:
    if value is None: return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round4(value: Any) -> Optional[float]:
    if value is None: return None
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def present_expr() -> dict:
    return {"$in": ["$status", PRESENT_STATUSES]}


def attendance_pipeline_for_month(emp_code: str, month: str) -> list[dict]:
    start, end, s, e = month_match(month)
    return [
        {"$match": {"emp_code": emp_code, "date": {"$gte": s, "$lte": e}}},
        {"$set": {"_weekday": {"$in": [{"$isoDayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [1, 2, 3, 4, 5]]}}},
        {"$group": {"_id": None,
            "present_days": {"$sum": {"$cond": [{"$and": [present_expr(), "$_weekday"]}, {"$cond": [{"$eq": [{"$ifNull": ["$half_day", False]}, True]}, 0.5, 1]}, 0]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
        }}
    ]


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    start, end, _, _ = month_match(month)
    emp = db.employees.find_one({"emp_code": emp_code}, {"_id": 0, "joined_on": 1})
    if not emp: raise HTTPException(404, "employee not found")
    joined = max(start, parse_date(emp["joined_on"], "joined_on"))
    working = weekday_count(joined, end)
    rows = list(db.attendance_logs.aggregate(attendance_pipeline_for_month(emp_code, month)))
    row = rows[0] if rows else {}
    present = round2(row.get("present_days", 0)) or 0.0
    pct = round4(present / working * 100) if working else None
    return {"emp_code": emp_code, "month": month, "working_days": working, "present_days": present,
            "leave_days": int(row.get("leave_days", 0)), "late_count": int(row.get("late_count", 0)),
            "total_late_minutes": int(row.get("total_late_minutes", 0)), "total_overtime_minutes": int(row.get("total_overtime_minutes", 0)), "attendance_pct": pct}


def department_summary_pipeline(month: str, department: Optional[str] = None) -> list[dict]:
    start, end, s, e = month_match(month)
    match: dict[str, Any] = {"joined_on": {"$lte": e}}
    if department is not None: match["department"] = department
    return [
        {"$match": match},
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", s]}, {"$lte": ["$date", e]}]}}},
            {"$set": {"_weekday": {"$in": [{"$isoDayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [1,2,3,4,5]]}}}
        ], "as": "logs"}},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": "$department", "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$logs.status", PRESENT_STATUSES]}, {"$eq": ["$logs._weekday", True]}]}, {"$cond": [{"$eq": [{"$ifNull": ["$logs.half_day", False]}, True]}, 0.5, 1]}, 0]}},
            "work_hours_sum": {"$sum": {"$cond": [{"$and": [{"$in": ["$logs.status", PRESENT_STATUSES]}, {"$ne": ["$logs.work_hours", None]}]}, "$logs.work_hours", 0]}},
            "work_hours_count": {"$sum": {"$cond": [{"$and": [{"$in": ["$logs.status", PRESENT_STATUSES]}, {"$ne": ["$logs.work_hours", None]}]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$logs.late_minutes", 0]}},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}},
            "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}}}},
        {"$project": {"_id": 0, "department": "$_id", "headcount": {"$size": "$headcount"}, "present_days": 1,
            "avg_work_hours": {"$cond": [{"$gt": ["$work_hours_count", 0]}, {"$divide": ["$work_hours_sum", "$work_hours_count"]}, None]},
            "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1}},
        {"$sort": {"department": 1}},
    ]


@app.get("/analytics/departments/summary")
def department_summary(month: str, department: Optional[str] = None):
    month_match(month)
    items = []
    for row in db.employees.aggregate(department_summary_pipeline(month, department)):
        row["present_days"] = round2(row.get("present_days", 0)) or 0.0
        row["avg_work_hours"] = round2(row.get("avg_work_hours"))
        items.append(row)
    return {"month": month, "items": items}


def late_leaderboard_pipeline(month: str, department: Optional[str] = None, limit: int = 10) -> list[dict]:
    _, _, s, e = month_match(month)
    pipeline: list[dict] = [
        {"$match": {"date": {"$gte": s, "$lte": e}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}, "late_count": {"$sum": 1}}},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
    ]
    if department is not None: pipeline.append({"$match": {"employee.department": department}})
    pipeline += [
        {"$set": {"emp_code": "$_id", "name": "$employee.name", "department": "$employee.department"}},
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}},
        {"$project": {"_id": 0, "rank": 1, "emp_code": 1, "name": 1, "department": 1, "total_late_minutes": 1, "late_count": 1}},
    ]
    return pipeline


@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str, limit: int = Query(10, ge=1, le=50), department: Optional[str] = None):
    month_match(month)
    return {"month": month, "items": list(db.attendance_logs.aggregate(late_leaderboard_pipeline(month, department, limit)))}


def department_trend_pipeline(department: str, start: date, end: date) -> list[dict]:
    # Build day rows inside MongoDB, then join each employee/day to logs. This naturally fills gaps.
    count = (end - start).days + 1
    start_dt = datetime.combine(start, time.min, UTC)
    return [
        {"$match": {"department": department}},
        {"$set": {"_days": {"$map": {"input": {"$range": [0, count]}, "as": "offset", "in": {"$dateToString": {"date": {"$dateAdd": {"startDate": start_dt, "unit": "day", "amount": "$$offset"}}, "format": "%Y-%m-%d"}}}}}},
        {"$unwind": "$_days"},
        {"$set": {"_day": "$_days", "_joined": {"$lte": ["$joined_on", "$_days"]}}},
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code", "day": "$_day"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$eq": ["$date", "$$day"]}]}}}
        ], "as": "_logs"}},
        {"$unwind": {"path": "$_logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": "$_day", "headcount": {"$sum": {"$cond": ["$_joined", 1, 0]}},
            "present_count": {"$sum": {"$cond": [{"$in": ["$_logs.status", PRESENT_STATUSES]}, {"$cond": [{"$eq": [{"$ifNull": ["$_logs.half_day", False]}, True]}, 0.5, 1]}, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$_logs.late_minutes", 0]}, 0]}, 1, 0]}}}},
        {"$set": {"date": "$_id", "_dow": {"$isoDayOfWeek": {"$dateFromString": {"dateString": "$_id"}}}}},
        {"$set": {"is_working_day": {"$lte": ["$_dow", 5]}, "attendance_rate": {"$cond": [{"$and": [{"$lte": ["$_dow", 5]}, {"$gt": ["$headcount", 0]}]}, {"$divide": ["$present_count", "$headcount"]}, None]}}},
        {"$sort": {"date": 1}},
        {"$setWindowFields": {"sortBy": {"date": 1}, "output": {"moving_avg_7d": {"$avg": "$attendance_rate", "window": {"documents": [-6, "current"]}}}}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1, "present_count": 1, "late_count": 1, "attendance_rate": 1, "moving_avg_7d": 1}},
    ]


@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_date: str = Query(..., alias="from"), to_date: str = Query(..., alias="to")):
    start, end = parse_date(from_date, "from"), parse_date(to_date, "to")
    if end < start: raise HTTPException(422, "to must be on or after from")
    if (end - start).days + 1 > 92: raise HTTPException(422, "date range cannot exceed 92 days")
    if not db.employees.find_one({"department": department}, {"_id": 1}): raise HTTPException(404, "department not found")
    items = list(db.employees.aggregate(department_trend_pipeline(department, start, end)))
    for row in items:
        row["present_count"] = round2(row.get("present_count", 0)) or 0.0
        row["attendance_rate"] = round4(row.get("attendance_rate"))
        row["moving_avg_7d"] = round4(row.get("moving_avg_7d"))
    return {"department": department, "items": items}


# --------------------------------- explain ----------------------------------
def explain_query(collection: str, pipeline: list[dict]) -> dict:
    coll = db[collection]
    return db.command({"explain": {"aggregate": coll.name, "pipeline": pipeline, "cursor": {}}, "verbosity": "executionStats"})


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: str, emp_code: Optional[str] = None, month: Optional[str] = None,
                     department: Optional[str] = None, limit: int = Query(10, ge=1, le=50),
                     date_from: Optional[str] = None, date_to: Optional[str] = None, status: Optional[str] = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     from_date: Optional[str] = Query(None, alias="from"), to_date: Optional[str] = Query(None, alias="to")):
    if endpoint == "attendance_list":
        if date_from: parse_date(date_from, "date_from")
        if date_to: parse_date(date_to, "date_to")
        if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must be <= date_to")
        q: dict[str, Any] = {}
        if emp_code: q["emp_code"] = emp_code
        if status:
            if status not in ALL_STATUSES: raise HTTPException(422, "invalid status")
            q["status"] = status
        if date_from or date_to:
            q["date"] = {}
            if date_from: q["date"]["$gte"] = date_from
            if date_to: q["date"]["$lte"] = date_to
        pipeline = [{"$match": q}, {"$sort": {"date": -1, "emp_code": 1}}, {"$skip": (page - 1) * page_size}, {"$limit": page_size}]
        collection = "attendance_logs"
    elif endpoint == "employee_monthly":
        if not emp_code or not month: raise HTTPException(422, "emp_code and month are required")
        pipeline = attendance_pipeline_for_month(emp_code, month); collection = "attendance_logs"
    elif endpoint == "department_summary":
        if not month: raise HTTPException(422, "month is required")
        pipeline = department_summary_pipeline(month, department); collection = "employees"
    elif endpoint == "late_leaderboard":
        if not month: raise HTTPException(422, "month is required")
        pipeline = late_leaderboard_pipeline(month, department, limit); collection = "attendance_logs"
    elif endpoint == "department_trend":
        if not department or not from_date or not to_date: raise HTTPException(422, "department, from and to are required")
        start, end = parse_date(from_date, "from"), parse_date(to_date, "to")
        if end < start or (end - start).days + 1 > 92: raise HTTPException(422, "invalid trend date range")
        pipeline = department_trend_pipeline(department, start, end); collection = "employees"
    else:
        raise HTTPException(422, "endpoint must be one of attendance_list, employee_monthly, department_summary, late_leaderboard, department_trend")
    try:
        explain = explain_query(collection, pipeline)
    except PyMongoError as exc:
        raise HTTPException(503, f"explain unavailable: {type(exc).__name__}")
    return {"endpoint": endpoint, "collection": collection, "explain": json_util.loads(json_util.dumps(explain))}
