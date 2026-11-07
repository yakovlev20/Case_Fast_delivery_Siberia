"""API-level checks of Card G scenarios (needs: pip install fastapi httpx pytest)."""
from fastapi.testclient import TestClient
from main import app

c = TestClient(app)
V2 = "vehicle_id,capacity_kg\nV1,500\nV2,500\n"


def imp(orders, vehicles=V2):
    return c.post("/api/v1/planning-sessions/import", json={"orders_csv": orders, "vehicles_csv": vehicles})


def test_p03_p04_r01_flow():
    r = imp("order_id,weight_kg\nO1,800\nO2,300\n")
    assert r.status_code == 201
    sid = r.json()["planning_session_id"]
    plan = c.post(f"/api/v1/planning-sessions/{sid}/calculate").json()
    assert plan["assigned_share"] == 0.5
    by = {a["order_id"]: a for a in plan["assignments"]}
    assert by["O1"]["reason"] == "Exceeds vehicle capacity" and by["O2"]["vehicle_id"] in ("V1", "V2")
    csv_resp = c.get(f"/api/v1/planning-sessions/{sid}/unassigned.csv")
    assert csv_resp.text.splitlines() == ["order_id,reason", "O1,Exceeds vehicle capacity"]
    assert c.post(f"/api/v1/planning-sessions/{sid}/calculate").json() == plan      # export didn't change plan


def test_p04_header_only():
    sid = imp("order_id,weight_kg\nO1,200\n").json()["planning_session_id"]
    c.post(f"/api/v1/planning-sessions/{sid}/calculate")
    assert c.get(f"/api/v1/planning-sessions/{sid}/unassigned.csv").text.splitlines() == ["order_id,reason"]


def test_n01_n02_n03_422():
    r = imp("order_id,weight_kg\nO1,0\nO2,-1\n")
    assert r.status_code == 422 and [e["message"] for e in r.json()["errors"]] == ["Weight must be a positive number"] * 2
    assert imp("order_id,weight_kg\nO1,abc\n").json()["errors"][0]["message"] == "Invalid numeric format for weight_kg"
    assert "Duplicate order_id found: O1" in [e["message"] for e in imp("order_id,weight_kg\nO1,300\nO1,200\n").json()["errors"]]


def test_export_before_calculate_is_409():
    sid = imp("order_id,weight_kg\nO1,200\n").json()["planning_session_id"]
    assert c.get(f"/api/v1/planning-sessions/{sid}/unassigned.csv").status_code == 409
