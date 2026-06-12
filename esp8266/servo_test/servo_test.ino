/*
 * SERVO MOTOR TEST — ESP8266 (NodeMCU / Wemos D1 Mini)
 *
 * Wiring:
 *   Servo signal (yellow/orange) -> D7 (GPIO 13)
 *   Servo GND (brown/black)      -> GND on board
 *   Servo V+ (red)               -> 5V recommended (4.8–6V)
 *
 * 3.3V power note:
 *   ESP8266 runs at 3.3V, but most hobby servos need ~5V on V+ to move properly.
 *   3.3V on V+ often causes buzzing, jitter, or no rotation — that is a power issue,
 *   not a code issue. Keep signal on D7; use a separate 5V supply for V+ if you can.
 *
 * Upload this sketch ONLY from the servo_test folder (not vision_servo).
 * Open Serial Monitor at 115200 baud.
 *
 * What you should see:
 *   - Servo moves: 90 -> 0 -> 180 -> 90 -> repeat
 *   - Serial prints each step
 *
 * If servo does NOT move:
 *   - Check wiring and power
 *   - Try another pin: change SERVO_PIN to 12 (D6) or 13 (D7)
 *   - Try a different USB cable / 5V supply for the servo
 */

#include <Servo.h>

const int SERVO_PIN = 13;  // D7 on NodeMCU

Servo testServo;
int angle = 90;

void moveTo(int target, const char* label) {
  Serial.print("Moving to ");
  Serial.print(target);
  Serial.print(" deg (");
  Serial.print(label);
  Serial.println(")");

  if (target > angle) {
    for (int a = angle; a <= target; a++) {
      testServo.write(a);
      delay(15);
    }
  } else {
    for (int a = angle; a >= target; a--) {
      testServo.write(a);
      delay(15);
    }
  }
  angle = target;
  delay(500);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== ESP8266 SERVO TEST ===");
  Serial.println("Pin: GPIO 13 (D7)");
  Serial.println("Starting in 2 seconds...");
  delay(2000);

  testServo.attach(SERVO_PIN);
  testServo.write(angle);
  Serial.println("Servo attached. Beginning test loop...");
}

void loop() {
  moveTo(0, "full left");
  moveTo(90, "center");
  moveTo(180, "full right");
  moveTo(90, "center");

  Serial.println("--- cycle complete, repeating ---");
  delay(1000);
}
