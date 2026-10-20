#include "memory_telemetry.h"
#include <stdio.h>

bool memory_due(uint64_t now, uint64_t last, bool first) {
    return first || now - last >= 60000;
}

size_t memory_format(char* buffer, size_t capacity, const char* boot_id, const MemorySample& s) {
    int length = snprintf(buffer, capacity,
        "{\"cmd\":\"MEMORY\",\"version\":1,\"boot_id\":\"%s\",\"uptime_ms\":%llu,"
        "\"heap_current\":%lu,\"heap_peak\":%lu,\"heap_reserved\":%lu,"
        "\"alloc_count\":%lu,\"alloc_failures\":%lu,\"stack_high_water\":%lu,"
        "\"stack_reserved\":%lu,\"stack_count\":%lu,\"stack_min_free\":%lu,"
        "\"gui_used\":%lu,\"gui_peak\":%lu,\"gui_total\":%lu,\"gui_largest_free\":%lu,"
        "\"stack_complete\":%s}", boot_id, (unsigned long long)s.uptime_ms,
        (unsigned long)s.heap_current, (unsigned long)s.heap_peak, (unsigned long)s.heap_reserved,
        (unsigned long)s.alloc_count, (unsigned long)s.alloc_failures,
        (unsigned long)s.stack_high_water, (unsigned long)s.stack_reserved,
        (unsigned long)s.stack_count, (unsigned long)s.stack_min_free,
        (unsigned long)s.gui_used, (unsigned long)s.gui_peak,
        (unsigned long)s.gui_total, (unsigned long)s.gui_largest_free,
        s.stack_complete ? "true" : "false");
    if (length < 0 || (size_t)length >= capacity) return 0;
    return (size_t)length;
}
