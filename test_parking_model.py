import tempfile
import unittest
from pathlib import Path

from parking_management_system import ParkingModel


class ParkingModelTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "test_parking.db"
        self.model = ParkingModel(db_path=str(db_path), base_price=50.0, overtime_fine=100.0)

    def tearDown(self):
        self.model.close()
        self.tmpdir.cleanup()

    def test_park_vehicle_creates_active_ticket(self):
        ticket_id = self.model.park_vehicle("01AA123A", "car", 2)
        active = self.model.get_active_tickets()
        self.assertTrue(ticket_id > 0)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["plate_number"], "01AA123A")

    def test_exit_vehicle_closes_ticket_and_frees_spot(self):
        ticket_id = self.model.park_vehicle("01BB999B", "motorbike", 1)
        result = self.model.exit_vehicle(ticket_id)
        self.assertEqual(result["ticket_id"], ticket_id)
        self.assertTrue(result["amount"] >= 50.0)
        self.assertEqual(len(self.model.get_active_tickets()), 0)

    def test_invalid_vehicle_type_raises_error(self):
        with self.assertRaises(ValueError):
            self.model.park_vehicle("01CC111C", "bus", 1)

    def test_invalid_hours_raises_error(self):
        with self.assertRaises(ValueError):
            self.model.park_vehicle("01DD222D", "car", 0)

    def test_reports_available(self):
        self.model.park_vehicle("01EE333E", "truck", 1)
        reports = self.model.build_reports()
        self.assertIn("1. Загрузка по этажам", reports)
        self.assertIn("5. Просроченные активные талоны", reports)
        self.assertIn("6. Средняя длительность (часы)", reports)


if __name__ == "__main__":
    unittest.main()
