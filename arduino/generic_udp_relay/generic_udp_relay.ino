#include <WiFi.h>
#include <WiFiUdp.h>

// Replace these with the network you want the Pico W to join.
const char *WIFI_SSID = "embedded";
const char *WIFI_PASSWORD = "12345678";

const uint16_t DISCOVERY_PORT = 5001;  // Fixed and always on: DISCOVER -> HELLO <mac>.
const uint8_t MAX_SUBSCRIPTIONS = 4;   // How many UDP ports the robot can subscribe to at once.
const unsigned long LEASE_MS = 10000;  // A subscription expires this long after its last renewal.
const unsigned long INFO_INTERVAL_MS = 2000;  // How often to refresh the Zumo's display info.
const uint32_t ROBOT_BAUD = 115200;    // Serial1 link to the non-wireless robot Pico.
const size_t BUF_SIZE = 512;

unsigned long lastConnectAttempt = 0;
unsigned long lastHeartbeat = 0;
bool wifiWasConnected = false;

WiFiUDP discoveryUdp;

// One of these per subscribed port. Each holds a "tx" buffer (the latest
// packet queued or currently being relayed) and an "rx" buffer used only
// while tx is actively mid-transmission, so a fresh packet can never
// corrupt bytes still being written out over Serial1.
struct Subscription {
  uint16_t port = 0;  // 0 means this slot is free.
  WiFiUDP udp;
  unsigned long expiresAt = 0;

  uint8_t bufA[BUF_SIZE];
  uint8_t bufB[BUF_SIZE];
  uint8_t *txBuf = bufA;
  size_t txLen = 0;
  bool txReady = false;

  uint8_t *rxBuf = bufB;
  size_t rxLen = 0;
  bool rxReady = false;
};

Subscription subs[MAX_SUBSCRIPTIONS];
Subscription *activeSub = nullptr;
size_t activeSent = 0;
uint8_t rrIndex = 0;  // Round-robin cursor across subs[]; no priority between ports.

// The Pico's own network info (reserved pseudo-port 0), lowest priority.
uint8_t infoBuf[160];
size_t infoLen = 0;
size_t infoSent = 0;
bool infoReady = false;
bool activeIsInfo = false;
unsigned long lastInfoMs = 0;

uint8_t uartLineBuf[16];
size_t uartLineLen = 0;
uint8_t usbLineBuf[16];
size_t usbLineLen = 0;

Subscription *findSubscription(uint16_t port) {
  for (uint8_t i = 0; i < MAX_SUBSCRIPTIONS; i++) {
    if (subs[i].port == port) return &subs[i];
  }
  return nullptr;
}

Subscription *allocSubscription(uint16_t port) {
  for (uint8_t i = 0; i < MAX_SUBSCRIPTIONS; i++) {
    if (subs[i].port == 0) {
      subs[i].port = port;
      return &subs[i];
    }
  }
  return nullptr;  // Pool full.
}

void subscribe(uint16_t port) {
  Subscription *s = findSubscription(port);
  if (s == nullptr) {
    s = allocSubscription(port);
    if (s == nullptr) {
      Serial.println("SUBSCRIPTION POOL FULL");
      return;
    }
    if (!s->udp.begin(port)) {
      Serial.print("UDP BIND FAILED on port ");
      Serial.println(port);
      s->port = 0;  // Free the slot back up.
      return;
    }
  }
  s->expiresAt = millis() + LEASE_MS;
}

void expireSubscriptions() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < MAX_SUBSCRIPTIONS; i++) {
    Subscription &s = subs[i];
    if (s.port != 0 && (long)(now - s.expiresAt) >= 0) {
      s.udp.stop();
      if (activeSub == &s) activeSub = nullptr;
      s.port = 0;
      s.txReady = false;
      s.rxReady = false;
    }
  }
}

// Parse "<port>\n" lines arriving over USB or UART0 as subscribe/renew requests.
void handleSubscribeByte(uint8_t *buf, size_t &len, char c) {
  if (c == '\n' || c == '\r') {
    if (len > 0) {
      buf[len] = '\0';
      long port = atol((char *)buf);
      if (port > 0 && port <= 65535) subscribe((uint16_t)port);
      len = 0;
    }
    return;
  }
  if (len < sizeof(uartLineBuf) - 1) buf[len++] = (uint8_t)c;
}

void pollSubscribeRequests() {
  while (Serial1.available()) handleSubscribeByte(uartLineBuf, uartLineLen, (char)Serial1.read());
  while (Serial.available()) handleSubscribeByte(usbLineBuf, usbLineLen, (char)Serial.read());
}

void serviceDiscovery() {
  int packetSize = discoveryUdp.parsePacket();
  if (packetSize <= 0) return;
  uint8_t raw[16];
  if (packetSize > (int)sizeof(raw)) packetSize = sizeof(raw);
  int received = discoveryUdp.read(raw, packetSize);
  if (received != 8 || memcmp(raw, "DISCOVER", 8) != 0) return;

  IPAddress sender = discoveryUdp.remoteIP();
  uint16_t senderPort = discoveryUdp.remotePort();
  if (discoveryUdp.beginPacket(sender, senderPort)) {
    discoveryUdp.print("HELLO ");
    discoveryUdp.print(WiFi.macAddress());
    discoveryUdp.endPacket();
  }
}

void serviceSubscription(Subscription &s) {
  int packetSize = s.udp.parsePacket();
  if (packetSize <= 0) return;

  uint8_t raw[BUF_SIZE];
  if ((size_t)packetSize > sizeof(raw)) packetSize = sizeof(raw);
  int received = s.udp.read(raw, packetSize);
  if (received <= 0) return;

  // Tag the relayed line with the source port, e.g. "5000 {...}", so the
  // robot can dispatch by port; the Pico attaches no other meaning to it.
  char tag[8];
  int tagLen = snprintf(tag, sizeof(tag), "%u ", s.port);
  uint8_t *dest = (&s == activeSub) ? s.rxBuf : s.txBuf;
  size_t maxPayload = BUF_SIZE - tagLen - 1;
  size_t copyLen = (size_t)received > maxPayload ? maxPayload : (size_t)received;
  memcpy(dest, tag, tagLen);
  memcpy(dest + tagLen, raw, copyLen);
  size_t total = tagLen + copyLen;
  dest[total++] = '\n';

  Serial.write(dest, total);

  if (&s == activeSub) {
    s.rxLen = total;
    s.rxReady = true;  // Newest packet always wins over any older, un-relayed one.
  } else {
    s.txLen = total;
    s.txReady = true;
  }
}

void buildInfoLine() {
  IPAddress ip = WiFi.localIP();
  int n = snprintf(
      (char *)infoBuf, sizeof(infoBuf),
      "0 {\"ip\":\"%d.%d.%d.%d\",\"rssi\":%ld,\"ssid\":\"%s\"}\n",
      ip[0], ip[1], ip[2], ip[3], (long)WiFi.RSSI(), WIFI_SSID);
  if (n <= 0) return;
  infoLen = (size_t)n >= sizeof(infoBuf) ? sizeof(infoBuf) - 1 : (size_t)n;
  infoReady = true;
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
      discoveryUdp.stop();
      for (uint8_t i = 0; i < MAX_SUBSCRIPTIONS; i++) {
        subs[i].udp.stop();
        subs[i].port = 0;
        subs[i].txReady = false;
        subs[i].rxReady = false;
      }
      activeSub = nullptr;
      activeIsInfo = false;
      infoReady = false;
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
    discoveryUdp.begin(DISCOVERY_PORT);
    wifiWasConnected = true;
    lastInfoMs = millis() - INFO_INTERVAL_MS;  // Send info promptly after connecting.
    Serial.print("READY ");
    Serial.println(WiFi.localIP());
  }

  serviceDiscovery();
  pollSubscribeRequests();
  expireSubscriptions();
  for (uint8_t i = 0; i < MAX_SUBSCRIPTIONS; i++) {
    if (subs[i].port != 0) serviceSubscription(subs[i]);
  }

  if (!infoReady && !activeIsInfo && millis() - lastInfoMs >= INFO_INTERVAL_MS) {
    buildInfoLine();
    lastInfoMs = millis();
  }

  // Round-robin across active subscriptions; info is lowest priority.
  if (activeSub == nullptr && !activeIsInfo) {
    for (uint8_t i = 0; i < MAX_SUBSCRIPTIONS; i++) {
      uint8_t idx = (rrIndex + i) % MAX_SUBSCRIPTIONS;
      if (subs[idx].port != 0 && subs[idx].txReady) {
        activeSub = &subs[idx];
        activeSent = 0;
        rrIndex = (idx + 1) % MAX_SUBSCRIPTIONS;
        break;
      }
    }
    if (activeSub == nullptr && infoReady) {
      activeIsInfo = true;
      infoSent = 0;
    }
  }

  // Non-blocking relay: only write as much as Serial1's buffer can take right now.
  if (activeSub != nullptr) {
    Subscription &s = *activeSub;
    while (activeSent < s.txLen && Serial1.availableForWrite() > 0) {
      Serial1.write(s.txBuf[activeSent++]);
    }
    if (activeSent >= s.txLen) {
      if (s.rxReady) {
        // A newer packet landed on this port while we were sending; take it over.
        uint8_t *swap = s.txBuf;
        s.txBuf = s.rxBuf;
        s.rxBuf = swap;
        s.txLen = s.rxLen;
        s.txReady = true;
        s.rxReady = false;
      } else {
        s.txReady = false;
      }
      activeSub = nullptr;
    }
  } else if (activeIsInfo) {
    while (infoSent < infoLen && Serial1.availableForWrite() > 0) {
      Serial1.write(infoBuf[infoSent++]);
    }
    if (infoSent >= infoLen) {
      infoReady = false;
      activeIsInfo = false;
    }
  }
}
