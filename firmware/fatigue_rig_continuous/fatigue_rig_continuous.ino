/*
  BARNES Type B automated bending rig, CONTINUOUS-ROTATION servo version (step 5: cycles)
  --------------------------------------------------------------------------------------
  Hardware: Arduino Uno/Nano; continuous-rotation ("360") MG995 on the crank, signal on pin 9.
            Power the servo from its own 5-6 V supply (>= 2 A), GND joined to the Arduino GND.
  Optional but recommended: a once-per-turn sensor on the crank, on pin 2 (to GND when
            triggered): a micro-switch the crank presses, or a hall sensor (A3144) with a small
            magnet on the crank, placed where the FINGER IS AT 0 deg. With it the sketch counts
            every turn exactly and parks the finger at 0 deg. Without it, it counts by time.
  Serial:   115200 baud, line ending "Newline".

  WHAT A CONTINUOUS SERVO CAN AND CANNOT DO
  * The crank turns all the way round, so every cycle is the linkage's FULL rocker swing (about
    88-90 deg with crank 30 / coupler 106 / rocker 43.2 mm). Speed is all you control: the swing
    cannot be made smaller in code. H reaches 74 deg and B 78 deg before the collars meet, so a
    90 deg swing forces them past that. Shorten the crank (about 21.5 mm centre to centre for a
    60 deg swing) or check the swing in the motion study first.
  * It has no idea of its position: without the sensor it can only estimate turns from time,
    and it cannot hold an angle (step 4 stays manual).

  Commands:
    ?  /  p        help / status
    v <us>         run pulse width: 1500 = stop; e.g. 1600 slow one way, 1400 the other way.
                   Default 1600. Keep it slow (0.5-1 turn per second).
    stop <us>      the pulse width at which YOUR servo stands still (default 1500): try
                   'go', then adjust with 'stop 1490' etc. until it does not creep with 'halt'
    go / halt      run continuously / stop (for setting up)
    P <ms>         time for one crank turn in ms (no-sensor mode: time 10 turns with a
                   stopwatch while 'go' is running, divide by 10, enter it)
    sensor <0|1>   use the pin-2 sensor (1, default) or count by time (0)
    c <n>          run n cycles (0 = until 'x'); one cycle = one crank turn
    k <n>          stop at 0 deg every n cycles for a resting-angle reading (default 100, 0 = never);
                   type  r <deg>  to log it and continue, or  r  to continue
    x              stop (at the next 0 deg with the sensor)
    n              reset the cycle counter
  Output:  LOG,cycle,<n>,rest_deg,<deg>,ms,<millis>
*/

#include <Servo.h>
#include <EEPROM.h>

const uint8_t SERVO_PIN = 9, SENSOR_PIN = 2;

struct Cfg { uint16_t magic; int runUs, stopUs; unsigned long periodMs; uint8_t useSensor; uint32_t cycles; };
const uint16_t MAGIC = 0xC0A2;
Cfg cfg;
Servo servo;
uint32_t checkEvery = 100;

void saveCfg() { EEPROM.put(0, cfg); }
void loadCfg() {
  EEPROM.get(0, cfg);
  if (cfg.magic != MAGIC) { cfg = {MAGIC, 1600, 1500, 1500UL, 1, 0}; saveCfg(); }
}

void runMotor()  { servo.writeMicroseconds(cfg.runUs); }
void haltMotor() { servo.writeMicroseconds(cfg.stopUs); }

bool sensorActive() { return digitalRead(SENSOR_PIN) == LOW; }

// wait for the next sensor edge (inactive -> active), with debounce; false on timeout or 'x'
bool waitTurn(bool &stopReq) {
  unsigned long t0 = millis(), tmo = cfg.periodMs * 3UL + 2000UL;
  if (!cfg.useSensor) {
    while (millis() - t0 < cfg.periodMs) {
      if (Serial.available() && Serial.peek() == 'x') { Serial.read(); stopReq = true; }
      delay(5);
    }
    return true;
  }
  // leave the switch first, then wait for it to close again
  while (sensorActive()) { if (millis() - t0 > tmo) return false; delay(2); }
  unsigned long minGap = cfg.periodMs / 3;
  while (true) {
    if (Serial.available() && Serial.peek() == 'x') { Serial.read(); stopReq = true; }
    if (millis() - t0 > tmo) return false;
    if (sensorActive() && millis() - t0 > minGap) {
      delay(3);
      if (sensorActive()) return true;
    }
    delay(1);
  }
}

String readLine() {
  while (!Serial.available()) {}
  String s = Serial.readStringUntil('\n');
  s.trim();
  return s;
}

void status() {
  Serial.print(F("run ")); Serial.print(cfg.runUs); Serial.print(F(" us | stop ")); Serial.print(cfg.stopUs);
  Serial.print(F(" us | turn ")); Serial.print(cfg.periodMs); Serial.print(F(" ms | sensor "));
  Serial.print(cfg.useSensor ? F("on") : F("off (counting by time)"));
  Serial.print(F(" | cycles ")); Serial.print(cfg.cycles);
  Serial.print(F(" | check every ")); Serial.println(checkEvery);
}

void runCycles(uint32_t n) {
  Serial.println(F("running: type x to stop"));
  bool stopReq = false;
  uint32_t done = 0;
  runMotor();
  if (cfg.useSensor) {                       // line up on the 0-deg mark first
    if (!waitTurn(stopReq)) { haltMotor(); Serial.println(F("no sensor signal: check wiring or 'sensor 0'")); return; }
  }
  unsigned long tPrev = millis();
  while (!stopReq && (n == 0 || done < n)) {
    if (!waitTurn(stopReq)) { haltMotor(); Serial.println(F("sensor timeout: stalled or jammed? stopped")); break; }
    unsigned long now = millis();
    if (cfg.useSensor) cfg.periodMs = (cfg.periodMs * 7 + (now - tPrev)) / 8;   // track the real speed
    tPrev = now;
    cfg.cycles++; done++;
    if (cfg.cycles % 50 == 0) saveCfg();
    if (checkEvery && cfg.cycles % checkEvery == 0) {
      haltMotor();
      Serial.print(F("cycle ")); Serial.print(cfg.cycles);
      Serial.println(cfg.useSensor ? F(": parked at 0 deg. r <deg> to log and continue")
                                   : F(": stopped (position approximate). r <deg> to log and continue"));
      String s;
      do { s = readLine(); } while (!(s.length() && s[0] == 'r'));
      s = s.substring(1); s.trim();
      Serial.print(F("LOG,cycle,")); Serial.print(cfg.cycles); Serial.print(F(",rest_deg,"));
      if (s.length()) Serial.print(s.toFloat(), 1);
      Serial.print(F(",ms,")); Serial.println(millis());
      runMotor();
      tPrev = millis();
    }
  }
  haltMotor();
  saveCfg();
  Serial.print(F("stopped at ")); Serial.print(cfg.cycles); Serial.println(F(" cycles"));
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  pinMode(SENSOR_PIN, INPUT_PULLUP);
  loadCfg();
  servo.attach(SERVO_PIN, 500, 2500);
  haltMotor();
  Serial.println(F("BARNES fatigue rig (continuous servo) ready"));
  Serial.println(F("v <us> | stop <us> | go | halt | P <ms> | sensor 0/1 | c <n> | k <n> | x | n | p"));
  status();
}

void loop() {
  if (!Serial.available()) return;
  String s = readLine();
  if (!s.length()) return;
  bool hasArg = s.indexOf(' ') > 0;
  long v = hasArg ? s.substring(s.indexOf(' ') + 1).toInt() : 0;

  if (s == "?" || s == "p") status();
  else if (s.startsWith("v") && hasArg) { cfg.runUs = constrain(v, 500L, 2500L); saveCfg(); status(); }
  else if (s.startsWith("stop") && hasArg) { cfg.stopUs = constrain(v, 1300L, 1700L); haltMotor(); saveCfg(); status(); }
  else if (s == "go") runMotor();
  else if (s == "halt" || s == "x") haltMotor();
  else if (s.startsWith("P") && hasArg) { cfg.periodMs = max(200L, v); saveCfg(); status(); }
  else if (s.startsWith("sensor") && hasArg) { cfg.useSensor = v ? 1 : 0; saveCfg(); status(); }
  else if (s.startsWith("c")) runCycles(hasArg ? (uint32_t)v : 0);
  else if (s.startsWith("k") && hasArg) { checkEvery = max(0L, v); status(); }
  else if (s == "n") { cfg.cycles = 0; saveCfg(); Serial.println(F("cycle count reset")); }
  else Serial.println(F("? for help"));
}
