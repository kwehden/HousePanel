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
inline bool arm_failure = false;
inline bool layout_ok = true, bootloader_capable = true, storage_ready = true, entropy_ok = true;
inline uint32_t millis() { return fake_ms; }
constexpr int WL_CONNECTED = 1;
struct FakeWifi { int status() { return wifi_up ? WL_CONNECTED : 0; } };
inline FakeWifi WiFi;
struct Link { std::vector<uint8_t> in, out; size_t cursor = 0; bool connected = true; };
inline std::deque<std::shared_ptr<Link>> pending;
class WiFiClient {
    std::shared_ptr<Link> link;
public:
    WiFiClient() = default;
    explicit WiFiClient(std::shared_ptr<Link> value) : link(value) {}
    explicit operator bool() const { return link && link->connected; }
    int available() { return link ? link->in.size() - link->cursor : 0; }
    int read() { return available() ? link->in[link->cursor++] : -1; }
    int read(uint8_t* out, size_t count) {
        count = std::min(count, static_cast<size_t>(available()));
        for (size_t i = 0; i < count; ++i) out[i] = link->in[link->cursor++];
        return count;
    }
    size_t write(const uint8_t* data, size_t count) { link->out.insert(link->out.end(), data, data + count); return count; }
    void setTimeout(unsigned) {}
    void stop() { if (link) link->connected = false; }
    bool connected() { return link && link->connected; }
};
class WiFiServer {
public:
    explicit WiFiServer(uint16_t) {}
    void begin() { ++listens; }
    void end() {}
    WiFiClient accept() {
        if (pending.empty()) return {};
        auto link = pending.front(); pending.pop_front(); return WiFiClient(link);
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
