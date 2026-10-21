#pragma once
#include <algorithm>
#include <deque>
#include <memory>
#include <stdint.h>
#include <vector>

inline uint32_t fake_ms = 0;
inline bool wifi_up = true;
inline unsigned entropy_counter = 0;
inline int mounts = 0, arms = 0, resets = 0, listens = 0;
inline int sockets_live = 0;
inline unsigned send_calls_total = 0;
inline bool arm_failure = false;
inline bool layout_ok = true, bootloader_capable = true, storage_ready = true, entropy_ok = true;
inline uint32_t millis() { return fake_ms; }
constexpr int WL_CONNECTED = 1;
struct FakeWifi { int status() { return wifi_up ? WL_CONNECTED : 0; } void* getNetwork() { return nullptr; } };
inline FakeWifi WiFi;
struct Link {
    std::vector<uint8_t> in, out;
    size_t cursor = 0, max_send = 640;
    std::deque<int> send_results;
    bool connected = true, stall_send = false;
    int send_calls = 0;
};
inline std::deque<std::shared_ptr<Link>> pending;
using nsapi_error_t = int;
constexpr int NSAPI_ERROR_OK = 0, NSAPI_ERROR_WOULD_BLOCK = -3001, NSAPI_SOCKET = 1, NSAPI_REUSEADDR = 2;
class TCPSocket {
    std::shared_ptr<Link> link;
public:
    TCPSocket() = default;
    explicit TCPSocket(std::shared_ptr<Link> value) : link(value) { ++sockets_live; }
    ~TCPSocket() { if (link) --sockets_live; }
    int recv(void* destination, size_t count) {
        auto out = static_cast<uint8_t*>(destination);
        count = std::min(count, link->in.size() - link->cursor);
        if (!count) return link->connected ? NSAPI_ERROR_WOULD_BLOCK : 0;
        for (size_t i = 0; i < count; ++i) out[i] = link->in[link->cursor++];
        return count;
    }
    int send(const void* source, size_t count) {
        ++send_calls_total;
        ++link->send_calls;
        if (link->stall_send) return NSAPI_ERROR_WOULD_BLOCK;
        if (!link->send_results.empty()) {
            int result = link->send_results.front(); link->send_results.pop_front();
            if (result <= 0) return result;
            count = std::min(count, static_cast<size_t>(result));
        }
        count = std::min(count, link->max_send);
        auto data = static_cast<const uint8_t*>(source);
        link->out.insert(link->out.end(), data, data + count); return count;
    }
    void set_timeout(unsigned) {}
    void set_blocking(bool) {}
    int close() { if (link) link->connected = false; return 0; }
    int open(void*) { return 0; }
    void setsockopt(int, int, void*, size_t) {}
    int bind(uint16_t) { return 0; }
    int listen(int) { ++listens; return 0; }
    TCPSocket* accept(int* error) {
        if (pending.empty()) { *error = NSAPI_ERROR_WOULD_BLOCK; return nullptr; }
        auto link = pending.front(); pending.pop_front(); *error = 0; return new TCPSocket(link);
    }
};
constexpr int QSPI_FLASH_FATFS_MBR = 0;
class Arduino_Portenta_OTA {
public:
    enum class Error { None, Failure };
};
class Arduino_Portenta_OTA_QSPI : public Arduino_Portenta_OTA {
public:
    Arduino_Portenta_OTA_QSPI(int, int) {}
    void setFeedWatchdogFunc(void (*)()) {}
    bool isOtaCapable() { return bootloader_capable; }
    Error begin() { ++mounts; return storage_ready ? Error::None : Error::Failure; }
    Error update() { ++arms; return arm_failure ? Error::Failure : Error::None; }
    void reset() { ++resets; }
};
namespace mbed {
class BlockDevice {
public:
    static BlockDevice* get_default_instance() { static BlockDevice device; return &device; }
};
class MBRBlockDevice {
public:
    MBRBlockDevice(BlockDevice*, int) {}
    int init() { return 0; }
    void deinit() {}
    unsigned get_partition_start() { return layout_ok ? 1024 * 1024 : 2 * 1024 * 1024; }
    unsigned get_partition_stop() { return 6 * 1024 * 1024; }
    unsigned get_partition_type() { return 0x0b; }
};
class Watchdog {
public:
    static Watchdog& get_instance() { static Watchdog value; return value; }
    void kick() {}
};
}
struct trng_t {};
inline void trng_init(trng_t*) {}
inline void trng_free(trng_t*) {}
inline int trng_get_bytes(trng_t*, uint8_t* out, size_t size, size_t* actual) {
    if (!entropy_ok) { *actual = 0; return -1; }
    for (size_t i = 0; i < size; ++i) out[i] = entropy_counter++;
    *actual = size;
    return 0;
}
