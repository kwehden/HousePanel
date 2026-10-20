#pragma once
#include "Arduino.h"
namespace rtos { namespace Kernel { inline uint64_t get_ms_count() { return test_clock_ms; } } }
