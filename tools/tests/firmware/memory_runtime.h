#pragma once
#include <stddef.h>
#include <stdint.h>
#define MBED_HEAP_STATS_ENABLED 1
#define MBED_STACK_STATS_ENABLED 1
#define OS_STACK_WATERMARK 1
#define LV_STDLIB_BUILTIN 1
#define LV_USE_STDLIB_MALLOC 1
#define LV_MEM_SIZE 131072
using osThreadId_t = void*;
struct trng_t {};
extern bool rng_ok;
extern int32_t lock_result;
extern unsigned thread_count, restores;
inline void trng_init(trng_t*) {}
inline void trng_free(trng_t*) {}
inline int trng_get_bytes(trng_t*, uint8_t* bytes, size_t length, size_t* produced) {
    for (size_t i = 0; i < length; ++i) bytes[i] = (uint8_t)i;
    *produced = rng_ok ? length : 0;
    return rng_ok ? 0 : -1;
}
namespace rtos { namespace Kernel { inline uint64_t get_ms_count() { return 60000; } } }
struct mbed_stats_heap_t {
    uint32_t current_size, max_size, total_size, reserved_size, alloc_cnt, alloc_fail_cnt, overhead_size;
};
inline void mbed_stats_heap_get(mbed_stats_heap_t* s) { *s = {1000, 2000, 0, 3000, 20, 0, 0}; }
inline int32_t osKernelLock() { return lock_result; }
inline int32_t osKernelRestoreLock(int32_t lock) { ++restores; return lock; }
inline uint32_t osThreadGetCount() { return thread_count; }
inline uint32_t osThreadEnumerate(osThreadId_t* threads, uint32_t count) {
    unsigned n = thread_count < count ? thread_count : count;
    for (unsigned i = 0; i < n; ++i) threads[i] = nullptr;
    return n;
}
inline uint32_t osThreadGetStackSize(osThreadId_t) { return 1024; }
inline uint32_t osThreadGetStackSpace(osThreadId_t) { return 256; }
// Match the pinned LVGL v9.5.0 lv_mem.h layout and units, including separate percentages.
struct lv_mem_monitor_t {
    size_t total_size, free_cnt, free_size, free_biggest_size, used_cnt, max_used;
    uint8_t used_pct, frag_pct;
};
inline void lv_mem_monitor(lv_mem_monitor_t* s) { *s = {130000, 2, 100000, 90000, 4, 40000, 24, 10}; }
