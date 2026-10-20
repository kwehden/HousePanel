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
#include <TCPSocket.h>
#include <memory>

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
TCPSocket server;
// Core 4.5.0's WiFiClient closes but does not delete accepted sockets. Own the
// raw accepted Mbed socket explicitly; also avoid its per-connection reader task.
std::unique_ptr<TCPSocket> peer;
OtaReceiver receiver;
constexpr char identity[] = "HousePanel identity:" HOUSEPANEL_PANEL_ID ":" HOUSEPANEL_HOSTNAME ":end";
uint8_t header[OTA_HEADER_SIZE], buffer[1024], nonce[32];
char boot_id[33] = {}, nonce_hex[65] = {};
size_t header_size = 0;
bool ready = false, listening = false, receiving = false, nonce_valid = false;
bool querying = false;
uint32_t connected_at = 0, progress_at = 0, challenge_at = 0;
uint32_t listen_attempt_at = 0;
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
    if (peer) peer->close();
    peer.reset();
    receiving = querying = false;
    header_size = 0;
}
void reply(const char* text) {
    peer->set_timeout(1000);
    peer->send(text, strlen(text));
    peer->set_blocking(false);
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
        if (peer) close_peer();
        if (listening) server.close();
        listening = false;
        return;
    }
    if (!listening) {
        if (listen_attempt_at && (millis() - listen_attempt_at) < 5000) return;
        listen_attempt_at = millis();
        if (server.open(WiFi.getNetwork()) != NSAPI_ERROR_OK) { server.close(); return; }
        int reuse = 1;
        server.setsockopt(NSAPI_SOCKET, NSAPI_REUSEADDR, &reuse, sizeof(reuse));
        server.set_blocking(false);
        if (server.bind(OTA_PORT) != NSAPI_ERROR_OK || server.listen(1) != NSAPI_ERROR_OK) { server.close(); return; }
        listening = true;
    }
    if (!peer) {
        nsapi_error_t error = NSAPI_ERROR_OK;
        peer.reset(server.accept(&error));
        if (error != NSAPI_ERROR_OK || !peer) {
            close_peer();
            if (error != NSAPI_ERROR_WOULD_BLOCK) { server.close(); listening = false; }
            return;
        }
        peer->set_blocking(false);
        connected_at = progress_at = millis();
    }
    uint32_t now = millis();
    if ((now - connected_at) > 180000 || (now - progress_at) > 5000) { close_peer(); return; }
    // One bounded chunk per UI loop. Idle/partial clients cannot stall the display.
    int actual = peer->recv(buffer, sizeof(buffer));
    if (actual == NSAPI_ERROR_WOULD_BLOCK) return;
    if (actual <= 0) { close_peer(); return; }
    progress_at = now;
    size_t used = 0;
    while (!receiving && used < static_cast<size_t>(actual)) {
        header[header_size++] = buffer[used++];
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
    if (receiving && used < static_cast<size_t>(actual)) {
        if (!receiver.feed(buffer + used, static_cast<size_t>(actual) - used)) {
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
}
