import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


class VehicleType:
    CAR = "car"
    MOTORBIKE = "motorbike"
    TRUCK = "truck"


class SpotType:
    COMPACT = "compact"
    BIKE = "bike"
    LARGE = "large"


VEHICLE_TO_SPOT = {
    VehicleType.CAR: SpotType.COMPACT,
    VehicleType.MOTORBIKE: SpotType.BIKE,
    VehicleType.TRUCK: SpotType.LARGE,
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def to_dt(raw):
    return datetime.fromisoformat(raw)


@dataclass
class ParkingTicketDTO:
    id: int
    plate_number: str
    vehicle_type: str
    spot_id: int
    issued_at: str
    allowed_until: str
    exit_at: str | None
    paid_amount: float | None
    status: str


class Database:
    def __init__(self, db_path="parking_management.db"):
        self.db_path = db_path
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row

    def execute(self, query, params=()):
        cur = self.connection.cursor()
        cur.execute(query, params)
        self.connection.commit()
        return cur

    def query_all(self, query, params=()):
        cur = self.connection.cursor()
        cur.execute(query, params)
        return cur.fetchall()

    def query_one(self, query, params=()):
        cur = self.connection.cursor()
        cur.execute(query, params)
        return cur.fetchone()

    def close(self):
        self.connection.close()


class VehicleDAO:
    def __init__(self, db):
        self.db = db

    def create(self, plate_number, vehicle_type):
        self.db.execute(
            """
            INSERT OR IGNORE INTO vehicles (plate_number, vehicle_type)
            VALUES (?, ?)
            """,
            (plate_number.upper(), vehicle_type),
        )

    def get(self, plate_number):
        return self.db.query_one(
            "SELECT * FROM vehicles WHERE plate_number = ?",
            (plate_number.upper(),),
        )

    def update(self, plate_number, vehicle_type):
        self.db.execute(
            "UPDATE vehicles SET vehicle_type = ? WHERE plate_number = ?",
            (vehicle_type, plate_number.upper()),
        )

    def delete(self, plate_number):
        self.db.execute("DELETE FROM vehicles WHERE plate_number = ?", (plate_number.upper(),))

    def list_all(self):
        return self.db.query_all("SELECT * FROM vehicles ORDER BY plate_number")


class SpotDAO:
    def __init__(self, db):
        self.db = db

    def create(self, spot_code, floor_number, spot_type):
        self.db.execute(
            """
            INSERT INTO parking_spots (spot_code, floor_number, spot_type, occupied)
            VALUES (?, ?, ?, 0)
            """,
            (spot_code, floor_number, spot_type),
        )

    def get(self, spot_id):
        return self.db.query_one("SELECT * FROM parking_spots WHERE id = ?", (spot_id,))

    def update_occupied(self, spot_id, occupied):
        self.db.execute(
            "UPDATE parking_spots SET occupied = ? WHERE id = ?",
            (1 if occupied else 0, spot_id),
        )

    def delete(self, spot_id):
        self.db.execute("DELETE FROM parking_spots WHERE id = ?", (spot_id,))

    def list_free_for_vehicle(self, vehicle_type):
        need_spot_type = VEHICLE_TO_SPOT[vehicle_type]
        return self.db.query_all(
            """
            SELECT * FROM parking_spots
            WHERE spot_type = ? AND occupied = 0
            ORDER BY floor_number, spot_code
            """,
            (need_spot_type,),
        )

    def list_all(self):
        return self.db.query_all(
            "SELECT * FROM parking_spots ORDER BY floor_number, spot_code"
        )


class TicketDAO:
    def __init__(self, db):
        self.db = db

    def create(self, plate_number, spot_id, issued_at, allowed_until):
        cur = self.db.execute(
            """
            INSERT INTO tickets (
                plate_number, spot_id, issued_at, allowed_until, exit_at, paid_amount, status
            ) VALUES (?, ?, ?, ?, NULL, NULL, 'ACTIVE')
            """,
            (plate_number.upper(), spot_id, issued_at, allowed_until),
        )
        return cur.lastrowid

    def get(self, ticket_id):
        row = self.db.query_one(
            """
            SELECT t.*, v.vehicle_type
            FROM tickets t
            JOIN vehicles v ON v.plate_number = t.plate_number
            WHERE t.id = ?
            """,
            (ticket_id,),
        )
        if row is None:
            return None
        return ParkingTicketDTO(
            id=row["id"],
            plate_number=row["plate_number"],
            vehicle_type=row["vehicle_type"],
            spot_id=row["spot_id"],
            issued_at=row["issued_at"],
            allowed_until=row["allowed_until"],
            exit_at=row["exit_at"],
            paid_amount=row["paid_amount"],
            status=row["status"],
        )

    def close_ticket(self, ticket_id, exit_at, paid_amount):
        self.db.execute(
            """
            UPDATE tickets
            SET exit_at = ?, paid_amount = ?, status = 'CLOSED'
            WHERE id = ?
            """,
            (exit_at, paid_amount, ticket_id),
        )

    def delete(self, ticket_id):
        self.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))

    def list_active(self):
        return self.db.query_all(
            """
            SELECT t.id, t.plate_number, v.vehicle_type, p.spot_code, p.floor_number,
                   t.issued_at, t.allowed_until
            FROM tickets t
            JOIN vehicles v ON v.plate_number = t.plate_number
            JOIN parking_spots p ON p.id = t.spot_id
            WHERE t.status = 'ACTIVE'
            ORDER BY t.issued_at
            """
        )

    def list_all(self):
        return self.db.query_all("SELECT * FROM tickets ORDER BY id")


class ReportDAO:
    def __init__(self, db):
        self.db = db

    def occupancy_by_floor(self):
        return self.db.query_all(
            """
            SELECT floor_number,
                   COUNT(*) AS total,
                   SUM(CASE WHEN occupied = 1 THEN 1 ELSE 0 END) AS occupied,
                   SUM(CASE WHEN occupied = 0 THEN 1 ELSE 0 END) AS free
            FROM parking_spots
            GROUP BY floor_number
            ORDER BY floor_number
            """
        )

    def occupancy_by_spot_type(self):
        return self.db.query_all(
            """
            SELECT spot_type,
                   COUNT(*) AS total,
                   SUM(CASE WHEN occupied = 1 THEN 1 ELSE 0 END) AS occupied
            FROM parking_spots
            GROUP BY spot_type
            ORDER BY spot_type
            """
        )

    def revenue_by_day(self):
        return self.db.query_all(
            """
            SELECT DATE(exit_at) AS day, ROUND(SUM(paid_amount), 2) AS revenue
            FROM tickets
            WHERE status = 'CLOSED'
            GROUP BY DATE(exit_at)
            ORDER BY day DESC
            """
        )

    def top_vehicles_by_visits(self):
        return self.db.query_all(
            """
            SELECT plate_number, COUNT(*) AS visits
            FROM tickets
            GROUP BY plate_number
            ORDER BY visits DESC, plate_number
            LIMIT 10
            """
        )

    def overdue_active_tickets(self):
        return self.db.query_all(
            """
            SELECT t.id, t.plate_number, p.spot_code, t.allowed_until
            FROM tickets t
            JOIN parking_spots p ON p.id = t.spot_id
            WHERE t.status = 'ACTIVE' AND t.allowed_until < ?
            ORDER BY t.allowed_until
            """,
            (now_iso(),),
        )

    def average_parking_duration_hours(self):
        row = self.db.query_one(
            """
            SELECT AVG((julianday(exit_at) - julianday(issued_at)) * 24.0) AS avg_hours
            FROM tickets
            WHERE status = 'CLOSED'
            """
        )
        return 0.0 if row["avg_hours"] is None else round(float(row["avg_hours"]), 2)


class ParkingModel:
    def __init__(self, db_path="parking_management.db", base_price=50.0, overtime_fine=100.0):
        self.db = Database(db_path)
        self.vehicle_dao = VehicleDAO(self.db)
        self.spot_dao = SpotDAO(self.db)
        self.ticket_dao = TicketDAO(self.db)
        self.report_dao = ReportDAO(self.db)
        self.base_price = float(base_price)
        self.overtime_fine = float(overtime_fine)
        self._build_schema()
        self._seed_spots_if_empty()

    def _build_schema(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                plate_number TEXT PRIMARY KEY,
                vehicle_type TEXT NOT NULL CHECK(vehicle_type IN ('car', 'motorbike', 'truck'))
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS parking_spots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spot_code TEXT NOT NULL UNIQUE,
                floor_number INTEGER NOT NULL,
                spot_type TEXT NOT NULL CHECK(spot_type IN ('compact', 'bike', 'large')),
                occupied INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate_number TEXT NOT NULL,
                spot_id INTEGER NOT NULL,
                issued_at TEXT NOT NULL,
                allowed_until TEXT NOT NULL,
                exit_at TEXT,
                paid_amount REAL,
                status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'CLOSED')),
                FOREIGN KEY (plate_number) REFERENCES vehicles(plate_number),
                FOREIGN KEY (spot_id) REFERENCES parking_spots(id)
            )
            """
        )

    def _seed_spots_if_empty(self):
        row = self.db.query_one("SELECT COUNT(*) AS cnt FROM parking_spots")
        if row["cnt"] > 0:
            return
        for i in range(1, 9):
            self.spot_dao.create(f"1-C{i}", 1, SpotType.COMPACT)
        for i in range(1, 5):
            self.spot_dao.create(f"1-B{i}", 1, SpotType.BIKE)
        for i in range(1, 4):
            self.spot_dao.create(f"1-L{i}", 1, SpotType.LARGE)
        for i in range(1, 7):
            self.spot_dao.create(f"2-C{i}", 2, SpotType.COMPACT)
        for i in range(1, 3):
            self.spot_dao.create(f"2-B{i}", 2, SpotType.BIKE)
        for i in range(1, 3):
            self.spot_dao.create(f"2-L{i}", 2, SpotType.LARGE)

    def validate_vehicle_type(self, vehicle_type):
        raw = vehicle_type.strip().lower()
        if raw not in VEHICLE_TO_SPOT:
            raise ValueError("Тип транспорта должен быть car, motorbike или truck")
        return raw

    def validate_plate_number(self, plate_number):
        cleaned = plate_number.strip().upper()
        if len(cleaned) < 4:
            raise ValueError("Номер машины слишком короткий")
        return cleaned

    def calculate_amount(self, allowed_until_iso, exit_at_iso):
        allowed_until = to_dt(allowed_until_iso)
        exit_at = to_dt(exit_at_iso)
        total = self.base_price
        if exit_at > allowed_until:
            overtime = exit_at - allowed_until
            overtime_hours = ceil(overtime.total_seconds() / 3600)
            total += overtime_hours * self.overtime_fine
        return round(total, 2)

    def park_vehicle(self, plate_number, vehicle_type, hours_allowed):
        plate = self.validate_plate_number(plate_number)
        v_type = self.validate_vehicle_type(vehicle_type)
        hours = int(hours_allowed)
        if hours <= 0:
            raise ValueError("Часы парковки должны быть больше 0")

        existing = self.vehicle_dao.get(plate)
        if existing is None:
            self.vehicle_dao.create(plate, v_type)
        elif existing["vehicle_type"] != v_type:
            self.vehicle_dao.update(plate, v_type)

        free_spots = self.spot_dao.list_free_for_vehicle(v_type)
        if not free_spots:
            raise RuntimeError("Нет свободных подходящих мест")

        spot = free_spots[0]
        issued_at = now_iso()
        allowed_until = (to_dt(issued_at) + timedelta(hours=hours)).isoformat(timespec="seconds")
        ticket_id = self.ticket_dao.create(plate, spot["id"], issued_at, allowed_until)
        self.spot_dao.update_occupied(spot["id"], True)
        return ticket_id

    def exit_vehicle(self, ticket_id):
        ticket = self.ticket_dao.get(int(ticket_id))
        if ticket is None:
            raise KeyError("Талон не найден")
        if ticket.status != "ACTIVE":
            raise RuntimeError("Талон уже закрыт")

        exit_at = now_iso()
        amount = self.calculate_amount(ticket.allowed_until, exit_at)
        self.ticket_dao.close_ticket(ticket.id, exit_at, amount)
        self.spot_dao.update_occupied(ticket.spot_id, False)
        return {
            "ticket_id": ticket.id,
            "plate_number": ticket.plate_number,
            "exit_at": exit_at,
            "amount": amount,
        }

    def get_dashboard(self):
        spots = self.spot_dao.list_all()
        total = len(spots)
        occupied = sum(1 for s in spots if s["occupied"] == 1)
        free = total - occupied
        active = self.ticket_dao.list_active()
        return {
            "total_spots": total,
            "free_spots": free,
            "occupied_spots": occupied,
            "active_tickets": len(active),
        }

    def get_active_tickets(self):
        return self.ticket_dao.list_active()

    def build_reports(self):
        return {
            "1. Загрузка по этажам": self.report_dao.occupancy_by_floor(),
            "2. Загрузка по типам мест": self.report_dao.occupancy_by_spot_type(),
            "3. Выручка по дням": self.report_dao.revenue_by_day(),
            "4. Топ машин по посещениям": self.report_dao.top_vehicles_by_visits(),
            "5. Просроченные активные талоны": self.report_dao.overdue_active_tickets(),
            "6. Средняя длительность (часы)": self.report_dao.average_parking_duration_hours(),
        }

    def close(self):
        self.db.close()


class ParkingView(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Parking Management System - MVC")
        self.geometry("980x640")
        self.minsize(820, 560)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Card.TFrame", background="#f4f7fb")
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Stat.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Body.TLabel", font=("Segoe UI", 10))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=14)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.header = ttk.Label(top, text="Parking Management", style="Header.TLabel")
        self.header.grid(row=0, column=0, sticky="w")

        center = ttk.Frame(self, padding=(14, 0, 14, 14))
        center.grid(row=1, column=0, sticky="nsew")
        center.columnconfigure(0, weight=1)
        center.columnconfigure(1, weight=1)
        center.rowconfigure(1, weight=1)

        self.dashboard_card = ttk.Frame(center, style="Card.TFrame", padding=12)
        self.dashboard_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.dashboard_card.columnconfigure(0, weight=1)
        self.dashboard_var = tk.StringVar(value="Загрузка данных...")
        ttk.Label(
            self.dashboard_card,
            textvariable=self.dashboard_var,
            style="Stat.TLabel",
            background="#f4f7fb",
        ).grid(row=0, column=0, sticky="w")

        left = ttk.LabelFrame(center, text="Регистрация въезда", padding=12)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(1, weight=1)

        ttk.Label(left, text="Номер машины:").grid(row=0, column=0, sticky="w", pady=4)
        self.plate_entry = ttk.Entry(left)
        self.plate_entry.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(left, text="Тип:").grid(row=1, column=0, sticky="w", pady=4)
        self.vehicle_type_combo = ttk.Combobox(
            left,
            values=[VehicleType.CAR, VehicleType.MOTORBIKE, VehicleType.TRUCK],
            state="readonly",
        )
        self.vehicle_type_combo.grid(row=1, column=1, sticky="ew", pady=4)
        self.vehicle_type_combo.current(0)

        ttk.Label(left, text="Часы:").grid(row=2, column=0, sticky="w", pady=4)
        self.hours_entry = ttk.Entry(left)
        self.hours_entry.insert(0, "2")
        self.hours_entry.grid(row=2, column=1, sticky="ew", pady=4)

        self.park_btn = ttk.Button(left, text="Припарковать")
        self.park_btn.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 2))

        ttk.Separator(left, orient="horizontal").grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)

        ttk.Label(left, text="Ticket ID для выезда:").grid(row=5, column=0, sticky="w", pady=4)
        self.ticket_id_entry = ttk.Entry(left)
        self.ticket_id_entry.grid(row=5, column=1, sticky="ew", pady=4)

        self.exit_btn = ttk.Button(left, text="Оформить выезд")
        self.exit_btn.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 2))

        right = ttk.LabelFrame(center, text="Активные талоны", padding=12)
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.tickets_tree = ttk.Treeview(
            right,
            columns=("id", "plate", "type", "spot", "floor", "allowed_until"),
            show="headings",
            height=14,
        )
        self.tickets_tree.grid(row=0, column=0, sticky="nsew")

        headings = [
            ("id", "ID"),
            ("plate", "Номер"),
            ("type", "Тип"),
            ("spot", "Место"),
            ("floor", "Этаж"),
            ("allowed_until", "Оплачено до"),
        ]
        for key, text in headings:
            self.tickets_tree.heading(key, text=text)

        self.tickets_tree.column("id", width=60, anchor="center")
        self.tickets_tree.column("plate", width=100, anchor="center")
        self.tickets_tree.column("type", width=90, anchor="center")
        self.tickets_tree.column("spot", width=80, anchor="center")
        self.tickets_tree.column("floor", width=70, anchor="center")
        self.tickets_tree.column("allowed_until", width=170, anchor="center")

        scrollbar = ttk.Scrollbar(right, orient="vertical", command=self.tickets_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tickets_tree.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.LabelFrame(self, text="Отчеты", padding=12)
        bottom.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))
        bottom.columnconfigure(0, weight=1)

        self.report_text = tk.Text(bottom, height=10, wrap="word")
        self.report_text.grid(row=0, column=0, sticky="nsew")

        self.refresh_btn = ttk.Button(bottom, text="Обновить дашборд и отчеты")
        self.refresh_btn.grid(row=1, column=0, sticky="ew", pady=(8, 0))

    def show_info(self, title, message):
        messagebox.showinfo(title, message)

    def show_error(self, title, message):
        messagebox.showerror(title, message)


class ParkingController:
    def __init__(self, model, view):
        self.model = model
        self.view = view

        self.view.park_btn.configure(command=self.on_park)
        self.view.exit_btn.configure(command=self.on_exit)
        self.view.refresh_btn.configure(command=self.refresh_all)

        self.refresh_all()
        self.view.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_park(self):
        try:
            plate = self.view.plate_entry.get()
            vehicle_type = self.view.vehicle_type_combo.get()
            hours = int(self.view.hours_entry.get().strip())
            ticket_id = self.model.park_vehicle(plate, vehicle_type, hours)
            self.view.show_info("Успех", f"Машина припаркована. Ticket ID: {ticket_id}")
            self.refresh_all()
        except Exception as exc:
            self.view.show_error("Ошибка ввода", str(exc))

    def on_exit(self):
        try:
            ticket_id = int(self.view.ticket_id_entry.get().strip())
            result = self.model.exit_vehicle(ticket_id)
            self.view.show_info(
                "Выезд оформлен",
                (
                    f"Ticket ID: {result['ticket_id']}\n"
                    f"Номер: {result['plate_number']}\n"
                    f"Время выезда: {result['exit_at']}\n"
                    f"К оплате: {result['amount']} сом"
                ),
            )
            self.refresh_all()
        except Exception as exc:
            self.view.show_error("Ошибка ввода", str(exc))

    def refresh_all(self):
        dashboard = self.model.get_dashboard()
        self.view.dashboard_var.set(
            (
                f"Всего мест: {dashboard['total_spots']} | "
                f"Свободно: {dashboard['free_spots']} | "
                f"Занято: {dashboard['occupied_spots']} | "
                f"Активных талонов: {dashboard['active_tickets']}"
            )
        )

        for row in self.view.tickets_tree.get_children():
            self.view.tickets_tree.delete(row)
        for t in self.model.get_active_tickets():
            self.view.tickets_tree.insert(
                "",
                "end",
                values=(
                    t["id"],
                    t["plate_number"],
                    t["vehicle_type"],
                    t["spot_code"],
                    t["floor_number"],
                    t["allowed_until"],
                ),
            )

        reports = self.model.build_reports()
        self.view.report_text.configure(state="normal")
        self.view.report_text.delete("1.0", "end")
        for title, data in reports.items():
            self.view.report_text.insert("end", f"{title}\n")
            if isinstance(data, (float, int)):
                self.view.report_text.insert("end", f"  Значение: {data}\n\n")
                continue
            if len(data) == 0:
                self.view.report_text.insert("end", "  Нет данных\n\n")
                continue
            for row in data:
                self.view.report_text.insert("end", f"  {dict(row)}\n")
            self.view.report_text.insert("end", "\n")
        self.view.report_text.configure(state="disabled")

    def on_close(self):
        self.model.close()
        self.view.destroy()


def main():
    db_file = Path(__file__).with_name("parking_management.db")
    model = ParkingModel(db_path=str(db_file))
    view = ParkingView()
    ParkingController(model, view)
    view.mainloop()


if __name__ == "__main__":
    main()
