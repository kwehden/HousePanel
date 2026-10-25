#pragma once
#include <stdint.h>

// Delivery/reconnect time is deliberately absent: replaying a cached reading
// must not extend its lifetime. Unknown or future source times are not live.
inline bool sensor_is_fresh(bool clock_ready, uint64_t now, uint64_t measured_at, uint64_t max_age = 300) {
  return clock_ready && measured_at > 0 && measured_at <= now && now - measured_at < max_age;
}
