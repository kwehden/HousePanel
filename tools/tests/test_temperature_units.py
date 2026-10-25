"""Exercise the firmware's actual conversion, hit area, and touch latch."""
from pathlib import Path
import subprocess


def test_temperature_units_and_touch_reports(tmp_path):
    root = Path(__file__).resolve().parents[2]
    binary = tmp_path / "temperature-units"
    subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
        "-fno-sanitize-recover=all", "-I", str(root / "firmware/giga-filament"),
        "-x", "c++", "-", "-o", str(binary),
    ], input='''#include "temperature_units.h"
#include <cassert>
#include <cmath>
int main() {
  TemperatureUnits units;
  assert(units.symbol() == 'C' && units.value(11.0f) == 11.0f);
  // Clock and date do not toggle, including a drag into the sensor region.
  assert(!units.report(true, 400, 100));
  assert(!units.report(true, 400, 250));
  units.report(false, -1, -1);
  assert(units.report(true, 210, 250));
  assert(units.symbol() == 'F');
  assert(std::fabs(units.value(11.0f) - 51.8f) < 0.001f);
  assert(std::fabs(units.value(24.4f) - 75.92f) < 0.001f);
  assert(units.value(0) == 32 && units.value(100) == 212 && units.value(-40) == -40);
  // A long press or moving finger stays one gesture. No-data polls must not
  // invoke report(false); only an actual controller release rearms the toggle.
  for (int i = 0; i < 100; ++i) assert(!units.report(true, 590, 370));
  assert(units.symbol() == 'F');
  units.report(false, -1, -1);
  assert(units.report(true, 590, 370));
  assert(units.symbol() == 'C' && units.value(11.0f) == 11.0f);
  units.report(false, -1, -1);
  assert(!units.report(true, 400, 440));
  units.report(false, -1, -1);
  assert(!units.report(true, 800, 250));
  units.report(false, -1, -1);
  assert(!units.report(true, 0, 174));
  units.report(false, -1, -1);
  assert(units.report(true, 0, 175));
  int x, y;
  touch_landscape(0, 0, true, x, y); assert(x == 0 && y == 479);
  touch_landscape(479, 799, true, x, y); assert(x == 799 && y == 0);
  touch_landscape(210, 250, false, x, y); assert(x == 210 && y == 250);
}
''', text=True, check=True)
    subprocess.run([binary], check=True)
