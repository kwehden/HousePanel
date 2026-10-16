import json
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(sys.implementation.name == "cpython" and sys.version_info[:2] == (3, 12),
                     "Version-specific reproducer; run in the deployed Python 3.12 image")
class CalendarCacheProbeTests(unittest.TestCase):
    def run_probe(self, *args):
        script = Path(__file__).resolve().parents[1] / "calendar_cache_probe.py"
        result = subprocess.run([sys.executable, str(script), "--iterations", "10000", *args],
                                check=True, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)["samples"]

    def test_datetime_cache_retention_is_bounded_and_released_by_cache_clear(self):
        samples = self.run_probe()
        before, after = samples[-2:]
        # A future 3.12 patch may eliminate this cache population entirely.
        self.assertLessEqual(before["allocation_count"], 4096)
        self.assertEqual(after["allocation_count"], 0)

    def test_real_retained_objects_survive_gc_and_cache_clear(self):
        samples = self.run_probe("--retain-control")
        for sample in samples:
            self.assertGreaterEqual(sample["allocation_count"], sample["cycle"])
        self.assertGreater(samples[-2]["allocation_bytes"], samples[0]["allocation_bytes"])
        self.assertEqual(samples[-1]["allocation_count"], samples[-1]["cycle"])
        self.assertLessEqual(samples[-1]["allocation_bytes"], samples[-2]["allocation_bytes"])
