#include "ws_client.h"
#include "config.h"

static WiFiClient _wifi_client;
static WebSocketClient _ws(_wifi_client, TRANSPORT_ADAPTER_HOST, TRANSPORT_ADAPTER_WS_PORT);

CommandFrame g_last_frame;
bool g_frame_ready = false;

void ws_init() {
    // nothing to init; client is constructed statically
}

bool ws_connect() {
    _ws.stop();
    int rc = _ws.begin(TRANSPORT_ADAPTER_WS_PATH);
    Serial.print("ws_connect rc=");
    Serial.println(rc);
    return (rc == 0);
}

bool ws_connected() {
    return _ws.connected();
}

void ws_send_hello(bool post_ota) {
    char buf[128];
    snprintf(buf, sizeof(buf),
             "{\"cmd\":\"HELLO\",\"firmware_version\":\"%s\",\"post_ota\":%s}",
             FIRMWARE_VERSION, post_ota ? "true" : "false");
    _ws.beginMessage(TYPE_TEXT);
    _ws.print(buf);
    _ws.endMessage();
}

// All streaming messages are <200 bytes; 256 is ample.
static const int WS_BUF_SIZE = 256;
static char _ws_payload[WS_BUF_SIZE];

void ws_loop() {
    int msg_size = _ws.parseMessage();
    if (msg_size <= 0) return;

    Serial.print("ws_loop: msg_size=");
    Serial.println(msg_size);

    int cap = min(msg_size, WS_BUF_SIZE - 1);
    int total = 0;
    unsigned long t0 = millis();

    while (total < cap) {
        int b = _ws.read();
        if (b >= 0) {
            _ws_payload[total++] = (char)b;
        } else {
            if ((millis() - t0) > 2000) {
                Serial.println("ws_loop: read timeout");
                break;
            }
            delay(1);
        }
    }
    _ws_payload[total] = '\0';

    Serial.print("ws_loop: read=");
    Serial.print(total);
    Serial.print(" prefix=");
    Serial.write(_ws_payload, min(total, 60));
    Serial.println();

    CommandFrame frame;
    if (parse_command_frame(_ws_payload, frame)) {
        g_last_frame = frame;
        g_frame_ready = true;
        Serial.print("ws_loop: type=");
        Serial.println((int)frame.type);
    } else {
        Serial.println("ws_loop: parse FAILED");
    }
}
