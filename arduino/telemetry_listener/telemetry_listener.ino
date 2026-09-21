#include <WiFi.h>
#include <WiFiUdp.h>

// Replace these with the network you want the Pico W to join.
const char *WIFI_SSID = "embedded";
const char *WIFI_PASSWORD = "12345678";
const uint16_t TELEMETRY_PORT = 5000;

WiFiUDP udp;
uint8_t buf[512];

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) delay(10);
  udp.begin(TELEMETRY_PORT);
}

void loop() {
  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    if (packetSize > (int)sizeof(buf)) packetSize = sizeof(buf);
    int received = udp.read(buf, packetSize);
    if (received > 0) {
      Serial.write(buf, received);
      Serial.println();
    }
  }
}

