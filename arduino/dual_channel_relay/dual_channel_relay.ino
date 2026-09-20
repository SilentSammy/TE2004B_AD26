#include <WiFi.h>
#include <WiFiUdp.h>

// Replace these with the network you want the Pico W to join.
const char *WIFI_SSID = "SammyPC";
const char *WIFI_PASSWORD = "12345678";
const uint16_t TELEMETRY_PORT = 5000;  // Public: anyone broadcasting here (e.g. main.py).
const uint16_t COMMAND_PORT = 5001;    // Private: unicast packets sent to this Pico specifically.
const uint32_t ROBOT_BAUD = 115200;    // Serial1 link to the non-wireless robot Pico.
const size_t BUF_SIZE = 512;

unsigned long lastConnectAttempt = 0;
unsigned long lastHeartbeat = 0;
bool wifiWasConnected = false;

// One channel per UDP port. Each holds a "tx" buffer (the latest packet
// queued or currently being relayed) and an "rx" buffer used only while tx
// is actively mid-transmission, so a fresh packet can never corrupt bytes
// still being written out over Serial1.
struct Channel {
  WiFiUDP udp;
  uint16_t port;
  const char *tag;
  bool listening = false;

  uint8_t bufA[BUF_SIZE];
  uint8_t bufB[BUF_SIZE];
  uint8_t *txBuf = bufA;
  size_t txLen = 0;
  bool txReady = false;

  uint8_t *rxBuf = bufB;
  size_t rxLen = 0;
  bool rxReady = false;

  Channel(uint16_t port, const char *tag) : port(port), tag(tag) {}
};

Channel telemetry(TELEMETRY_PORT, "T ");
Channel command(COMMAND_PORT, "C ");

Channel *activeChannel = nullptr;
size_t activeSent = 0;

void beginChannel(Channel &ch) {
  ch.listening = ch.udp.begin(ch.port);
  if (!ch.listening) {
    Serial.print("UDP BIND FAILED on port ");
    Serial.println(ch.port);
  }
}

void receiveChannel(Channel &ch) {
  int packetSize = ch.udp.parsePacket();
  if (packetSize <= 0) return;

  // Land the payload after the tag, so the relayed line is ready to stream as-is.
  size_t tagLen = strlen(ch.tag);
  uint8_t *dest = (&ch == activeChannel) ? ch.rxBuf : ch.txBuf;
  if ((size_t)packetSize > BUF_SIZE - tagLen - 1) packetSize = BUF_SIZE - tagLen - 1;
  memcpy(dest, ch.tag, tagLen);
  int received = ch.udp.read(dest + tagLen, packetSize);
  if (received <= 0) return;
  size_t total = tagLen + received;
  dest[total++] = '\n';

  Serial.write(dest, total);

  if (&ch == activeChannel) {
    ch.rxLen = total;
    ch.rxReady = true;  // Newest packet always wins over any older, un-relayed one.
  } else {
    ch.txLen = total;
    ch.txReady = true;
  }
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(ROBOT_BAUD);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastConnectAttempt = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiWasConnected) {
      telemetry.udp.stop();
      command.udp.stop();
      telemetry.listening = command.listening = false;
      wifiWasConnected = false;
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

  if (!wifiWasConnected) {
    WiFi.noLowPowerMode();
    beginChannel(telemetry);
    beginChannel(command);
    wifiWasConnected = true;
    Serial.print("READY ");
    Serial.println(WiFi.localIP());
  }

  receiveChannel(command);    // Check the private channel first: it is higher priority.
  receiveChannel(telemetry);

  // Once free, prefer the command channel over telemetry when both are waiting.
  if (activeChannel == nullptr) {
    if (command.txReady) {
      activeChannel = &command;
    } else if (telemetry.txReady) {
      activeChannel = &telemetry;
    }
    if (activeChannel != nullptr) activeSent = 0;
  }

  // Non-blocking relay: only write as much as Serial1's buffer can take right now.
  if (activeChannel != nullptr) {
    Channel &ch = *activeChannel;
    while (activeSent < ch.txLen && Serial1.availableForWrite() > 0) {
      Serial1.write(ch.txBuf[activeSent++]);
    }
    if (activeSent >= ch.txLen) {
      if (ch.rxReady) {
        // A newer packet landed on this channel while we were sending; take it over.
        uint8_t *swap = ch.txBuf;
        ch.txBuf = ch.rxBuf;
        ch.rxBuf = swap;
        ch.txLen = ch.rxLen;
        ch.txReady = true;
        ch.rxReady = false;
      } else {
        ch.txReady = false;
      }
      activeChannel = nullptr;
    }
  }
}
