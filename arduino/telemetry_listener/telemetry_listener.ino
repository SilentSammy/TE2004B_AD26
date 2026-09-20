#include <WiFi.h>
#include <WiFiUdp.h>

// Replace these with the network you want the Pico W to join.
const char *WIFI_SSID = "SammyPC";
const char *WIFI_PASSWORD = "12345678";
const uint16_t TELEMETRY_PORT = 5000;

WiFiUDP udp;
bool listening = false;
unsigned long lastConnectAttempt = 0;
unsigned long lastHeartbeat = 0;
uint8_t buf[512];

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastConnectAttempt = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (listening) {
      udp.stop();
      listening = false;
      Serial.println("WIFI LOST");
    }
    unsigned long now = millis();
    if (now - lastHeartbeat >= 2000) {
      Serial.print("HEARTBEAT (WiFi status: ");
      Serial.print(WiFi.status());
      Serial.println(")");
      lastHeartbeat = now;
    }
    if (now - lastConnectAttempt >= 5000) {
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastConnectAttempt = now;
    }
    delay(10);
    return;
  }

  if (!listening) {
    WiFi.noLowPowerMode();
    if (!udp.begin(TELEMETRY_PORT)) {
      Serial.println("UDP BIND FAILED");
      delay(1000);
      return;
    }
    listening = true;
    Serial.print("READY ");
    Serial.println(WiFi.localIP());
  }

  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    if (packetSize > (int)sizeof(buf)) packetSize = sizeof(buf);
    int received = udp.read(buf, packetSize);
    if (received > 0) {
      Serial.print("RX ");
      Serial.write(buf, received);
      Serial.println();
    }
  }
}
