#include "memory_runtime.h"
#include "memory_telemetry.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

bool rng_ok = true;
int32_t lock_result = 0;
unsigned thread_count = 3, restores = 0;

int main(int argc, char**) {
    char buffer[768];
    assert(memory_collect(buffer, sizeof(buffer)) == 0);
    rng_ok = false;
    memory_init();
    assert(memory_collect(buffer, sizeof(buffer)) == 0);
    rng_ok = true;
    memory_init();
    lock_result = -1;
    assert(memory_collect(buffer, sizeof(buffer)) == 0);
    assert(restores == 0);
    lock_result = 0;
    assert(memory_collect(buffer, sizeof(buffer)) > 0);
    assert(restores == 1);
    if (argc == 1) {
        puts(buffer);
        thread_count = 33;
        assert(memory_collect(buffer, sizeof(buffer)) > 0);
        puts(buffer);
        thread_count = 0;
        assert(memory_collect(buffer, sizeof(buffer)) > 0);
        puts(buffer);
    }
    assert(memory_due(0, 0, true));
    assert(!memory_due(59999, 0, false));
    assert(memory_due(60000, 0, false));
    assert(memory_due(UINT64_C(4294967300), UINT64_C(4294907300), false));
    assert(!memory_due(UINT64_C(4294967300), UINT64_C(4294967290), false));
    MemorySample s = {};
    s.uptime_ms = INT64_MAX;
    s.heap_current = s.heap_peak = s.heap_reserved = s.alloc_count = s.alloc_failures = UINT32_MAX;
    s.stack_high_water = s.stack_reserved = UINT32_MAX;
    s.stack_min_free = 0;
    s.stack_count = 32;
    s.stack_complete = true;
    s.gui_used = s.gui_peak = s.gui_total = UINT32_MAX;
    s.gui_largest_free = 0;
    size_t length = memory_format(buffer, sizeof(buffer), "0123456789abcdef", s);
    assert(length > 0 && length < sizeof(buffer));
    if (argc == 1) puts(buffer);
    char exact[768];
    assert(memory_format(exact, length + 1, "0123456789abcdef", s) == length);
    assert(memory_format(exact, length, "0123456789abcdef", s) == 0);
    assert(memory_format(exact, 1, "0123456789abcdef", s) == 0);
    for (int i = 0; i < 10000; ++i) {
        assert(memory_format(buffer, sizeof(buffer), "0123456789abcdef", s) == length);
    }
}
