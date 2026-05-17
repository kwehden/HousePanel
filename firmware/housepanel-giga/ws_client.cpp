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
    String msg = "{\"cmd\":\"HELLO\",\"firmware_version\":\"";
    msg += FIRMWARE_VERSION;
    msg += "\",\"post_ota\":";
    msg += post_ota ? "true" : "false";
    msg += "}";
    _ws.beginMessage(TYPE_TEXT);
    _ws.print(msg);
    _ws.endMessage();
}

void ws_loop() {
    int msg_size = _ws.parseMessage();
    if (msg_size > 0) {
        Serial.print("ws_loop: msg_size=");
        Serial.println(msg_size);
        // Wait until all payload bytes are in the TCP buffer.
        // WiFiClient::read() is non-blocking; if bytes haven't arrived yet
        // readString() appends 0xFF garbage and corrupts the JSON.
        unsigned long wait_start = millis();
        while (_wifi_client.available() < msg_size) {
            if ((millis() - wait_start) > 1000) {
                Serial.println("ws_loop: payload wait timeout");
                break;
            }
            delay(1);
        }
        Serial.print("ws_loop: avail=");
        Serial.println(_wifi_client.available());
        String payload = _ws.readString();
        Serial.print("ws_loop: payload len=");
        Serial.print(payload.length());
        Serial.print(" prefix=");
        Serial.println(payload.substring(0, 60));
        CommandFrame frame;
        if (parse_command_frame(payload, frame)) {
            g_last_frame = frame;
            g_frame_ready = true;
            Serial.print("ws_loop: parsed type=");
            Serial.println((int)frame.type);
        } else {
            Serial.println("ws_loop: parse FAILED");
        }
    }
}
