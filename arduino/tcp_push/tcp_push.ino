#include <WiFi.h>

// Laptop hotspot used for this test.
const char *WIFI_SSID = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const uint16_t TCP_PORT = 4212;

WiFiClient client;
bool wifiReady = false;
bool tcpReady = false;
unsigned long lastWifiAttempt = 0;
unsigned long lastTcpAttempt = 0;
uint8_t commandPacket[5];
size_t commandBytes = 0;

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
  lastWifiAttempt = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiReady) {
      client.stop();
      wifiReady = false;
      tcpReady = false;
      commandBytes = 0;
      Serial.println("WIFI LOST");
    }
    if (millis() - lastWifiAttempt >= 5000) {
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastWifiAttempt = millis();
    }
    delay(10);
    return;
  }

  if (!wifiReady) {
    WiFi.noLowPowerMode();  // Match the unicast UDP test.
    wifiReady = true;
    Serial.print("WIFI READY ");
    Serial.println(WiFi.localIP());
  }

  if (!client.connected()) {
    if (tcpReady) {
      client.stop();
      tcpReady = false;
      commandBytes = 0;
      Serial.println("TCP LOST");
    }
    if (millis() - lastTcpAttempt >= 1000) {
      lastTcpAttempt = millis();
      if (client.connect(WiFi.gatewayIP(), TCP_PORT)) {
        client.setNoDelay(true);
        tcpReady = true;
        uint8_t hello[7];
        hello[0] = 'H';
        WiFi.macAddress(hello + 1);
        client.write(hello, sizeof(hello));
        Serial.println("TCP READY");
      }
    }
    delay(1);
    return;
  }

  // TCP is a byte stream: assemble each five-byte command before acting.
  while (client.available() > 0) {
    int incoming = client.read();
    if (incoming < 0) break;
    commandPacket[commandBytes++] = static_cast<uint8_t>(incoming);
    if (commandBytes != sizeof(commandPacket)) continue;
    commandBytes = 0;

    char command = static_cast<char>(commandPacket[4]);
    if (command != '0' && command != '1') continue;
    uint32_t sequence = (uint32_t(commandPacket[0]) << 24) |
                        (uint32_t(commandPacket[1]) << 16) |
                        (uint32_t(commandPacket[2]) << 8) |
                        uint32_t(commandPacket[3]);
    reportLed(sequence, command);

    // Network ACK: 'A', four sequence bytes, then the command byte.
    uint8_t ack[6] = {'A', commandPacket[0], commandPacket[1],
                      commandPacket[2], commandPacket[3], commandPacket[4]};
    client.write(ack, sizeof(ack));
  }
}
