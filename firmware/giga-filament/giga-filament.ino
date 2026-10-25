// Primary-only minimal display. Build with private secrets.h in a staging directory.
#include <ArduinoGraphics.h>
#include <Arduino_H7_Video.h>
#include <ArduinoHttpClient.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <mbed.h>
#include <USB/PluggableUSBSerial.h>
#include <math.h>
#include <new>
#include <time.h>
#include "config.h"
#include "ota_update.h"
#include "smooth_font.h"
#include "sensor_freshness.h"

Arduino_H7_Video display(800, 480, GigaDisplayShield);
WiFiClient network;
WebSocketClient socket(network, TRANSPORT_ADAPTER_HOST, TRANSPORT_ADAPTER_WS_PORT);
bool clockReady = false, sensorReady = false;
bool outdoorReady = false;
int offsetMinutes = 0;
float temperature = 0, humidity = 0;
float outdoorTemperature = 0, outdoorHumidity = 0;
uint32_t outdoorMeasuredAt = 0, outdoorReceivedAt = 0;
uint32_t sensorMeasuredAt = 0, lastFrame = 0, lastDraw = 0, lastReport = 0;
uint32_t lastWifiTry = 0, lastSocketTry = 0;
bool wifiTried = false, socketTried = false;

// Drop diagnostic output when USB is busy; never wait for a serial reader.
void logLine(const char* line) {
  uint32_t sent = 0;
  _SerialUSB.send_nb((uint8_t*)line, strlen(line), &sent);
}

const SmoothGlyph* findGlyph(const SmoothFont& font, uint8_t code) {
  for (unsigned i = 0; i < font.count; ++i)
    if (font.glyphs[i].code == code) return &font.glyphs[i];
  return nullptr;
}

// Native-size alpha coverage from TrueType outlines, blended against black.
void drawText(const char* text, int center, int y, const SmoothFont& font, uint32_t color) {
  int width = 0;
  for (const char* p = text; *p; ++p) {
    const SmoothGlyph* glyph = findGlyph(font, (uint8_t)*p);
    if (glyph) width += glyph->advance;
  }
  int x = center - width / 2;
  for (const char* p = text; *p; ++p) {
    const SmoothGlyph* glyph = findGlyph(font, (uint8_t)*p);
    if (!glyph) continue;
    for (unsigned row = 0; row < glyph->height; ++row) {
      for (unsigned col = 0; col < glyph->width; ++col) {
        unsigned index = row * glyph->width + col;
        uint8_t packed = font.pixels[glyph->offset + index / 2];
        unsigned alpha = (index & 1) ? (packed & 15) : (packed >> 4);
        int px = x + glyph->left + col;
        int py = y + font.ascent + glyph->top + row;
        if (alpha && px >= 0 && px < 800 && py >= 0 && py < 480)
          display.set(px, py, ((color >> 16) & 255) * alpha / 15,
                      ((color >> 8) & 255) * alpha / 15, (color & 255) * alpha / 15);
      }
    }
    x += glyph->advance;
  }
}

void drawScreen() {
  char clock[16] = "--:--:--", temp[32] = "--.- \xB0" "C", rh[32] = "--.- %";
  char date[16] = "---- -- --";
  if (clockReady) {
    time_t local = time(nullptr) + offsetMinutes * 60;
    struct tm fields;
    gmtime_r(&local, &fields);
    strftime(clock, sizeof(clock), "%H:%M:%S", &fields);
    strftime(date, sizeof(date), "%Y-%m-%d", &fields);
  }
  bool fresh = sensorReady && sensor_is_fresh(clockReady, time(nullptr), sensorMeasuredAt);
  bool outdoorFresh = outdoorReady && millis() - outdoorReceivedAt < 180000UL &&
      sensor_is_fresh(clockReady, time(nullptr), outdoorMeasuredAt, 3600);
  char outdoorTemp[32] = "--.- \xB0" "C", outdoorRh[32] = "--.- %";
  if (outdoorFresh) {
    snprintf(outdoorTemp, sizeof(outdoorTemp), "%.1f \xB0" "C", outdoorTemperature);
    snprintf(outdoorRh, sizeof(outdoorRh), "%.1f %%", outdoorHumidity);
  }
  if (fresh) {
    snprintf(temp, sizeof(temp), "%.1f \xB0" "C", temperature);
    snprintf(rh, sizeof(rh), "%.1f %%", humidity);
  }
  display.beginDraw();
  display.background(0, 0, 0);
  display.clear();
  int dateWidth = 0;
  for (const char* p = date; *p; ++p) {
    const SmoothGlyph* glyph = findGlyph(labelFont, (uint8_t)*p);
    if (glyph) dateWidth += glyph->advance;
  }
  drawText(date, 776 - (dateWidth + 1) / 2, 12, labelFont, 0x9096A0);
  drawText(clock, 400, 35, clockFont, 0xF5F7FA);
  drawText("OUTDOOR", 210, 185, labelFont, 0x00FF80);
  drawText("FILAMENT", 590, 185, labelFont, 0x00FF80);
  drawText(outdoorTemp, 210, 228, valueFont, 0xF5F7FA);
  drawText(temp, 590, 228, valueFont, 0xF5F7FA);
  drawText(outdoorRh, 210, 330, valueFont, 0xF5F7FA);
  drawText(rh, 590, 330, valueFont, 0xF5F7FA);
  drawText(!socket.connected() ? "Connecting..." : !(fresh && outdoorFresh) ? "Waiting for fresh sensor data" : "Live", 400, 440, statusFont, 0x9096A0);
  display.endDraw();
}

void connectSocket() {
  socket.stop();
  socket.~WebSocketClient();
  new (&socket) WebSocketClient(network, TRANSPORT_ADAPTER_HOST, TRANSPORT_ADAPTER_WS_PORT);
  socket.setHttpResponseTimeout(3000);
  if (socket.begin("/ws/panels/primary") != 0) {
    socket.stop();
    return;
  }
  const char hello[] = "{\"cmd\":\"HELLO\",\"panel_id\":\"primary\",\"hostname\":\"housepanel\",\"firmware_version\":\"" FIRMWARE_VERSION "\"}";
  if (socket.beginMessage(TYPE_TEXT) != 0 || socket.write((const uint8_t*)hello, sizeof(hello)-1) != sizeof(hello)-1 || socket.endMessage() != 0) {
    socket.stop();
    return;
  }
  lastFrame = millis();
}

void receiveFrame() {
  int length = socket.parseMessage(); // Library handles server ping/pong.
  if (length <= 0) return;
  char payload[1024];
  if (length >= (int)sizeof(payload)) { socket.stop(); return; }
  int count = 0;
  uint32_t started = millis();
  while (count < length && millis() - started < 1000) {
    int ch = socket.read();
    if (ch >= 0) payload[count++] = (char)ch;
    else delay(1);
  }
  if (count != length) { socket.stop(); return; }
  payload[count] = 0;
  lastFrame = millis();
  JsonDocument data;
  if (deserializeJson(data, payload, count)) return;
  const char* cmd = data["cmd"] | "";
  if (strcmp(cmd, "TIME") == 0 && data["epoch"].is<unsigned long>() && data["utc_offset_min"].is<int>()) {
    unsigned long epoch = data["epoch"];
    int offset = data["utc_offset_min"];
    if (epoch >= 1700000000UL && offset >= -840 && offset <= 840) {
      set_time(epoch);
      offsetMinutes = offset;
      clockReady = true;
    }
  } else if (strcmp(cmd, "OUTDOOR_TEMP") == 0 && data["available"].is<bool>() && !data["available"].as<bool>()) {
    outdoorReady = false;
  } else if ((strcmp(cmd, "SYSMON_TEMP") == 0 || strcmp(cmd, "OUTDOOR_TEMP") == 0) &&
             data["t"].is<float>() && data["h"].is<float>()) {
    float t = data["t"], h = data["h"];
    if (isfinite(t) && isfinite(h) && h >= 0 && h <= 100) {
      unsigned long measured = data["measured_at"].is<unsigned long>() ? data["measured_at"].as<unsigned long>() : 0;
      if (strcmp(cmd, "OUTDOOR_TEMP") == 0) {
        outdoorTemperature = t; outdoorHumidity = h;
        outdoorMeasuredAt = measured; outdoorReceivedAt = millis(); outdoorReady = true;
      } else {
        temperature = t; humidity = h;
        sensorMeasuredAt = measured; sensorReady = true;
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  if (display.begin() != 0) { while (true) delay(1000); }
  WiFi.setHostname("housepanel");
  drawScreen();
  ota_init();
  logLine("FILAMENT: boot\n");
}

void loop() {
  ota_loop();
  uint32_t now = millis();
  if (WiFi.status() != WL_CONNECTED) {
    if (!wifiTried || now - lastWifiTry >= 15000UL) {
      wifiTried = true; lastWifiTry = now;
      socket.stop();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
  } else if (!socket.connected()) {
    if (!socketTried || now - lastSocketTry >= 5000UL) {
      socketTried = true; lastSocketTry = now;
      connectSocket();
    }
  } else {
    receiveFrame();
    if (millis() - lastFrame > 90000UL) socket.stop();
  }
  now = millis();
  if (now - lastDraw >= 1000UL) { lastDraw = now; drawScreen(); }
  if (now - lastReport >= 5000UL) {
    lastReport = now;
    // Keep one report within a USB packet; back-to-back nonblocking writes can
    // drop the second line and hide one source from diagnostics.
    char line[64];
    snprintf(line, sizeof(line), "F:%.1f/%.1f O:%.1f/%.1f ready=%d/%d\n", temperature, humidity, outdoorTemperature, outdoorHumidity, sensorReady, outdoorReady);
    logLine(line);
  }
  delay(5);
}
