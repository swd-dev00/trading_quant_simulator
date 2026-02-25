# Evolé Base — Technical Feasibility & Architecture Document
**Version:** 0.2.0 — aligned to architecture diagram
**Naming:** *Evolé* (confirmed from architecture diagram; prior draft used "Elevé" — now corrected throughout)

---

## 1. Architecture Overview

Power and signal flow (top-down per diagram):

```
Recharge/Dock
  (Magnetic Dock  ──┐
   Hidden USB-C)    │
        │           ▼
        └──► Charge + Power Mgmt
                    │
         ┌──────────▼──────────┐
         │   MCU / Intelligent  │◄── Temp Sensor
         │        Core          │
         └──────────┬──────────┘
                    │
            Atomization Driver
           (MOSFET + PWM layer)
                    │
         Diffuser / Nozzle Module
          (physical output stage)
                    │
        Sealed Ampoule Interface
         (mechanical docking layer)
                    │
          Fragrance Ampoule
                    │
          NFC Tag ◄──► NFC Reader/Antenna
```

### Why the driver and diffuser are separate subsystems

The **Atomization Driver** is pure electronics: MOSFET gate drive, PWM signal,
overcurrent protection, soft-start ramp.  The **Diffuser/Nozzle Module** is the
physical output stage: nozzle geometry, twist-ring encoder, proximity sensor,
aerosol plume characteristics.  Separating these concerns allows independent
hardware revision of the PCB (driver) without re-tooling the nozzle assembly (diffuser),
and vice versa.

---

## 2. Subsystem Feasibility Assessment

### 2.1 Charge + Power Management

| Item | Approach | Feasibility |
|------|----------|-------------|
| Magnetic dock | Pogo-pin or inductive Qi-adjacent pad | ✅ Proven in luxury wearables |
| USB-C fallback | VBUS detect → charger IC handoff | ✅ Standard |
| BMS IC | BQ25895 or similar 1-cell Li-Po charger | ✅ COTS |
| SOC estimation | Voltage-to-SOC curve (±5 % accuracy) | ✅ Sufficient for luxury UX |
| Regulated rails | 3.3 V (MCU/NFC/BLE) + 5 V (piezo driver) | ✅ LDO + boost combo |

**Low-battery behaviour:** atomization halts at 5 % SOC; BLE alert sent at 15 %.

---

### 2.2 Temperature Sensor → MCU Compensation

Ambient temperature directly affects fragrance **volatility** (evaporation rate
scales with temperature per Clausius–Clapeyron).  Without compensation, output
volume perception varies ±40 % across the 10–40 °C operating range.

**Compensation model (implemented in `temp_sensor.py`):**

| Temp (°C) | Duty multiplier | Effect |
|-----------|----------------|--------|
| 10 | 1.35× | colder room → more power to match perception |
| 20 | 1.00× | nominal reference |
| 30 | 0.77× | warmer → less power, natural volatility assists |
| 40 | 0.60× | hot environment → minimum drive to avoid over-diffusion |

**Sensor choice:** NTC thermistor (10 kΩ, B = 3950 K) read via 12-bit ADC divider.
Low cost, no I²C overhead. Alternative: SHT31 for combined temp+humidity (useful
for future humidity-aware compensation).

---

### 2.3 Atomization Driver (MOSFET + PWM)

- **Transducer type:** Piezoelectric micro-mesh (1.7 MHz ultrasonic).
  Produces 1–10 µm MMAD droplets — within inhalation-safe range, invisible mist.
- **Drive topology:** NMOS pull-down (3.3 V logic-level gate from MCU PWM GPIO)
  switching 5 V rail through piezo mesh.
- **Overcurrent threshold:** 250 mA (≈1.25 W at 5 V), hardware comparator as
  secondary protection beyond firmware check.
- **Soft-start/stop:** 150 ms ease-in-out cubic ramp in 20 steps — eliminates
  mechanical click (see `safety.py: SoftRamp`).

---

### 2.4 Diffuser / Nozzle Module

**Twist-ring (grinder-style) manual intensity adjustment:**
- 270° rotary encoder on the outer collar.
- 5 discrete stops: OFF, LOW, MEDIUM, HIGH, BOOST (every 67.5°).
- Tactile detents at each stop (leaf spring on encoder disc).
- Maps directly to IntensityPreset → base duty cycle → MCU without app required.

**Proximity trigger:**
- IR emitter/detector pair, range ≈ 15 cm.
- Rising-edge only: hand approach starts a session; continuous presence does not re-fire.

**Nozzle orientations (factory or user-configurable cap):**
- UPWARD (default): mist column rises, distributes by convection.
- ANGLED_45: directional throw into room.
- DIFFUSE: porous sintered cap for omnidirectional dispersion.

---

### 2.5 Sealed Ampoule Interface

**Luxury insertion UX requirements:**
- Four N52 magnets in radial pattern guide angular alignment → audible "click".
- Hall-effect sensor on collar signals SEATED state to MCU.
- Spring-loaded stainless piercer pin penetrates silicone micro-stopper (3.2 mm neck).
- Elastomer re-seals on ejection (tested ≥ 100 cycles without fragrance bleed).
- Ejection: shape-memory alloy actuator or small solenoid partially lifts ampoule for grip.

**UV-blocking outer vessel:**
- Borosilicate glass + TiO₂/SiO₂ vacuum-deposited multilayer coating.
- Target: < 1 % UV-A/B transmission while maintaining glass visual clarity.

---

### 2.6 Fragrance Ampoule + NFC Tag

**Ampoule physical spec:**
- 18 mm outer diameter, 60 mm height — tall-thin luxury silhouette.
- Micro-neck 3.2 mm to matched piercer.
- Fill volume: 2 mL (≈ 20,000 µL) target → ~200 sessions at 0.1 mL/session.

**NFC tag (ISO 15693 / NFC-V, e.g. ST25DV64K):**

Encoded fields per ampoule:
| Field | Size | Purpose |
|-------|------|---------|
| UID | 8 B | Device-unique, used in auth HMAC |
| SKU | 16 B | Product code |
| Scent name | 32 B | Human-readable |
| Scent family | 1 B | Enum index |
| Concentration % | 4 B (float32) | Oil/carrier ratio |
| Fill volume µL | 4 B (float32) | Total at manufacture |
| Remaining µL | 4 B (float32) | Updated by MCU each session |
| Auth signature | 16 B | HMAC-MD5 (upgrade to HMAC-SHA256 in v2) |

**Authentication flow:**
1. MCU reads UID + payload via NFC IC (I²C bridge).
2. Recomputes HMAC over (UID ‖ SKU ‖ fill_volume_ul) with device-class key.
3. Compares to stored signature. Mismatch → `NFCAuthError`, atomization blocked.

**Anti-counterfeit note:** HMAC-MD5 is adequate for MVP; v2 should use per-device
keys from a secure element (e.g. ATECC608B) and HMAC-SHA256.

---

## 3. Graceful Physicality — Microfluidic Health Logic

### 3.1 Prime-and-Purge Routine

Triggered on: first use after manufacture, cartridge replacement, or > 7 days idle.

```
12 × (50 ms ON / 20 ms OFF) × 3 cycles, with 500 ms inter-cycle pause
Total: ~4 seconds, imperceptible mist, clears air voids in micro-channels.
```

### 3.2 Viscosity Compensation

Fragrance oil viscosity ranges from ≈ 5 mPa·s (thin citrus carrier) to ≈ 50 mPa·s
(heavy oriental base).  Hagen–Poiseuille scaling:

```
on_time_adjusted = on_time_reference × (µ_sample / µ_reference)
```

Calibrated reference: 10 mPa·s @ 100 ms on-time → 0.10 mL dose.
Per-cartridge µ stored on NFC tag; compensated at session start.

### 3.3 Anti-Clogging Stealth Pulse

After 48 h of inactivity: 3 × (8 ms ON / 2000 ms OFF).
8 ms is below the aerosol generation threshold but sufficient to re-wet the
piezo mesh and prevent resin polymerisation in the nozzle capillaries.

---

## 4. User-Centric Features

### 4.1 Intensity Grade Scale (1–10 → PWM)

| Grade | Duty % | Perception |
|-------|--------|-----------|
| 1 | 8 % | Barely perceptible — background trace |
| 3 | 22 % | Subtle everyday (Deep Work default) |
| 5 | 43 % | Moderate room fill |
| 7 | 65 % | Strong, large space |
| 10 | 93 % | Near-maximum output |

Non-linear curve: lower grades compressed for perceptual uniformity.

### 4.2 Lifestyle Scenes

| Scene | Grade | Session | Rest | Schedule |
|-------|-------|---------|------|---------|
| Deep Work | 3 | 30 min | 30 min | 09:00, 13:00 |
| Date Night | 6 | 10 min | 20 min | 19:30 |
| Gym Refresh | 8 | 5 min | 10 min | 06:30, 18:00 |
| Morning Ritual | 4 | 15 min | 60 min | 07:00 |
| Wind Down | 2 | 45 min | 120 min | 21:30 |
| Guest Mode | 5 | 15 min | 15 min | manual |

Scenes activated via BLE (app tap) or by holding twist-ring at BOOST for 3 s
(cycles through scene list with LED feedback).

### 4.3 Smart Boost

- Instant 30-second spray at grade 9.
- 5-minute cooldown prevents nozzle flooding.
- Does not modify the active scene schedule.
- Triggered: physical button, app tap, or BLE `BOOST_TRIGGER` characteristic write.

---

## 5. Safety Layer

### 5.1 Predictive Low-Juice Alert

- Pulse-count based (not time-based) to survive power cycles.
- Remaining µL decremented per pulse: `flow_rate × duty × pulse_duration`.
- Alert at 10 % remaining → BLE notification + LED amber blink.
- Halt at 0 % → DryFireGuard prevents dry mesh burn.

### 5.2 Soft-Start / Soft-Stop

150 ms ease-in-out cubic ramp in 20 PWM steps.
Eliminates inductive snap and piezo ring-down click.
Makes the device feel "magical" — no mechanical tell.

### 5.3 Dry-Fire Guard

Dual detection:
- **Volume exhaustion:** JuiceMonitor reports 0 µL → halt.
- **Current anomaly:** drive current drops below 30 mA during active session
  (dry mesh draws less current than wetted) → halt + `DRIVER_FAULT` alert.

---

## 6. BLE Connectivity

**Protocol:** BLE 5.0, GATT peripheral role, custom service UUID `0xEA10`.
**Advertising interval:** 100 ms (fast discovery without significant battery impact).
**Telemetry push rate:** every 2 s while connected (not polled).

Key characteristics:

| UUID | Direction | Purpose |
|------|-----------|---------|
| EA10:0001 | Notify | Battery SOC |
| EA10:0003 | Notify | Ampoule remaining µL |
| EA10:0101 | Write | Scene select |
| EA10:0102 | Write | Intensity grade (1–10) |
| EA10:0103 | Write | Boost trigger |
| EA10:0301 | Indicate | Alerts (low battery, empty ampoule, fault) |

**Power budget (BLE):** ~6 mA peak during connection events; < 0.5 mA average
in advertising-only state with 100 ms interval.

---

## 7. Open Questions / v2 Roadmap

1. **Naming confirmed:** "Evolé" is the product name going forward. "Elevé" references in prior documents are superseded.
2. **NFC auth upgrade:** HMAC-SHA256 with per-device key via secure element (ATECC608B) for v2.
3. **Humidity sensing:** SHT31 replaces NTC for combined temp+humidity compensation.
4. **Cloud scent AI:** Usage telemetry (scenes, grades, session frequency) → anonymised
   aggregation → ML-based scent recommendation engine.
5. **Multi-ampoule mixing:** Dual-slot mechanical interface with independent drivers
   for blended fragrance profiles (hardware scope increase for v3).
6. **Twist-ring encoder type:** Decide between potentiometer (continuous, simpler firmware)
   vs. incremental encoder (no wear, requires index calibration at boot).
