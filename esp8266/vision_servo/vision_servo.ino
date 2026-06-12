#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <Servo.h>

// --- Configuration ---
// ESP8266 only supports 2.4 GHz Wi-Fi (not 5 GHz).
// SSID must match exactly (capital letters matter).
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

const char* mqtt_server = "192.168.1.101";  // PC IP — run ipconfig, same Wi-Fi as ESP8266
const int mqtt_port = 1884;
const char* client_id = "esp8266_rusi123";
const char* topic_movement = "vision/rusi123/movement";
const char* topic_heartbeat = "vision/rusi123/heartbeat";

// Servo Configuration
// Signal: D7 (GPIO13) — 3.3V logic is OK for the signal wire
// Power:  Most servos need 4.8–6V on V+; 3.3V often causes weak/no movement.
//         If you only have 3.3V, expect buzzing or no torque — use external 5V if possible.
Servo panServo;
Servo tiltServo;
const int panPin = 13;   // D7 — horizontal pan
const int tiltPin = 12;  // D6 — optional vertical tilt (comment out attach if unused)
const bool USE_TILT = false;

int panAngle = 90;
int tiltAngle = 90;

// --- Search Mode Variables ---
bool isSearching = true;   // sweep only until PC confirms target locked
bool targetLocked = false; // stays true until PC says searching again
unsigned long lastSweepTime = 0;
const int SWEEP_DELAY_MS = 35;
const int SWEEP_STEP = 4;
int sweepStep = SWEEP_STEP;
const int PAN_MIN = 15;
const int PAN_MAX = 165;
const int TILT_MIN = 30;
const int TILT_MAX = 150;

// Parse a JSON number field (simple substring parse)
float parseJsonFloat(const String& msg, const char* key) {
  String needle = String("\"") + key + "\":";
  int idx = msg.indexOf(needle);
  if (idx < 0) return 0.0f;
  idx += needle.length();
  return msg.substring(idx).toFloat();
}

bool parseJsonBool(const String& msg, const char* key) {
  String needle = String("\"") + key + "\":";
  int idx = msg.indexOf(needle);
  if (idx < 0) return false;
  idx += needle.length();
  return msg.substring(idx).startsWith("true");
}

void movePan(int delta) {
  panAngle += delta;
  if (panAngle < 0) panAngle = 0;
  if (panAngle > 180) panAngle = 180;
  panServo.write(panAngle);
}

void moveTilt(int delta) {
  if (!USE_TILT) return;
  tiltAngle += delta;
  if (tiltAngle < TILT_MIN) tiltAngle = TILT_MIN;
  if (tiltAngle > TILT_MAX) tiltAngle = TILT_MAX;
  tiltServo.write(tiltAngle);
}

int proportionalStep(float offset) {
  float magnitude = abs(offset);
  if (magnitude < 0.05f) return 0;
  int step = (int)(magnitude * 10.0f);
  if (step < 2) step = 2;
  if (step > 10) step = 10;
  return step;
}

WiFiClient espClient;
PubSubClient client(espClient);

void scan_wifi() {
  Serial.println("Scanning for Wi-Fi networks...");
  int n = WiFi.scanNetworks();
  if (n == 0) {
    Serial.println("No networks found — move ESP8266 closer to the phone hotspot.");
    return;
  }
  Serial.print(n);
  Serial.println(" networks found:");
  for (int i = 0; i < n; i++) {
    Serial.print("  ");
    Serial.print(WiFi.SSID(i));
    Serial.print(" (");
    Serial.print(WiFi.RSSI(i));
    Serial.println(" dBm)");
  }
}

void setup_wifi() {
  Serial.println();
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);

  WiFi.persistent(false);
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(200);
  WiFi.begin(ssid, password);

  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 60) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("WiFi connected!");
    Serial.print("ESP8266 IP: ");
    Serial.println(WiFi.localIP());
    return;
  }

  Serial.print("WiFi FAILED. Status code: ");
  Serial.println(WiFi.status());
  Serial.println("Codes: 1=network not found, 4=wrong password");
  Serial.println("Use 2.4 GHz Wi-Fi only. Check SSID spelling exactly.");
  scan_wifi();
}

bool ensure_wifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  static unsigned long lastRetry = 0;
  unsigned long now = millis();
  if (now - lastRetry < 8000) {
    return false;
  }
  lastRetry = now;

  Serial.println("Retrying WiFi...");
  WiFi.disconnect();
  delay(100);
  WiFi.begin(ssid, password);
  return false;
}

void moveServo(int delta) {
  movePan(delta);
}

void startSearch(const char* reason) {
  if (targetLocked) {
    return; // PC says target is locked — never sweep
  }
  if (!isSearching) {
    Serial.print("SEARCH MODE: ");
    Serial.println(reason);
  }
  isSearching = true;
}

void stopSearch() {
  if (isSearching) {
    Serial.println("Target seen — STOP sweep, hold position");
  }
  isSearching = false;
  targetLocked = true;
}

void followTarget(const String& message) {
  stopSearch();

  float offsetX = parseJsonFloat(message, "offset_x");
  float offsetY = parseJsonFloat(message, "offset_y");

  int panStep = proportionalStep(offsetX);
  if (panStep > 0) {
    if (offsetX < 0) {
      movePan(-panStep);
      Serial.println("FOLLOW LEFT");
    } else {
      movePan(panStep);
      Serial.println("FOLLOW RIGHT");
    }
  }

  if (USE_TILT) {
    int tiltStep = proportionalStep(offsetY);
    if (tiltStep > 0) {
      if (offsetY < 0) {
        moveTilt(-tiltStep);
        Serial.println("FOLLOW UP");
      } else {
        moveTilt(tiltStep);
        Serial.println("FOLLOW DOWN");
      }
    }
  }

  if (message.indexOf("MOVE_UP") >= 0 && USE_TILT) moveTilt(-3);
  if (message.indexOf("MOVE_DOWN") >= 0 && USE_TILT) moveTilt(3);
  // BENAX assessment: horizontal pan only; tilt is manual 2-DOF on mount
}

void callback(char* topic, byte* payload, unsigned int length) {
  String message = "";
  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }

  bool locked = parseJsonBool(message, "locked");
  bool searching = parseJsonBool(message, "searching");

  // Target confirmed — stop sweeping immediately, hold pan angle
  if (locked) {
    stopSearch();
  }

  // Resume search only when PC says speaker left the frame
  if (searching ||
      message.indexOf("\"OUT_OF_FRAME\"") >= 0 ||
      message.indexOf("\"SCAN\"") >= 0) {
    if (!locked) {
      targetLocked = false;
      startSearch("target left camera");
    }
    return;
  }

  if (message.indexOf("\"STOPPED\"") >= 0 ||
      message.indexOf("\"CENTERED\"") >= 0) {
    return;
  }

  if (message.indexOf("\"MOVED_LEFT\"") >= 0) {
    followTarget(message);
    if (parseJsonFloat(message, "offset_x") == 0.0f) movePan(-3);
    return;
  }

  if (message.indexOf("\"MOVED_RIGHT\"") >= 0) {
    followTarget(message);
    if (parseJsonFloat(message, "offset_x") == 0.0f) movePan(3);
    return;
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("MQTT -> ");
    Serial.print(mqtt_server);
    Serial.print(":");
    Serial.print(mqtt_port);
    Serial.print(" ... ");
    client.setServer(mqtt_server, mqtt_port);
    if (client.connect(client_id)) {
      Serial.println("Connected!");
      client.subscribe(topic_movement);
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" (retry in 5s)");
      Serial.println("rc=-2 = PC broker unreachable (firewall or WiFi client isolation)");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  panServo.attach(panPin);
  panServo.write(panAngle);
  if (USE_TILT) {
    tiltServo.attach(tiltPin);
    tiltServo.write(tiltAngle);
  }

  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(callback);

  Serial.println("Ready — searching until target face is detected...");
}

void loop() {
  if (!ensure_wifi()) {
    return;
  }

  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();

  // Sweep only while searching and target not locked
  if (isSearching && !targetLocked) {
    if (now - lastSweepTime > SWEEP_DELAY_MS) {
      lastSweepTime = now;
      panAngle += sweepStep;

      if (panAngle >= PAN_MAX) {
        panAngle = PAN_MAX;
        sweepStep = -SWEEP_STEP;
      } else if (panAngle <= PAN_MIN) {
        panAngle = PAN_MIN;
        sweepStep = SWEEP_STEP;
      }
      panServo.write(panAngle);
    }
  }

  // --- SYSTEM HEARTBEAT ---
  static unsigned long lastHeartbeat = 0;
  if (now - lastHeartbeat > 5000) {
    lastHeartbeat = now;
    String heartbeat = "{\"node\": \"esp8266\", \"status\": \"ONLINE\"}";
    client.publish(topic_heartbeat, heartbeat.c_str());
  }
}