"""Barebone planner for the 'Fast Delivery Siberia' case (v0.2 scope: L01, L02, L04).

Scope = capacity-only allocation of indivisible orders (Card G, Week 4).
The distance matrix is OPTIONAL: if loaded, it is validated and used only to
order stops (nearest neighbour) and report mileage. It never changes assignment.

Stdlib only.
"""
from __future__ import annotations

import contextlib
import csv
import io
import math
from dataclasses import dataclass, field
from pathlib import Path

# ---- messages fixed by the test cards (change here, tests follow) ----------
MSG_WEIGHT_POSITIVE = "Weight must be a positive number"
MSG_WEIGHT_FORMAT = "Invalid numeric format for weight_kg"
MSG_CAPACITY_POSITIVE = "Capacity must be a positive number"
MSG_CAPACITY_FORMAT = "Invalid numeric format for capacity_kg"
MSG_DUP_ORDER = "Duplicate order_id found: {}"
MSG_DUP_VEHICLE = "Duplicate vehicle_id found: {}"
REASON_TOO_HEAVY = "Exceeds vehicle capacity"            # heavier than every vehicle
REASON_NO_ROOM = "Insufficient remaining capacity"        # ASSUMPTION: not in the ТЗ
EXPORT_HEADER = ["order_id", "reason"]
DEPOT = "DEPOT"


# ---- model -----------------------------------------------------------------
@dataclass(frozen=True)
class Order:
    order_id: str
    weight_kg: float


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    capacity_kg: float


@dataclass(frozen=True)
class Issue:
    row: int | None      # 1-based data row (header = row 0 / None)
    field: str | None
    message: str

    def __str__(self) -> str:
        where = f"row {self.row}, " if self.row else ""
        fld = f"{self.field}: " if self.field else ""
        return f"{where}{fld}{self.message}"


class ImportValidationError(Exception):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(map(str, issues)))

    def messages(self) -> list[str]:
        return [i.message for i in self.issues]


class PlanError(Exception):
    pass


@dataclass
class PlanResult:
    assignment: dict[str, str | None]          # order_id -> vehicle_id or None
    reasons: dict[str, str]                    # order_id -> reason (unassigned only)
    load_kg: dict[str, float]                  # vehicle_id -> total assigned weight
    routes: dict[str, list[str]] = field(default_factory=dict)       # vehicle_id -> stop order
    distance: dict[str, float] = field(default_factory=dict)         # vehicle_id -> km (if matrix)

    @property
    def assigned_share(self) -> float:
        return (sum(v is not None for v in self.assignment.values()) / len(self.assignment)
                if self.assignment else 0.0)


# ---- CSV helpers -----------------------------------------------------------
def text_source(text: str) -> io.StringIO:
    """Wrap CSV text (e.g. from an HTTP request) so import_* can read it like a file."""
    return io.StringIO(text.lstrip("\ufeff"), newline="")


def _open(src):
    """src = path, or file-like object (StringIO)."""
    if hasattr(src, "read"):
        return contextlib.nullcontext(src)
    return open(src, newline="", encoding="utf-8-sig")        # utf-8-sig tolerates Excel BOM


def _read_rows(path, required: list[str]) -> list[tuple[int, dict[str, str]]]:
    with _open(path) as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in required if c not in header]
        if missing:
            raise ImportValidationError(
                [Issue(0, c, f"Missing column: {c}") for c in missing])
        rows = []
        for n, raw in enumerate(reader, start=1):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if any(row.values()):                              # skip blank lines
                rows.append((n, row))
        return rows


def _parse_positive(text: str, fmt_msg: str, pos_msg: str) -> tuple[float | None, str | None]:
    try:
        x = float(text)
    except ValueError:
        return None, fmt_msg
    if math.isnan(x) or math.isinf(x):
        return None, fmt_msg
    if x <= 0:
        return None, pos_msg
    return x, None


# ---- planner (holds in-memory state) --------------------------------------
class Planner:
    def __init__(self) -> None:
        self.orders: list[Order] = []
        self.vehicles: list[Vehicle] = []
        self.matrix: dict[str, dict[str, float]] | None = None
        self.result: PlanResult | None = None

    # L01 ---- import. All-or-nothing: on any error previous state is untouched.
    def import_orders(self, path) -> list[Order]:
        issues: list[Issue] = []
        out: list[Order] = []
        seen: set[str] = set()
        for n, row in _read_rows(path, ["order_id", "weight_kg"]):
            oid = row["order_id"]
            if not oid:
                issues.append(Issue(n, "order_id", "order_id must not be empty"))
            elif oid in seen:
                issues.append(Issue(n, "order_id", MSG_DUP_ORDER.format(oid)))
            seen.add(oid)
            w, err = _parse_positive(row["weight_kg"], MSG_WEIGHT_FORMAT, MSG_WEIGHT_POSITIVE)
            if err:
                issues.append(Issue(n, "weight_kg", err))
            elif oid:
                out.append(Order(oid, w))
        if issues:
            raise ImportValidationError(issues)
        self.orders, self.result = out, None       # new data invalidates old plan
        return out

    def import_vehicles(self, path) -> list[Vehicle]:
        issues: list[Issue] = []
        out: list[Vehicle] = []
        seen: set[str] = set()
        for n, row in _read_rows(path, ["vehicle_id", "capacity_kg"]):
            vid = row["vehicle_id"]
            if not vid:
                issues.append(Issue(n, "vehicle_id", "vehicle_id must not be empty"))
            elif vid in seen:
                issues.append(Issue(n, "vehicle_id", MSG_DUP_VEHICLE.format(vid)))
            seen.add(vid)
            c, err = _parse_positive(row["capacity_kg"], MSG_CAPACITY_FORMAT, MSG_CAPACITY_POSITIVE)
            if err:
                issues.append(Issue(n, "capacity_kg", err))
            elif vid:
                out.append(Vehicle(vid, c))
        if issues:
            raise ImportValidationError(issues)
        self.vehicles, self.result = out, None
        return out

    def import_distance_matrix(self, path) -> None:
        """CSV: first row = ',DEPOT,O1,O2,...'; first column = same ids. Square, >=0, zero diagonal."""
        with _open(path) as f:
            grid = [[c.strip() for c in r] for r in csv.reader(f) if any(c.strip() for c in r)]
        if not grid or len(grid) < 2:
            raise ImportValidationError([Issue(None, None, "Distance matrix is empty")])
        ids = grid[0][1:]
        issues: list[Issue] = []
        if [r[0] for r in grid[1:]] != ids:
            issues.append(Issue(None, None, "Matrix row ids must match column ids (square matrix)"))
        m: dict[str, dict[str, float]] = {}
        for r in grid[1:]:
            if len(r) != len(ids) + 1:
                issues.append(Issue(None, r[0], "Row length does not match header"))
                continue
            m[r[0]] = {}
            for cid, cell in zip(ids, r[1:]):
                try:
                    d = float(cell)
                    if d < 0 or math.isnan(d) or math.isinf(d):
                        raise ValueError
                except ValueError:
                    issues.append(Issue(None, f"{r[0]}->{cid}", f"Invalid distance: {cell!r}"))
                    continue
                m[r[0]][cid] = d
            if m[r[0]].get(r[0], 0.0) != 0.0:
                issues.append(Issue(None, r[0], "Diagonal must be 0"))
        if issues:
            raise ImportValidationError(issues)
        self.matrix, self.result = m, None

    # L02 ---- allocation. Strategy (fixed, deterministic): first-fit decreasing.
    #   orders sorted by weight desc, then order_id; vehicles in file order.
    def allocate(self) -> PlanResult:
        if not self.orders or not self.vehicles:
            raise PlanError("Import orders and vehicles before allocation")
        if self.matrix is not None:
            absent = [i for i in [DEPOT, *(o.order_id for o in self.orders)] if i not in self.matrix]
            if absent:   # Week 2 remark: no silent heuristic on missing matrix data
                raise PlanError(f"Distance matrix lacks ids: {', '.join(absent)}")

        free = {v.vehicle_id: v.capacity_kg for v in self.vehicles}
        load = {v.vehicle_id: 0.0 for v in self.vehicles}
        max_cap = max(v.capacity_kg for v in self.vehicles)
        assignment: dict[str, str | None] = {}
        reasons: dict[str, str] = {}

        for o in sorted(self.orders, key=lambda o: (-o.weight_kg, o.order_id)):
            target = next((v.vehicle_id for v in self.vehicles if o.weight_kg <= free[v.vehicle_id]), None)
            if target is None:
                assignment[o.order_id] = None
                reasons[o.order_id] = REASON_TOO_HEAVY if o.weight_kg > max_cap else REASON_NO_ROOM
            else:
                assignment[o.order_id] = target
                free[target] -= o.weight_kg
                load[target] += o.weight_kg

        # report in original input order
        assignment = {o.order_id: assignment[o.order_id] for o in self.orders}
        res = PlanResult(assignment, reasons, load)
        if self.matrix is not None:
            self._route(res)
        self.result = res
        return res

    def _route(self, res: PlanResult) -> None:
        for v in self.vehicles:
            todo = [o for o, veh in res.assignment.items() if veh == v.vehicle_id]
            cur, route, km = DEPOT, [], 0.0
            while todo:
                nxt = min(todo, key=lambda x: (self.matrix[cur][x], x))
                km += self.matrix[cur][nxt]; route.append(nxt); todo.remove(nxt); cur = nxt
            if route:
                km += self.matrix[cur][DEPOT]
            res.routes[v.vehicle_id], res.distance[v.vehicle_id] = route, km

    # L04 ---- export. Read-only with respect to the plan (TC-R-01).
    def export_unassigned_csv(self, path) -> Path:
        if self.result is None:
            raise PlanError("Run allocation before export")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")        # csv module quotes commas/quotes/newlines
            w.writerow(EXPORT_HEADER)
            for oid, reason in self.result.reasons.items():
                w.writerow([oid, reason])
        return Path(path)
