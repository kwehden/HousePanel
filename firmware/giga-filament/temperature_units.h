#pragma once
#include <stdint.h>

struct TemperatureUnits {
  bool fahrenheit = false;
  bool pressed = false;

  float value(float celsius) const { return fahrenheit ? celsius * 1.8f + 32.0f : celsius; }
  char symbol() const { return fahrenheit ? 'F' : 'C'; }

  // Call only for a new controller report. No-data polls are not releases.
  bool report(bool contact, int x, int y) {
    if (!contact) { pressed = false; return false; }
    if (pressed) return false;
    pressed = true;
    if (x < 0 || x >= 800 || y < 175 || y >= 425) return false;
    fahrenheit = !fahrenheit;
    return true;
  }
};

inline void touch_landscape(uint16_t raw_x, uint16_t raw_y, bool portrait, int& x, int& y) {
  // Inverse of Arduino_H7_Video::set() for its rotated 800x480 framebuffer.
  x = portrait ? raw_y : raw_x;
  y = portrait ? 479 - int(raw_x) : raw_y;
}
