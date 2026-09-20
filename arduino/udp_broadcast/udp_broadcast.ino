#include <WiFi.h>
#include <WiFiUdp.h>

// Replace these if you use a different 2.4 GHz network.
const char *WIFI_SSID = "SammyPC";
const char *WIFI_PASSWORD = "12345678";
const uint16_t UDP_PORT = 4210;

WiFiUDP udp;
bool listening = false;
unsigned long lastConnectAttempt = 0;
unsigned long lastHeartbeat = 0;

void reportLed(uint32_t sequence, char command) {
  digitalWrite(LED_BUILTIN, command == '1' ? HIGH : LOW);
  Serial.print("ACK ");
  Serial.print(sequence);
  Serial.print(' ');
  Serial.println(command);
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
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
    // Print heartbeat while trying to connect
    unsigned long now = millis();
    if (now - lastHeartbeat >= 2000) {
      Serial.print("HEARTBEAT (WiFi status: ");
      Serial.print(WiFi.status());
      Serial.println(")");
      lastHeartbeat = now;
    }
    if (now - lastConnectAttempt >= 5000) {
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastConnectAttempt = millis();
    }
    delay(10);
    return;
  }

  if (!listening) {
    // Test latency with the Pico W Wi-Fi radio kept awake.
    WiFi.noLowPowerMode();
    if (!udp.begin(UDP_PORT)) {
      Serial.println("UDP BIND FAILED");
      delay(1000);
      return;
    }
    listening = true;
    Serial.print("READY ");
    Serial.println(WiFi.localIP());
  }

  int packetSize = udp.parsePacket();
  if (packetSize == 0) return;

  // Packet: 4-byte big-endian sequence number, then ASCII '0' or '1'.
  if (packetSize != 5) {
    while (udp.available()) udp.read();
    return;
  }

  uint8_t packet[5];
  if (udp.read(packet, sizeof(packet)) != sizeof(packet)) return;
  char command = static_cast<char>(packet[4]);
  if (command != '0' && command != '1') return;

  uint32_t sequence = (uint32_t(packet[0]) << 24) |
                      (uint32_t(packet[1]) << 16) |
                      (uint32_t(packet[2]) << 8) |
                      uint32_t(packet[3]);
  reportLed(sequence, command);
}
