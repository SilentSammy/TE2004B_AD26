#include <WiFi.h>
#include <WiFiUdp.h>

// Replace these with the network you want the Pico W to join.
const char *WIFI_SSID = "SammyPC";
const char *WIFI_PASSWORD = "12345678";
const uint16_t TELEMETRY_PORT = 5000;
const uint32_t ROBOT_BAUD = 115200;  // Serial1 link to the non-wireless robot Pico.

WiFiUDP udp;
bool listening = false;
unsigned long lastConnectAttempt = 0;
unsigned long lastHeartbeat = 0;

// Two buffers so a fresh packet can never overwrite one still being relayed.
uint8_t bufA[512];
uint8_t bufB[512];
uint8_t *txBuf = bufA;
size_t txLen = 0;
size_t txSent = 0;
bool txActive = false;

uint8_t *rxBuf = bufB;
size_t rxLen = 0;
bool rxReady = false;

void setup() {
  Serial.begin(115200);
  Serial1.begin(ROBOT_BAUD);
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
    if (packetSize > (int)sizeof(bufA) - 1) packetSize = sizeof(bufA) - 1;
    int received = udp.read(rxBuf, packetSize);
    if (received > 0) {
      rxBuf[received] = '\n';
      rxLen = received + 1;
      rxReady = true;  // Newest packet always wins over any older, un-relayed one.
      Serial.print("RX ");
      Serial.write(rxBuf, received);
      Serial.println();
    }
  }

  // Pick up the latest packet only once the previous relay finished.
  if (!txActive && rxReady) {
    uint8_t *swap = txBuf;
    txBuf = rxBuf;
    rxBuf = swap;
    txLen = rxLen;
    txSent = 0;
    txActive = true;
    rxReady = false;
  }

  // Non-blocking relay: only write as much as Serial1's buffer can take right now.
  if (txActive) {
    while (txSent < txLen && Serial1.availableForWrite() > 0) {
      Serial1.write(txBuf[txSent++]);
    }
    if (txSent >= txLen) txActive = false;
  }
}
