import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from schemas.base import ShanghaiBaseModel


class _SampleModel(ShanghaiBaseModel):
    created_at: datetime


class TimezoneSerializationTest(unittest.TestCase):
    def test_naive_datetime_serializes_as_shanghai_iso(self) -> None:
        model = _SampleModel(created_at=datetime(2026, 5, 7, 6, 33, 26))
        payload = json.loads(model.model_dump_json())

        self.assertEqual(payload["created_at"], "2026-05-07T14:33:26+08:00")

    def test_aware_utc_datetime_serializes_as_shanghai_iso(self) -> None:
        model = _SampleModel(created_at=datetime(2026, 5, 7, 6, 33, 26, tzinfo=timezone.utc))
        payload = json.loads(model.model_dump_json())

        self.assertEqual(payload["created_at"], "2026-05-07T14:33:26+08:00")


if __name__ == "__main__":
    unittest.main()
