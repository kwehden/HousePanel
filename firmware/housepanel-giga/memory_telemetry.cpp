#include "memory_telemetry.h"
#include <mbed.h>
#include "platform/mbed_stats.h"
#include "hal/trng_api.h"
#include "cmsis_os2.h"
#include <stdio.h>
#include "Arduino_H7_Video.h"
#include "lvgl.h"

#if !MBED_HEAP_STATS_ENABLED || !MBED_STACK_STATS_ENABLED || !OS_STACK_WATERMARK
#error Memory telemetry requires heap statistics and RTOS stack watermarking
#endif
#if LV_USE_STDLIB_MALLOC != LV_STDLIB_BUILTIN
#error GUI telemetry requires the LVGL built-in allocator monitor
#endif

static char boot_id[17];
static bool initialized = false;
static osThreadId_t threads[32];

void memory_init() {
    trng_t rng;
    uint32_t words[2] = {};
    size_t produced = 0;
    trng_init(&rng);
    int result = trng_get_bytes(&rng, (uint8_t*)words, sizeof(words), &produced);
    trng_free(&rng);
    initialized = result == 0 && produced == sizeof(words);
    if (initialized) {
        snprintf(boot_id, sizeof(boot_id), "%08lx%08lx",
                 (unsigned long)words[0], (unsigned long)words[1]);
    }
}

size_t memory_collect(char* buffer, size_t capacity) {
    if (!initialized) return 0;
    MemorySample sample = {};
    sample.uptime_ms = rtos::Kernel::get_ms_count();
    mbed_stats_heap_t heap = {};
    mbed_stats_heap_get(&heap);
    sample.heap_current = heap.current_size;
    sample.heap_peak = heap.max_size;
    sample.heap_reserved = heap.reserved_size;
    sample.alloc_count = heap.alloc_cnt;
    sample.alloc_failures = heap.alloc_fail_cnt;
    // Mbed's convenience stack sampler mallocs. Enumerate into fixed storage
    // instead, and never present a truncated thread set as a complete sample.
    int32_t lock = osKernelLock();
    if (lock < 0) return 0;
    uint32_t count = osThreadGetCount();
    sample.stack_count = osThreadEnumerate(threads, 32);
    sample.stack_complete = count <= 32 && sample.stack_count == count;
    sample.stack_min_free = UINT32_MAX;
    for (uint32_t i = 0; i < sample.stack_count; ++i) {
        uint32_t reserved = osThreadGetStackSize(threads[i]);
        uint32_t free = osThreadGetStackSpace(threads[i]);
        sample.stack_reserved += reserved;
        sample.stack_high_water += reserved - free;
        if (free < sample.stack_min_free) sample.stack_min_free = free;
    }
    osKernelRestoreLock(lock);
    if (sample.stack_count == 0) sample.stack_min_free = 0;
    lv_mem_monitor_t gui = {};
    lv_mem_monitor(&gui);
    sample.gui_used = gui.total_size - gui.free_size;
    // LVGL 9.5.0 max_used is bytes; used_pct is the separate percentage field.
    sample.gui_peak = gui.max_used;
    // Monitor total_size excludes allocator block headers and varies with
    // fragmentation. Peak usage is bounded by the configured fixed capacity.
    sample.gui_total = LV_MEM_SIZE;
    sample.gui_largest_free = gui.free_biggest_size;
    return memory_format(buffer, capacity, boot_id, sample);
}
