/*
  BARNES automated bending rig: tendon winch (+ optional HX711 load cell)
  ---------------------------------------------------------------------
  Driven by the PC program tools/auto_rig (run.py); you normally never type to it.

  Hardware
    Servo winch (OT5116M or any standard positional servo) signal -> pin 9.
      Servo power from its own 6 V supply (>= 3 A), GND joined to the Arduino GND.
    Optional HX711 load-cell amplifier: DT -> pin 3, SCK -> pin 4, VCC 5 V, GND.
      If no HX711 is fitted, force comes from the camera reading the scale's display.

  Serial 115200, newline-terminated commands; every command answers one line:
    P <us> <ms>     move to pulse width <us> over <ms> ms (smooth), answers  OK P <us>
    Q               answers  S <us> <grams|NA>
    T               tare the load cell                     -> OK T
    C <grams>       calibrate with a known weight hanging  -> OK C <factor>
    L <lo> <hi>     pulse-width limits (stored in EEPROM)  -> OK L
    D / A           detach (limp) / attach                 -> OK D / OK A
*/

#include <Servo.h>
#include <EEPROM.h>

const uint8_t SERVO_PIN = 9, HX_DT = 3, HX_SCK = 4;

struct Cfg { uint16_t magic; int lo, hi; float factor; long offset; };
const uint16_t MAGIC = 0xA17E;
Cfg cfg;
Servo servo;
int posUs = 1500;
bool hxPresent = false;

// ------------------------------------------------------------------ HX711 (bit-banged, gain 128)
bool hxReady() { return digitalRead(HX_DT) == LOW; }
long hxRaw() {
  unsigned long t0 = millis();
  while (!hxReady()) { if (millis() - t0 > 200) return LONG_MIN; }
  long v = 0;
  noInterrupts();
  for (uint8_t i = 0; i < 24; i++) {
    digitalWrite(HX_SCK, HIGH); delayMicroseconds(1);
    v = (v << 1) | digitalRead(HX_DT);
    digitalWrite(HX_SCK, LOW); delayMicroseconds(1);
  }
  digitalWrite(HX_SCK, HIGH); delayMicroseconds(1); digitalWrite(HX_SCK, LOW);   // gain 128
  interrupts();
  if (v & 0x800000L) v |= 0xFF000000L;   // sign-extend 24 bits
  return v;
}
long hxAvg(uint8_t n) {
  long s = 0; uint8_t k = 0;
  for (uint8_t i = 0; i < n; i++) { long r = hxRaw(); if (r != LONG_MIN) { s += r; k++; } }
  return k ? s / k : LONG_MIN;
}

// ------------------------------------------------------------------ motion
void moveTo(int us, unsigned long ms) {
  us = constrain(us, cfg.lo, cfg.hi);
  int from = posUs;
  if (!servo.attached()) servo.attach(SERVO_PIN, 500, 2500);
  if (ms < 20 || from == us) { posUs = us; servo.writeMicroseconds(us); return; }
  unsigned long t0 = millis();
  while (true) {
    unsigned long t = millis() - t0;
    if (t >= ms) break;
    float f = 0.5f - 0.5f * cos(PI * (float)t / (float)ms);
    posUs = from + (int)round((us - from) * f);
    servo.writeMicroseconds(posUs);
    delay(5);
  }
  posUs = us;
  servo.writeMicroseconds(us);
}

void save() { EEPROM.put(0, cfg); }

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(100);
  EEPROM.get(0, cfg);
  if (cfg.magic != MAGIC) { cfg = {MAGIC, 500, 2500, 420.0f, 0}; save(); }
  pinMode(HX_SCK, OUTPUT); digitalWrite(HX_SCK, LOW);
  pinMode(HX_DT, INPUT_PULLUP);
  unsigned long t0 = millis();
  while (millis() - t0 < 600) { if (hxReady()) { hxPresent = hxRaw() != LONG_MIN; break; } }
  posUs = constrain(1500, cfg.lo, cfg.hi);
  Serial.print(F("READY winch")); Serial.println(hxPresent ? F(" hx711") : F(" no-hx711"));
}

void loop() {
  if (!Serial.available()) return;
  String s = Serial.readStringUntil('\n');
  s.trim();
  if (!s.length()) return;
  char c = s[0];
  String a = s.substring(1); a.trim();
  if (c == 'P') {
    int sp = a.indexOf(' ');
    int us = (sp > 0 ? a.substring(0, sp) : a).toInt();
    long ms = sp > 0 ? a.substring(sp + 1).toInt() : 300;
    moveTo(us, ms);
    Serial.print(F("OK P ")); Serial.println(posUs);
  } else if (c == 'Q') {
    Serial.print(F("S ")); Serial.print(posUs); Serial.print(' ');
    if (!hxPresent) { Serial.println(F("NA")); return; }
    long r = hxAvg(4);
    if (r == LONG_MIN) Serial.println(F("NA"));
    else Serial.println((r - cfg.offset) / cfg.factor, 2);
  } else if (c == 'T') {
    long r = hxAvg(16);
    if (r != LONG_MIN) { cfg.offset = r; save(); }
    Serial.println(F("OK T"));
  } else if (c == 'C') {
    float g = a.toFloat();
    long r = hxAvg(16);
    if (g > 0 && r != LONG_MIN && r != cfg.offset) { cfg.factor = (r - cfg.offset) / g; save(); }
    Serial.print(F("OK C ")); Serial.println(cfg.factor, 4);
  } else if (c == 'L') {
    int sp = a.indexOf(' ');
    if (sp > 0) { cfg.lo = constrain(a.substring(0, sp).toInt(), 500, 2500);
                  cfg.hi = constrain(a.substring(sp + 1).toInt(), 500, 2500); save(); }
    Serial.println(F("OK L"));
  } else if (c == 'D') { servo.detach(); Serial.println(F("OK D")); }
  else if (c == 'A') { servo.attach(SERVO_PIN, 500, 2500); servo.writeMicroseconds(posUs); Serial.println(F("OK A")); }
  else Serial.println(F("ERR unknown"));
}
