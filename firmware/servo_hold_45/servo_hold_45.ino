/*
 * Hold 5 servos at 45 degrees - Arduino Uno, pins 3, 5, 6, 9, 10
 *
 * Written to keep peak current as low as possible, because five MG995s
 * moving together will collapse most supplies:
 *   - servos are brought up one at a time, not all at once
 *   - each one ramps to the target in small steps instead of slamming there
 *   - only ever one servo in motion; the rest are already holding
 *
 * Power: all red wires to an external 5-6V supply (+), all brown wires to
 * that supply's (-) AND to Arduino GND. Keep the Arduino on USB so a sag on
 * the servo rail cannot reset the board.
 */

#include <Servo.h>

const uint8_t SERVO_PINS[] = {3, 5, 6, 9, 10};
const uint8_t NUM_SERVOS = sizeof(SERVO_PINS) / sizeof(SERVO_PINS[0]);

const int PULSE_MIN = 600;    // us at 0 deg
const int PULSE_MAX = 2400;   // us at 180 deg

const int TARGET      = 45;   // the angle to hold
const int ATTACH_REST = 90;   // where a servo lands when it is first attached
const int STEP_MS     = 20;   // ms per degree while ramping - raise to slow it

Servo servos[NUM_SERVOS];

// Walk one servo from `from` to `to` a degree at a time.
void rampTo(Servo &s, int from, int to) {
  int step = (to > from) ? 1 : -1;
  for (int a = from; a != to; a += step) {
    s.write(a);
    delay(STEP_MS);
  }
  s.write(to);
}

void setup() {
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    // Attaching with no prior write emits the library default pulse, so the
    // servo settles near ATTACH_REST before we ramp it down to TARGET.
    servos[i].attach(SERVO_PINS[i], PULSE_MIN, PULSE_MAX);
    delay(400);                                  // let it arrive and the rail recover

    rampTo(servos[i], ATTACH_REST, TARGET);
    delay(300);                                  // settle before the next servo
  }
}

void loop() {
  // Nothing to do. The Servo library keeps pulsing on a timer interrupt, so
  // all five hold 45 deg on their own.
}
