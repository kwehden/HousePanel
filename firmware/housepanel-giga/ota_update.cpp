#include "ota_update.h"
#include "ota_protocol.h"
#include "config.h"
#include <Arduino_Portenta_OTA.h>
#include <WiFi.h>
#include <hal/trng_api.h>
#include <mbed.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

#if __has_include("ota_secrets.h")
#include "ota_secrets.h"
#endif
#ifndef HOUSEPANEL_OTA_KEY_HEX
#define HOUSEPANEL_OTA_KEY_HEX ""
#endif
#ifndef HOUSEPANEL_FIRMWARE_REVISION
#define HOUSEPANEL_FIRMWARE_REVISION "development"
#endif

namespace {
// Mount once per boot. The upstream begin() owns lifetime allocations, so never
// repeat it per request or on failure; never format storage from a running panel.
Arduino_Portenta_OTA_QSPI updater(QSPI_FLASH_FATFS_MBR, 2);
WiFiServer server(OTA_PORT);
WiFiClient peer;
OtaReceiver receiver;
constexpr char identity[] = "HousePanel identity:" HOUSEPANEL_PANEL_ID ":" HOUSEPANEL_HOSTNAME ":end";
uint8_t header[OTA_HEADER_SIZE], buffer[1024], nonce[32];
char boot_id[33] = {}, nonce_hex[65] = {};
size_t header_size = 0;
bool ready = false, listening = false, active = false, receiving = false, nonce_valid = false;
bool querying = false;
uint32_t connected_at = 0, progress_at = 0, challenge_at = 0;
const char* reason = "not_initialized";

bool random_bytes(uint8_t* out, size_t size) {
    trng_t trng;
    size_t actual = 0;
    trng_init(&trng);
    int result = trng_get_bytes(&trng, out, size, &actual);
    trng_free(&trng);
    if (result != 0 || actual != size) return false;
    uint8_t any = 0;
    for (size_t i = 0; i < size; ++i) any |= out[i];
    return any != 0;
}
void to_hex(const uint8_t* data, size_t size, char* out) {
    constexpr char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < size; ++i) {
        out[2 * i] = digits[data[i] >> 4];
        out[2 * i + 1] = digits[data[i] & 15];
    }
    out[2 * size] = 0;
}
class FileSink final : public OtaSink {
    FILE* file = nullptr;
public:
    bool begin() override {
        file = fopen("/fs/UPDATE.PART", "wb");
        return file != nullptr;
    }
    bool write(const uint8_t* data, size_t size) override {
        return file && fwrite(data, 1, size, file) == size;
    }
    bool finish() override {
        if (!file) return false;
        bool flushed = fflush(file) == 0;
        bool closed = fclose(file) == 0;
        file = nullptr;
        if (!flushed || !closed) return false;
        // FAT rename does not replace an existing target. Only remove the old
        // staged file after the new image has passed authentication/digest checks.
        if (remove("/fs/UPDATE.BIN") != 0 && errno != ENOENT) return false;
        return rename("/fs/UPDATE.PART", "/fs/UPDATE.BIN") == 0;
    }
    void abort() override {
        if (file) fclose(file);
        file = nullptr;
        remove("/fs/UPDATE.PART");
    }
} sink;
void close_peer() {
    receiver.abort();
    peer.stop();
    active = receiving = querying = false;
    header_size = 0;
}
void reply(const char* text) {
    peer.write(reinterpret_cast<const uint8_t*>(text), strlen(text));
}
void status() {
    nonce_valid = ready && random_bytes(nonce, sizeof(nonce));
    if (nonce_valid) {
        to_hex(nonce, sizeof(nonce), nonce_hex);
        receiver.challenge(nonce);
        challenge_at = millis();
    } else nonce_hex[0] = 0;
    char response[512];
    char request_nonce[65];
    to_hex(header + 8, 32, request_nonce);
    snprintf(response, sizeof(response),
             "{\"protocol\":1,\"panel_id\":\"%s\",\"hostname\":\"%s\",\"firmware\":\"%s\","
             "\"revision\":\"%s\",\"identity\":\"%s\",\"boot_id\":\"%s\",\"ready\":%s,"
             "\"reason\":\"%s\",\"challenge\":\"%s\",\"request_nonce\":\"%s\"}\n",
             HOUSEPANEL_PANEL_ID, HOUSEPANEL_HOSTNAME, FIRMWARE_VERSION,
             HOUSEPANEL_FIRMWARE_REVISION, identity, boot_id, nonce_valid ? "true" : "false", reason, nonce_hex, request_nonce);
    uint8_t tag[32];
    char tag_hex[66];
    if (receiver.sign(reinterpret_cast<const uint8_t*>(response), strlen(response), tag)) {
        to_hex(tag, sizeof(tag), tag_hex);
        strcat(tag_hex, "\n");
        reply(response);
        reply(tag_hex);
    }
    close_peer();
}
}

void ota_init() {
    uint8_t boot[16];
    uint8_t panel = strcmp(HOUSEPANEL_PANEL_ID, "primary") == 0 ? 1 :
                    strcmp(HOUSEPANEL_PANEL_ID, "panel-2") == 0 ? 2 : 0;
    if (!receiver.configure(HOUSEPANEL_OTA_KEY_HEX, panel, identity)) { reason = "key_not_provisioned"; return; }
    if (!random_bytes(boot, sizeof(boot))) { reason = "entropy_unavailable"; return; }
    to_hex(boot, sizeof(boot), boot_id);
    updater.setFeedWatchdogFunc([] { mbed::Watchdog::get_instance().kick(); });
    if (!updater.isOtaCapable()) { reason = "bootloader_not_ota_capable"; return; }
    mbed::MBRBlockDevice partition(mbed::BlockDevice::get_default_instance(), 2);
    if (partition.init() != 0) { reason = "partition_not_ready"; return; }
    bool layout_ok = partition.get_partition_start() == 1024 * 1024 &&
                     partition.get_partition_stop() == 6 * 1024 * 1024 && partition.get_partition_type() == 0x0b;
    partition.deinit();
    if (!layout_ok) { reason = "partition_layout_mismatch"; return; }
    if (updater.begin() != Arduino_Portenta_OTA::Error::None) { reason = "storage_not_ready"; return; }
    ready = true;
    reason = "ready";
}

void ota_loop() {
    if (!ready) return;
    if (WiFi.status() != WL_CONNECTED) {
        if (active) close_peer();
        if (listening) server.end();
        listening = false;
        return;
    }
    if (!listening) { server.begin(); listening = true; }
    if (!active) {
        peer = server.accept();
        if (!peer) return;
        peer.setTimeout(1000);
        active = true;
        connected_at = progress_at = millis();
    }
    uint32_t now = millis();
    if ((now - connected_at) > 180000 || (now - progress_at) > 5000) { close_peer(); return; }
    // One bounded chunk per UI loop. Idle/partial clients cannot stall the display.
    size_t budget = sizeof(buffer);
    while (!receiving && peer.available() > 0 && budget--) {
        int value = peer.read();
        if (value < 0) { close_peer(); return; }
        header[header_size++] = static_cast<uint8_t>(value);
        progress_at = now;
        if (header_size == 8) {
            querying = memcmp(header, "HPOTA1S\n", 8) == 0;
            if (!querying && memcmp(header, "HPOTA1U\n", 8) != 0) { close_peer(); return; }
        }
        if (querying && header_size == 40) { status(); return; }
        if (header_size == OTA_HEADER_SIZE) {
            if (!nonce_valid || (now - challenge_at) > 60000 || !receiver.begin(header, sink)) {
                reply("{\"ok\":false}\n"); close_peer(); return;
            }
            nonce_valid = false;
            receiving = true;
            reply("{\"accepted\":true}\n");
        }
    }
    if (receiving && peer.available() > 0) {
        int available = peer.available();
        size_t count = static_cast<size_t>(available) < sizeof(buffer) ? static_cast<size_t>(available) : sizeof(buffer);
        int actual = peer.read(buffer, count);
        if (actual <= 0 || !receiver.feed(buffer, static_cast<size_t>(actual))) {
            reply("{\"ok\":false}\n"); close_peer(); return;
        }
        progress_at = now;
        if (receiver.complete()) {
            bool armed = updater.update() == Arduino_Portenta_OTA::Error::None;
            reply(armed ? "{\"ok\":true}\n" : "{\"ok\":false}\n");
            close_peer();
            if (armed) updater.reset();
        }
    }
    if (active && !peer.connected() && peer.available() == 0) close_peer();
}
