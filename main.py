"""FastAPI backend (Week 3, Card Д: Variant 1 = Python / FastAPI + Swagger UI).

Run:   uvicorn main:app --reload
UI:    http://127.0.0.1:8000/        Swagger: http://127.0.0.1:8000/docs

Storage is IN-MEMORY for now (dict of sessions). Swap for PostgreSQL + SQLAlchemy later.
Endpoints follow the Week 3 paths; CSV field names follow Week 4 (order_id, weight_kg, ...).
"""
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import planner as core
from planner import ImportValidationError, PlanError, Planner, text_source

app = FastAPI(title="Fast Delivery Siberia — planner (v0.2)")
SESSIONS: dict[str, Planner] = {}
STATIC = Path(__file__).parent / "static"


class ImportRequest(BaseModel):
    orders_csv: str                    # contents of orders.csv     (order_id,weight_kg)
    vehicles_csv: str                  # contents of vehicles.csv   (vehicle_id,capacity_kg)
    matrix_csv: str | None = None      # optional distance matrix


def error(status: int, code: str, message: str, issues: list | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "code": code, "message": message,
        "errors": [{"row": i.row, "field": i.field, "message": i.message} for i in issues or []]})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/v1/planning-sessions/import", status_code=201)
def import_session(req: ImportRequest):
    """L01. Atomic: a session exists only if EVERYTHING validated; on error nothing is stored."""
    p = Planner()
    try:
        p.import_orders(text_source(req.orders_csv))
        p.import_vehicles(text_source(req.vehicles_csv))
        if req.matrix_csv and req.matrix_csv.strip():
            p.import_distance_matrix(text_source(req.matrix_csv))
    except ImportValidationError as e:
        return error(422, "VALIDATION_ERROR", "Import rejected", e.issues)
    sid = str(uuid.uuid4())
    SESSIONS[sid] = p
    return {"planning_session_id": sid, "orders": len(p.orders), "vehicles": len(p.vehicles),
            "has_distance_matrix": p.matrix is not None}


@app.post("/api/v1/planning-sessions/{session_id}/calculate")
def calculate(session_id: str):
    """L02. Deterministic, so repeating the call returns the same plan (idempotent)."""
    p = SESSIONS.get(session_id)
    if p is None:
        return error(404, "SESSION_NOT_FOUND", "Unknown planning session")
    try:
        r = p.allocate()
    except PlanError as e:
        return error(422, "PLAN_ERROR", str(e))
    return {
        "planning_session_id": session_id,
        "assigned_share": r.assigned_share,
        "assignments": [
            {"order_id": o.order_id, "weight_kg": o.weight_kg, "vehicle_id": r.assignment[o.order_id],
             "status": "assigned" if r.assignment[o.order_id] else "unassigned",
             "reason": r.reasons.get(o.order_id)} for o in p.orders],
        "vehicles": [
            {"vehicle_id": v.vehicle_id, "capacity_kg": v.capacity_kg, "load_kg": r.load_kg[v.vehicle_id],
             "route": r.routes.get(v.vehicle_id), "distance_km": r.distance.get(v.vehicle_id)}
            for v in p.vehicles],
    }


@app.get("/api/v1/planning-sessions/{session_id}/unassigned.csv")
def unassigned_csv(session_id: str):
    """L04. Header-only file when nothing is unassigned. 409 if calculate was not run yet."""
    p = SESSIONS.get(session_id)
    if p is None:
        return error(404, "SESSION_NOT_FOUND", "Unknown planning session")
    if p.result is None:
        return error(409, "NOT_CALCULATED", "Run calculate before export")
    tmp = STATIC / f".export-{uuid.uuid4().hex}.csv"
    try:
        p.export_unassigned_csv(tmp)
        body = tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="unassigned_orders.csv"'})
