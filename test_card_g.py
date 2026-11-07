"""Card G, Week 4 — one test per scenario (IDs as in the card), plus a few boundary extras.
Run:  pip install pytest && pytest -v
"""
import csv
import pytest
from planner import (Planner, ImportValidationError, PlanError, MSG_WEIGHT_POSITIVE,
                     MSG_WEIGHT_FORMAT, REASON_TOO_HEAVY, EXPORT_HEADER)


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    return path


@pytest.fixture
def mk(tmp_path):
    """mk(orders=[(id,w)], vehicles=[(id,cap)]) -> Planner with data imported."""
    def _mk(orders, vehicles):
        p = Planner()
        p.import_orders(write(tmp_path / "orders.csv", ["order_id", "weight_kg"], orders))
        p.import_vehicles(write(tmp_path / "vehicles.csv", ["vehicle_id", "capacity_kg"], vehicles))
        return p
    return _mk


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


# ------------------------------ positive ------------------------------------
def test_TC_P_01_valid_import(tmp_path):
    p = Planner()
    orders = p.import_orders(write(tmp_path / "orders.csv", ["order_id", "weight_kg"], [("O1", 300), ("O2", 200)]))
    vehicles = p.import_vehicles(write(tmp_path / "vehicles.csv", ["vehicle_id", "capacity_kg"], [("V1", 500)]))
    assert [(o.order_id, o.weight_kg) for o in orders] == [("O1", 300), ("O2", 200)]
    assert [(v.vehicle_id, v.capacity_kg) for v in vehicles] == [("V1", 500)]
    assert p.orders and p.vehicles           # objects live in memory


def test_TC_P_02_full_allocation(mk):
    r = mk([("O1", 200), ("O2", 300)], [("V1", 500)]).allocate()
    assert r.assignment == {"O1": "V1", "O2": "V1"}
    assert r.load_kg["V1"] == 500 <= 500
    assert r.assigned_share == 1.0
    assert r.reasons == {}


def test_TC_P_03_partial_allocation(mk):
    r = mk([("O1", 800), ("O2", 300)], [("V1", 500), ("V2", 500)]).allocate()
    assert r.assignment["O2"] in ("V1", "V2")           # card accepts either
    assert r.assignment["O1"] is None
    assert r.reasons == {"O1": "Exceeds vehicle capacity"}
    assert r.assigned_share == 0.5


def test_TC_P_04_export_unassigned(mk, tmp_path):
    p = mk([("O1", 800), ("O2", 300)], [("V1", 500), ("V2", 500)])
    p.allocate()
    out = p.export_unassigned_csv(tmp_path / "unassigned.csv")
    assert read_csv(out) == [EXPORT_HEADER, ["O1", "Exceeds vehicle capacity"]]


# ------------------------------ negative ------------------------------------
def test_TC_N_01_zero_and_negative_weight(tmp_path):
    p = Planner()
    f = write(tmp_path / "orders.csv", ["order_id", "weight_kg"], [("O1", 0), ("O2", -1)])
    with pytest.raises(ImportValidationError) as e:
        p.import_orders(f)
    assert e.value.messages() == [MSG_WEIGHT_POSITIVE] * 2      # both rows reported
    assert p.orders == []                                        # rejected -> nothing enters allocation


def test_TC_N_02_non_numeric_weight(tmp_path):
    p = Planner()
    f = write(tmp_path / "orders.csv", ["order_id", "weight_kg"], [("O1", "abc")])
    with pytest.raises(ImportValidationError) as e:
        p.import_orders(f)
    assert e.value.messages() == [MSG_WEIGHT_FORMAT]
    assert p.orders == []


def test_TC_N_03_duplicate_order_id(tmp_path):
    p = Planner()
    f = write(tmp_path / "orders.csv", ["order_id", "weight_kg"], [("O1", 300), ("O1", 200)])
    with pytest.raises(ImportValidationError) as e:
        p.import_orders(f)
    assert "Duplicate order_id found: O1" in e.value.messages()
    assert p.orders == []


def test_TC_N_08_export_with_nothing_unassigned(mk, tmp_path):
    # NB: card calls this TC-N-08; sequence suggests TC-N-04 (see notes).
    p = mk([("O1", 200)], [("V1", 500)])
    p.allocate()
    out = p.export_unassigned_csv(tmp_path / "unassigned.csv")
    assert read_csv(out) == [EXPORT_HEADER]                      # header only


# ------------------------------ regression ----------------------------------
def test_TC_R_01_export_does_not_change_plan(mk, tmp_path):
    p = mk([("O1", 800), ("O2", 300)], [("V1", 500), ("V2", 500)])
    before = p.allocate()
    snapshot = (dict(before.assignment), dict(before.reasons), dict(before.load_kg), before.assigned_share)
    p.export_unassigned_csv(tmp_path / "u.csv")
    after = p.result
    assert (after.assignment, after.reasons, after.load_kg, after.assigned_share) == snapshot
    assert after.assignment["O2"] == "V1" and after.assignment["O1"] is None
    assert after.assigned_share == 0.5
    # re-running gives the same result (deterministic)
    again = p.allocate()
    assert again.assignment == snapshot[0]


def test_TC_R_02_validation_stable_on_reimport(tmp_path):
    bad = write(tmp_path / "orders_bad.csv", ["order_id", "weight_kg"], [("O1", -1)])
    good = write(tmp_path / "orders_good.csv", ["order_id", "weight_kg"], [("O1", 300)])
    p = Planner()
    with pytest.raises(ImportValidationError):
        p.import_orders(bad)                                     # step 1
    p.import_orders(good)                                        # step 2
    assert [o.order_id for o in p.orders] == ["O1"]
    with pytest.raises(ImportValidationError) as e:
        p.import_orders(bad)                                     # step 3: still blocked
    assert e.value.messages() == [MSG_WEIGHT_POSITIVE]
    assert [o.weight_kg for o in p.orders] == [300]              # ASSUMPTION: failed import keeps last good data


# ------------------------------ extras (boundaries from the case data) ------
def test_single_order_exactly_capacity(mk):
    r = mk([("O1", 500)], [("V1", 500)]).allocate()
    assert r.assignment == {"O1": "V1"} and r.assigned_share == 1.0


def test_order_just_over_capacity(mk):
    r = mk([("O1", 500.01)], [("V1", 500)]).allocate()
    assert r.assignment["O1"] is None and r.reasons["O1"] == REASON_TOO_HEAVY


def test_never_exceeds_capacity_and_assigns_once(mk):
    orders = [(f"O{i}", w) for i, w in enumerate([400, 300, 300, 200, 200, 150, 100, 100, 50, 50], 1)]
    r = mk(orders, [("V1", 500), ("V2", 500)]).allocate()
    assert all(load <= 500 for load in r.load_kg.values())
    assert set(r.assignment) == {o for o, _ in orders}          # every order present, once
    assert all((v is None) == (o in r.reasons) for o, v in r.assignment.items())


def test_export_before_allocation_fails(mk, tmp_path):
    with pytest.raises(PlanError):
        mk([("O1", 1)], [("V1", 5)]).export_unassigned_csv(tmp_path / "x.csv")


def test_export_escapes_special_chars(mk, tmp_path):
    p = mk([("O,1", 800)], [("V1", 500)])
    p.allocate()
    out = p.export_unassigned_csv(tmp_path / "u.csv")
    assert read_csv(out)[1] == ["O,1", "Exceeds vehicle capacity"]
