/*
  BARNES Type B automated bending rig: steps 4 (spring-back) and 5 (cycles)
  ------------------------------------------------------------------------
  Hardware: Arduino Uno/Nano, STANDARD (positional, ~180 deg) MG995 on the crank,
            signal on pin 9. Power the servo from its own 5-6 V supply (>= 2 A);
            join the supply's GND to the Arduino GND. Never power the MG995 from the
            Arduino's 5 V pin.
  Serial:   115200 baud, line ending "Newline" (Arduino IDE Serial Monitor).

  The finger angle is a non-linear function of the crank angle (four-bar), so the sketch does
  not compute it: you CALIBRATE by jogging the crank until the protractor reads the finger angle
  you want, and save that servo position. Positions are stored as servo pulse widths (us), which
  are finer than degrees, and kept in EEPROM, so calibrate once per module.

  Commands (type, then Enter):
    ?            help and current settings
    p            print position, calibration and cycle count
    j <us>       jog to an absolute pulse width (500-2500), e.g.  j 1500
    + / -        jog by the step size (default 5 us);  ++ / --  by 10x the step
    s <us>       set the jog step size in us
    z            save the CURRENT position as finger 0 deg   (ZERO)
    t            save the CURRENT position as the test angle (TARGET)
    a <deg>      record what the protractor reads at TARGET (for the log only), e.g. a 60
    lo / hi      save the current position as the low / high SAFETY LIMIT (the sketch never
                 drives outside them: set them just inside where the collars meet)
    L            reset the safety limits to the full 500-2500 us range
    0            go to ZERO        T   go to TARGET  (slowly)
    c <n>        run n cycles ZERO -> TARGET -> ZERO (0 = run until stopped)
    f <ms>       time for one cycle in ms (default 2000 = 0.5 Hz; minimum 600)
    w <ms>       dwell at each end in ms (default 200)
    k <n>        stop at ZERO every n cycles for a resting-angle reading (default 100;
                 0 = never). It waits for you: read the protractor, type  r <deg>  to log
                 it and continue, or just  r  to continue without logging.
    x            stop now (finishes the move, goes to ZERO)
    n            reset the cycle counter to 0
    h <s>        step 4: drive to TARGET, hold s seconds, then prompt you to release the
                 finger (take the coupler pin out) and time the readings at 1 s, 10 s, 60 s
                 and 10 min. Type  r <deg>  at each prompt.
    d            detach the servo (goes limp)   e   re-attach it at the current position

  Output lines starting with "LOG," are CSV: copy them into the workbook.
    LOG,cycle,<n>,rest_deg,<deg>,ms,<millis>
    LOG,springback,<label>,<deg>,ms,<millis>
*/

#include <Servo.h>
#include <EEPROM.h>

const uint8_t SERVO_PIN = 9;
const int US_MIN = 500, US_MAX = 2500;   // MG995 pulse range; the safety limits sit inside it

struct Cal {
  uint16_t magic;
  int zeroUs, targetUs, loUs, hiUs;
  int targetDeg;
  uint32_t cycles;
};
const uint16_t MAGIC = 0xB5A1;
Cal cal;

Servo servo;
int posUs = 1500;          // last commanded pulse width
int stepUs = 5;
unsigned long cycleMs = 2000, dwellMs = 200;
uint32_t checkEvery = 100;
bool attached = false;

// ---------------------------------------------------------------- storage
void saveCal() { EEPROM.put(0, cal); }
void loadCal() {
  EEPROM.get(0, cal);
  if (cal.magic != MAGIC) {
    cal = {MAGIC, 1500, 1500, US_MIN, US_MAX, 0, 0};
    saveCal();
  }
}

// ---------------------------------------------------------------- motion
int clampUs(int us) {
  int lo = max(US_MIN, cal.loUs), hi = min(US_MAX, cal.hiUs);
  return constrain(us, lo, hi);
}

void attachIfNeeded() {
  if (!attached) { servo.attach(SERVO_PIN, US_MIN, US_MAX); servo.writeMicroseconds(posUs); attached = true; }
}

// Move to 'us' in 'ms' milliseconds with a smooth (cosine) speed profile, so the linkage and
// the TPU are not jerked. Returns false if stopped by 'x'.
bool moveTo(int us, unsigned long ms) {
  attachIfNeeded();
  us = clampUs(us);
  int from = posUs;
  if (ms < 20 || from == us) { posUs = us; servo.writeMicroseconds(us); return true; }
  unsigned long t0 = millis();
  while (true) {
    unsigned long t = millis() - t0;
    if (t >= ms) break;
    float f = 0.5f - 0.5f * cos(PI * (float)t / (float)ms);
    posUs = from + (int)round((us - from) * f);
    servo.writeMicroseconds(posUs);
    if (Serial.available() && Serial.peek() == 'x') { Serial.read(); return false; }
    delay(5);
  }
  posUs = us;
  servo.writeMicroseconds(us);
  return true;
}

void slowTo(int us) {   // for jogging and going home: about 1 s per 500 us
  moveTo(us, max(300UL, (unsigned long)abs(us - posUs) * 2UL));
}

// ---------------------------------------------------------------- serial helpers
String readLine() {
  while (!Serial.available()) {}
  String s = Serial.readStringUntil('\n');
  s.trim();
  return s;
}

void printState() {
  Serial.print(F("pos ")); Serial.print(posUs);
  Serial.print(F(" us | zero ")); Serial.print(cal.zeroUs);
  Serial.print(F(" | target ")); Serial.print(cal.targetUs);
  Serial.print(F(" (")); Serial.print(cal.targetDeg); Serial.print(F(" deg)"));
  Serial.print(F(" | limits ")); Serial.print(cal.loUs); Serial.print('-'); Serial.print(cal.hiUs);
  Serial.print(F(" | cycles ")); Serial.print(cal.cycles);
  Serial.print(F(" | cycle ")); Serial.print(cycleMs); Serial.print(F(" ms, dwell "));
  Serial.print(dwellMs); Serial.print(F(" ms, check every ")); Serial.println(checkEvery);
}

void help() {
  Serial.println(F("j <us> | + - ++ -- | s <us> | z | t | a <deg> | lo | hi | L | 0 | T | c <n> | f <ms> | w <ms> | k <n> | x | n | h <s> | d | e | p"));
  printState();
}

// wait for "r" or "r <deg>"; returns the angle or NAN
float waitReading(const __FlashStringHelper *prompt) {
  Serial.println(prompt);
  while (true) {
    String s = readLine();
    if (s.length() && s[0] == 'r') {
      s = s.substring(1); s.trim();
      return s.length() ? s.toFloat() : NAN;
    }
    Serial.println(F("type r <deg> (or r to skip)"));
  }
}

// ---------------------------------------------------------------- step 5: cycles
void runCycles(uint32_t n) {
  if (cal.zeroUs == cal.targetUs) { Serial.println(F("calibrate z and t first")); return; }
  unsigned long half = max(300UL, cycleMs / 2 - dwellMs);
  Serial.println(F("cycling: type x to stop"));
  slowTo(cal.zeroUs);
  uint32_t done = 0;
  while (n == 0 || done < n) {
    if (!moveTo(cal.targetUs, half)) break;
    delay(dwellMs);
    if (!moveTo(cal.zeroUs, half)) break;
    delay(dwellMs);
    cal.cycles++; done++;
    if (cal.cycles % 50 == 0) saveCal();                  // survive a power cut
    if (checkEvery && cal.cycles % checkEvery == 0) {
      Serial.print(F("cycle ")); Serial.print(cal.cycles); Serial.println(F(": at ZERO."));
      float deg = waitReading(F("read the resting angle, type r <deg> to log and continue"));
      Serial.print(F("LOG,cycle,")); Serial.print(cal.cycles); Serial.print(F(",rest_deg,"));
      if (isnan(deg)) Serial.print(F("")); else Serial.print(deg, 1);
      Serial.print(F(",ms,")); Serial.println(millis());
    }
  }
  slowTo(cal.zeroUs);
  saveCal();
  Serial.print(F("stopped at ")); Serial.print(cal.cycles); Serial.println(F(" cycles"));
}

// ---------------------------------------------------------------- step 4: spring-back
void springBack(unsigned long holdS) {
  if (cal.zeroUs == cal.targetUs) { Serial.println(F("calibrate z and t first")); return; }
  slowTo(cal.zeroUs);
  slowTo(cal.targetUs);
  Serial.print(F("holding at TARGET for ")); Serial.print(holdS); Serial.println(F(" s"));
  unsigned long t0 = millis();
  while (millis() - t0 < holdS * 1000UL) {
    if (Serial.available() && Serial.peek() == 'x') { Serial.read(); Serial.println(F("aborted")); return; }
    delay(50);
  }
  float held = waitReading(F("read the held angle: r <deg>"));
  Serial.print(F("LOG,springback,held,")); if (!isnan(held)) Serial.print(held, 1);
  Serial.print(F(",ms,")); Serial.println(millis());
  Serial.println(F("RELEASE NOW: pull the coupler pin (finger free). Type r when released."));
  waitReading(F("type r the moment it is released"));
  unsigned long tr = millis();
  servo.detach(); attached = false;              // the crank must not move while the pin is out
  const unsigned long marks[] = {1000UL, 10000UL, 60000UL, 600000UL};
  const char *labels[] = {"1s", "10s", "60s", "10min"};
  for (int i = 0; i < 4; i++) {
    while (millis() - tr < marks[i]) delay(10);
    Serial.print(F(">>> read the angle now (")); Serial.print(labels[i]); Serial.println(F(")"));
    float deg = waitReading(F("r <deg>"));
    Serial.print(F("LOG,springback,")); Serial.print(labels[i]); Serial.print(',');
    if (!isnan(deg)) Serial.print(deg, 1);
    Serial.print(F(",ms,")); Serial.println(millis() - tr);
  }
  Serial.println(F("done. Refit the pin, type e to re-attach, then 0 to go to ZERO."));
}

// ---------------------------------------------------------------- main
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  loadCal();
  posUs = clampUs(cal.zeroUs);
  attachIfNeeded();
  Serial.println(F("BARNES fatigue rig ready"));
  help();
}

void loop() {
  if (!Serial.available()) return;
  String s = readLine();
  if (!s.length()) return;
  String arg = s.substring(s.indexOf(' ') + 1);
  bool hasArg = s.indexOf(' ') > 0;
  long v = hasArg ? arg.toInt() : 0;

  if (s == "?") help();
  else if (s == "p") printState();
  else if (s.startsWith("j") && hasArg) { slowTo(v); printState(); }
  else if (s == "++") { slowTo(posUs + 10 * stepUs); printState(); }
  else if (s == "--") { slowTo(posUs - 10 * stepUs); printState(); }
  else if (s == "+") { slowTo(posUs + stepUs); printState(); }
  else if (s == "-") { slowTo(posUs - stepUs); printState(); }
  else if (s.startsWith("s") && hasArg) { stepUs = constrain(v, 1, 200); printState(); }
  else if (s == "z") { cal.zeroUs = posUs; saveCal(); Serial.println(F("ZERO saved")); }
  else if (s == "t") { cal.targetUs = posUs; saveCal(); Serial.println(F("TARGET saved")); }
  else if (s.startsWith("a") && hasArg) { cal.targetDeg = v; saveCal(); printState(); }
  else if (s == "lo") { cal.loUs = posUs; saveCal(); Serial.println(F("low limit saved")); }
  else if (s == "hi") { cal.hiUs = posUs; saveCal(); Serial.println(F("high limit saved")); }
  else if (s == "L") { cal.loUs = US_MIN; cal.hiUs = US_MAX; saveCal(); Serial.println(F("limits reset")); }
  else if (s == "0") slowTo(cal.zeroUs);
  else if (s == "T") slowTo(cal.targetUs);
  else if (s.startsWith("c")) runCycles(hasArg ? (uint32_t)v : 0);
  else if (s.startsWith("f") && hasArg) { cycleMs = max(600L, v); printState(); }
  else if (s.startsWith("w") && hasArg) { dwellMs = constrain(v, 0, 5000); printState(); }
  else if (s.startsWith("k") && hasArg) { checkEvery = max(0L, v); printState(); }
  else if (s == "n") { cal.cycles = 0; saveCal(); Serial.println(F("cycle count reset")); }
  else if (s.startsWith("h") && hasArg) springBack((unsigned long)v);
  else if (s == "d") { servo.detach(); attached = false; Serial.println(F("detached")); }
  else if (s == "e") { attachIfNeeded(); Serial.println(F("attached")); }
  else if (s == "x") { slowTo(cal.zeroUs); }
  else Serial.println(F("? for help"));
}
