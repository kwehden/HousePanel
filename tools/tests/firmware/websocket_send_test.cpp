#include "ws_client.h"
#include "memory_telemetry.h"
#include <cassert>
#include <iostream>
#include <string>

static bool maximal = false;
static unsigned samples = 0;
void memory_init() {}
size_t memory_collect(char* buffer, size_t capacity) {
    ++samples;
    MemorySample s = {};
    s.uptime_ms = test_clock_ms;
    s.heap_current = 1000; s.heap_peak = 2000; s.heap_reserved = 3000;
    s.alloc_count = 20; s.stack_high_water = 800; s.stack_reserved = 2000;
    s.stack_count = 3; s.stack_min_free = 200; s.stack_complete = true;
    s.gui_used = 100; s.gui_peak = 120; s.gui_total = 131072; s.gui_largest_free = 500;
    if (maximal) {
        s.uptime_ms = INT64_MAX;
        s.heap_current = s.heap_peak = s.heap_reserved = s.alloc_count = s.alloc_failures = UINT32_MAX;
        s.stack_high_water = s.stack_reserved = UINT32_MAX; s.stack_min_free = 0;
        s.stack_count = 32;
        s.gui_used = s.gui_peak = s.gui_total = UINT32_MAX; s.gui_largest_free = 0;
    }
    return memory_format(buffer, capacity, "0123456789abcdef", s);
}
bool parse_command_frame(const char*, CommandFrame&) { return false; }

static void emit(const char* name, const std::vector<uint8_t>& wire) {
    std::cout << name << " ";
    const char* digits = "0123456789abcdef";
    for (uint8_t c : wire) std::cout << digits[c >> 4] << digits[c & 15];
    std::cout << "\n";
}

int main() {
    CheckedWiFiClient& network = static_cast<CheckedWiFiClient&>(*WiFiClient::instance);
    ws_init();
    assert(ws_connect());  // Real upstream HTTP upgrade response parser.
    network.tx.clear();
    ws_send_hello(false);
    emit("hello", network.tx);
    network.tx.clear();
    ws_send_memory();
    emit("normal", network.tx);
    assert(samples == 1);
    network.tx.clear();
    test_clock_ms = 59999;
    ws_send_memory();
    assert(samples == 1 && network.tx.empty());
    test_clock_ms = 60000;
    maximal = true;
    ws_send_memory();
    emit("maximal", network.tx);
    assert(samples == 2);

    // The real endMessage observes a partial hardware write. No silent success.
    network.tx.clear();
    network.short_bulk_write = true;
    test_clock_ms = 120000;
    unsigned stops = network.stops;
    ws_send_memory();
    assert(!ws_connected() && network.stops == stops + 1);
    samples = 0;
    network.tx.clear();
    ws_send_memory();
    assert(samples == 0 && network.tx.empty());
    network.short_bulk_write = false;
    maximal = false;
    assert(ws_connect());
    network.tx.clear();
    ws_send_hello(false);
    ws_send_memory();  // Immediate retry after reconnect despite cadence.
    emit("reconnected", network.tx);
    assert(samples == 1);

    // Extended-size telemetry writes: opcode, length marker, two length bytes,
    // mask, payload. Fail each independently, including headers the library ignores.
    for (int position = 0; position < 6; ++position) {
        char frame[300];
        memset(frame, 'x', sizeof(frame));
        WebSocketClient client(network, "test", 80);
        // Establish a separate real upgraded session before injecting TX failure.
        network.stop();
        network.fail_write_at = -1;
        assert(client.begin("/test") == 0);
        network.frame_write_count = 0;
        network.fail_write_at = position;
        assert(!ws_send_text(client, network, frame, sizeof(frame)));
        assert(network.write_failed() && !network.alive);
    }
    network.fail_write_at = -1;
    assert(ws_connect());
    network.tx.clear();
    ws_send_hello(false);
    ws_send_memory();
    assert(ws_connected());
    emit("after_header_failures", network.tx);

    // Guard the dependency overflow and busy-TX error paths using a real client.
    network.stop();
    WebSocketClient client(network, "test", 80);
    assert(client.begin("/test") == 0);
    network.tx.clear();
    char boundary[WS_TX_BUFFER_SIZE + 1] = {};
    memset(boundary, 'x', sizeof(boundary));
    assert(!ws_send_text(client, network, boundary, 0));
    assert(!ws_send_text(client, network, boundary, sizeof(boundary)));
    assert(network.tx.empty());
    assert(ws_send_text(client, network, boundary, WS_TX_BUFFER_SIZE));
    emit("exact_capacity", network.tx);
    network.tx.clear();
    assert(client.beginMessage(TYPE_TEXT) == 0);
    assert(!ws_send_text(client, network, "{}", 2));
    assert(!network.alive && network.tx.empty());
    ws_force_reconnect();
}
