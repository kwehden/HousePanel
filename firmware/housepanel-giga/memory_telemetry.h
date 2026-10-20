#pragma once
#include <stddef.h>
#include <stdint.h>

struct MemorySample {
    uint64_t uptime_ms;
    uint32_t heap_current, heap_peak, heap_reserved, alloc_count, alloc_failures;
    uint32_t stack_high_water, stack_reserved, stack_count, stack_min_free;
    uint32_t gui_used, gui_peak, gui_total, gui_largest_free;
    bool stack_complete;
};

// Formatting and cadence are shared with native regression tests.
size_t memory_format(char* buffer, size_t capacity, const char* boot_id, const MemorySample& s);
bool memory_due(uint64_t now, uint64_t last, bool first);
void memory_init();
size_t memory_collect(char* buffer, size_t capacity);
