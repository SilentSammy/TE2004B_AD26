// Send '0' or '1' over USB serial to control the Pico W's built-in LED.
void turnOnLed() {
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.println("LED ON");
}

void turnOffLed() {
  digitalWrite(LED_BUILTIN, LOW);
  Serial.println("LED OFF");
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.begin(115200);
}

void loop() {
  if (Serial.available() > 0) {
    char command = Serial.read();

    if (command == '0') {
      turnOffLed();
    } else if (command == '1') {
      turnOnLed();
    }
  }
}
