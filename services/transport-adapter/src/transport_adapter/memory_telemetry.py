"""Bounded, strict firmware memory snapshots; identity comes from the socket."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

U32 = Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)]


class MemorySample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cmd: Literal["MEMORY"]
    version: Annotated[int, Field(ge=1, le=1)]
    boot_id: Annotated[str, Field(min_length=16, max_length=16, pattern=r"^[0-9a-f]{16}$")]
    uptime_ms: Annotated[int, Field(ge=0, le=2**63 - 1)]
    heap_current: U32
    heap_peak: U32
    heap_reserved: U32
    alloc_count: U32
    alloc_failures: U32
    stack_high_water: U32
    stack_reserved: U32
    stack_count: Annotated[int, Field(ge=0, le=32)]
    stack_min_free: U32
    stack_complete: bool
    gui_used: U32
    gui_peak: U32
    gui_total: U32
    gui_largest_free: U32

    @model_validator(mode="after")
    def consistent(self) -> "MemorySample":
        if self.heap_current > self.heap_peak:
            raise ValueError("current heap exceeds high-water mark")
        if self.heap_current > self.heap_reserved:
            raise ValueError("current heap exceeds reservation")
        if self.stack_high_water > self.stack_reserved or self.stack_min_free > self.stack_reserved - self.stack_high_water:
            raise ValueError("stack statistics exceed reservation")
        if self.stack_complete and self.stack_count == 0:
            raise ValueError("complete stack sample must contain threads")
        if self.gui_used > self.gui_total or self.gui_largest_free > self.gui_total - self.gui_used:
            raise ValueError("GUI statistics exceed pool capacity")
        if not self.gui_used <= self.gui_peak <= self.gui_total:
            raise ValueError("GUI peak must be between usage and fixed pool capacity")
        return self


# Export only fixed fields with fixed panel labels, never boot IDs/thread names.
MEMORY_METRICS = {
    "heap_current": ("heap_allocated_bytes", "Current tracked Mbed heap allocations, not whole-board RAM."),
    "heap_peak": ("heap_peak_bytes", "Peak tracked heap bytes since board boot."),
    "heap_reserved": ("heap_reserved_bytes", "Bytes reserved by the Mbed heap allocator, not free board RAM."),
    "alloc_count": ("heap_allocations", "Outstanding tracked heap allocations."),
    "alloc_failures": ("heap_allocation_failures", "Failed tracked allocations since board boot; resets on reboot."),
    "stack_high_water": ("stack_high_water_bytes", "Sum of RTOS thread stack high-water usage, not current stack usage."),
    "stack_reserved": ("stack_reserved_bytes", "Sum of reserved RTOS thread stack bytes."),
    "stack_count": ("stack_threads", "Number of RTOS stacks sampled."),
    "stack_min_free": ("stack_min_free_bytes", "Smallest remaining high-water headroom among sampled RTOS threads."),
    "gui_used": ("gui_allocated_bytes", "LVGL built-in display pool bytes currently used, separate from Mbed heap."),
    "gui_peak": ("gui_peak_bytes", "Peak LVGL built-in display pool usage."),
    "gui_total": ("gui_pool_bytes", "LVGL built-in display pool capacity."),
    "gui_largest_free": ("gui_largest_free_bytes", "Largest contiguous free block in the LVGL display pool."),
}
