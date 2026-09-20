#include <WiFi.h>
#include <WiFiUdp.h>
#include <string.h>

// Set these to the access point used for the current test.
const char *WIFI_SSID = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const uint16_t COMMAND_PORT = 4210;
const uint16_t REGISTRATION_PORT = 4211;

WiFiUDP udp;
bool listening = false;
unsigned long lastConnectAttempt = 0;

void announceTo(IPAddress address, uint16_t port) {
  if (udp.beginPacket(address, port)) {
    udp.print("HELLO ");
    udp.print(WiFi.macAddress());
    udp.endPacket();
  }
}

void reportLed(uint32_t sequence, char command, uint32_t parseUs) {
  uint32_t ledStarted = micros();
  digitalWrite(LED_BUILTIN, command == '1' ? HIGH : LOW);
  uint32_t ledUs = micros() - ledStarted;
  Serial.print("ACK ");
  Serial.print(sequence);
  Serial.print(' ');
  Serial.print(command);
  Serial.print(" LED_US=");
  Serial.print(ledUs);
  Serial.print(" PARSE_US=");
  Serial.println(parseUs);
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
    if (millis() - lastConnectAttempt >= 5000) {
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastConnectAttempt = millis();
    }
    delay(10);
    return;
  }

  if (!listening) {
    WiFi.noLowPowerMode();  // Match the second broadcast test.
    if (!udp.begin(COMMAND_PORT)) {
      Serial.println("UDP BIND FAILED");
      delay(1000);
      return;
    }
    listening = true;
    Serial.print("READY ");
    Serial.println(WiFi.localIP());
    announceTo(WiFi.gatewayIP(), REGISTRATION_PORT);
  }

  uint32_t parseStarted = micros();
  int packetSize = udp.parsePacket();
  uint32_t parseUs = micros() - parseStarted;
  if (packetSize == 0) return;

  if (packetSize == 8) {
    uint8_t discovery[8];
    IPAddress sender = udp.remoteIP();
    uint16_t senderPort = udp.remotePort();
    if (udp.read(discovery, sizeof(discovery)) == sizeof(discovery) &&
        memcmp(discovery, "DISCOVER", sizeof(discovery)) == 0) {
      announceTo(sender, senderPort);
    }
    return;
  }

  // Command packet: 4-byte big-endian sequence number, then ASCII '0' or '1'.
  if (packetSize != 5) {
    while (udp.available()) udp.read();
    return;
  }

  uint8_t packet[5];
  IPAddress sender = udp.remoteIP();
  uint16_t senderPort = udp.remotePort();
  if (udp.read(packet, sizeof(packet)) != sizeof(packet)) return;
  char command = static_cast<char>(packet[4]);
  if (command != '0' && command != '1') return;

  uint32_t sequence = (uint32_t(packet[0]) << 24) |
                      (uint32_t(packet[1]) << 16) |
                      (uint32_t(packet[2]) << 8) |
                      uint32_t(packet[3]);
  reportLed(sequence, command, parseUs);

  // Echo the same command over Wi-Fi for a second timing path.
  if (udp.beginPacket(sender, senderPort)) {
    udp.write(reinterpret_cast<const uint8_t *>("ACK"), 3);
    udp.write(packet, sizeof(packet));
    udp.endPacket();
  }
}
