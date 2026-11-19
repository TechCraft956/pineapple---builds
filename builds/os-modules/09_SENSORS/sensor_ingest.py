#!/usr/bin/env python3
"""
PINEAPPLE OS - 09_SENSORS - Sensor / ESP32 ingest layer (physical-world base).

The data model + interface for future ESP32 / IoT inputs around the RGV home:
garage door, motion, temp/humidity, water leak, vehicle/bike battery, freezer
temp, gate, mailbox.

It defines a Device schema and a Reading schema, provides ingest(reading) that
VALIDATES a reading and appends it to a local store, and items() that evaluates
each device's alert_rules against its latest readings and surfaces the ACTIVE
alerts (e.g. "Garage opened 5:13 AM", "Bike battery 11.8V low", "Water detected
near washer") as decision items with lat/lon for the map.

STATUS: sample. data/devices.json and data/readings.json are clearly-marked
SAMPLE data (realistic RGV coordinates, fabricated telemetry). No live network
is touched - this module is OFFLINE only. Real ESP32 nodes would POST/MQTT into
ingest(); see the INGEST ENDPOINTS doc block below (no ports are opened here).

Privacy: self-owned devices only. No third-party device data, no PII compilation
beyond the household's own sensors. Consent-aware by construction.

Run standalone:
    python sensor_ingest.py --selftest   # health summary, exit 0 on success
    python sensor_ingest.py              # pretty-print active alerts
    python sensor_ingest.py --json       # emit items() as JSON
    python sensor_ingest.py --export     # write alerts JSON to 00_PROCESSED

Pure Python 3.11 stdlib only. Windows host. UTF-8.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Paths. ROOT = Pineapple OS root. Output only goes to our folder or 00_PROCESSED.
# --------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
ROOT = MODULE_DIR.parent
DEVICES_PATH = MODULE_DIR / "data" / "devices.json"
READINGS_PATH = MODULE_DIR / "data" / "readings.json"
PROCESSED_DIR = ROOT / "00_PROCESSED"

# --------------------------------------------------------------------------
# FUTURE INGEST ENDPOINTS (documented only - NOTHING is opened/listened here).
#
# Real ESP32 / IoT nodes would push readings into ingest(). Two transports are
# planned; both validate via ingest() before the reading is appended to the
# local store, so the validation contract is identical regardless of transport.
#
#   1) HTTP POST (simplest for ESP32 HTTPClient / Arduino WiFiClientSecure):
#        POST http://<pineapple-host>:7777/api/sensors/ingest
#        Content-Type: application/json
#        Body: {"device_id":"esp32_garage_01","ts":"2026-06-26T05:13:00Z",
#               "metric":"state","value":"open"}
#        Server handler -> sensor_ingest.ingest(body, ingest_to_disk=True)
#        (pineapple_server.py owns the port; this module never binds a socket.)
#
#   2) MQTT (battery-friendly, many nodes, retained last-value):
#        Broker: Mosquitto on the LAN, e.g. mqtt://<pineapple-host>:1883
#        Topic:  pineapple/sensors/<device_id>/<metric>
#        Payload (JSON or bare value); a bridge subscriber maps the message to
#        {device_id, ts, metric, value} and calls sensor_ingest.ingest(...).
#        TLS + per-device username/token recommended; LAN-only, no cloud relay.
#
# Security / consent posture for the live wiring (not active now):
#   - LAN-only, no inbound from the public internet; auth token per device.
#   - Self-owned sensors only; never ingest a neighbor's / third party's device.
#   - Reject readings whose device_id is not in the local registry (devices.json).
# --------------------------------------------------------------------------

# Canonical sensor types this layer understands.
SENSOR_TYPES = (
    "garage_door", "motion", "temp_humidity", "water_leak",
    "battery", "freezer_temp", "gate", "mailbox",
)

# Device schema: keys every registered device MUST carry.
DEVICE_REQUIRED = (
    "device_id", "owner", "location", "sensor_type",
    "last_seen", "battery", "lat", "lon", "alert_rules",
)

# Reading schema: keys every ingested reading MUST carry.
READING_REQUIRED = ("device_id", "ts", "metric", "value")

# Comparison operators allowed in an alert_rule.
_OPS = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "ge": lambda a, b: a >= b,
    "le": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "change_to": lambda a, b: _norm(a) == _norm(b),  # state/door reached value b
}

_SEVERITY_RANK = {"LOW": 0, "MED": 1, "HIGH": 2}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _norm(v):
    """Lowercased, stripped string form for state/string comparisons."""
    return str(v).strip().lower()


def _num(v):
    """Best-effort float; None if not numeric (string states stay strings)."""
    if isinstance(v, bool):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_clock(ts: str) -> str:
    """ISO ts -> '5:13 AM' style local-ish label (no tz math; display only)."""
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.strftime("%-I:%M %p") if sys.platform != "win32" else dt.strftime("%#I:%M %p")
    except Exception:
        return ts


# --------------------------------------------------------------------------
# Loading + validation
# --------------------------------------------------------------------------
def load_devices(path: Path = DEVICES_PATH) -> dict:
    """Load device registry -> {device_id: device_dict}. Validates Device schema."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    devs = doc.get("devices")
    if not isinstance(devs, list) or not devs:
        raise ValueError("devices.json has no 'devices' list")
    out = {}
    for i, d in enumerate(devs):
        missing = [k for k in DEVICE_REQUIRED if k not in d]
        if missing:
            raise ValueError("device %d (%s) missing keys: %s"
                             % (i, d.get("device_id", "?"), missing))
        if d["sensor_type"] not in SENSOR_TYPES:
            raise ValueError("device %s has unknown sensor_type %r"
                             % (d["device_id"], d["sensor_type"]))
        if not isinstance(d["alert_rules"], list):
            raise ValueError("device %s alert_rules must be a list" % d["device_id"])
        out[d["device_id"]] = d
    return out


def load_readings(path: Path = READINGS_PATH) -> list:
    """Load the append-only readings store as a list of reading dicts."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    rds = doc.get("readings", [])
    if not isinstance(rds, list):
        raise ValueError("readings.json 'readings' must be a list")
    return rds


def validate_reading(reading: dict, devices: dict | None = None) -> dict:
    """
    Validate a single reading against the Reading schema (and, if a device
    registry is supplied, against the known device_id). Returns a normalized
    copy. Raises ValueError on any violation.
    """
    if not isinstance(reading, dict):
        raise ValueError("reading must be a dict")
    missing = [k for k in READING_REQUIRED if k not in reading]
    if missing:
        raise ValueError("reading missing keys: %s" % missing)

    device_id = reading["device_id"]
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("device_id must be a non-empty string")
    metric = reading["metric"]
    if not isinstance(metric, str) or not metric:
        raise ValueError("metric must be a non-empty string")

    ts = reading["ts"]
    if not isinstance(ts, str) or not ts:
        raise ValueError("ts must be a non-empty ISO-8601 string")
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception as e:
        raise ValueError("ts is not valid ISO-8601: %r (%s)" % (ts, e))

    value = reading["value"]
    if not isinstance(value, (int, float, str, bool)):
        raise ValueError("value must be number, string, or bool")

    if devices is not None and device_id not in devices:
        # Self-owned-only / consent posture: reject unregistered devices.
        raise ValueError("unknown device_id %r (not in registry)" % device_id)

    return {"device_id": device_id, "ts": ts, "metric": metric, "value": value}


# --------------------------------------------------------------------------
# ingest() - VALIDATE + append to the local store
# --------------------------------------------------------------------------
def ingest(reading: dict,
           store: list | None = None,
           devices: dict | None = None,
           ingest_to_disk: bool = False,
           readings_path: Path = READINGS_PATH) -> dict:
    """
    Validate `reading` and append it to a local readings store.

    - In-memory by default: pass `store` (a list) to accumulate; if omitted, a
      throwaway list is used. Nothing is written to disk unless ingest_to_disk.
    - ingest_to_disk=True appends to data/readings.json (our own folder only).
    - `devices`: optional registry; when provided, unknown device_ids are
      rejected (consent / self-owned-only posture).

    Returns {"ok": bool, "stored": <normalized reading>|None, "error": str|None,
             "count": <store length>}.
    """
    if devices is None:
        try:
            devices = load_devices()
        except Exception:
            devices = None  # validation can still run sans registry check
    try:
        norm = validate_reading(reading, devices=devices)
    except ValueError as e:
        return {"ok": False, "stored": None, "error": str(e),
                "count": (len(store) if store is not None else 0)}

    if store is None:
        store = []
    store.append(norm)

    if ingest_to_disk:
        doc = {"_status": "sample", "readings": []}
        if readings_path.exists():
            with open(readings_path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            doc.setdefault("readings", [])
        doc["readings"].append(norm)
        readings_path.parent.mkdir(parents=True, exist_ok=True)
        readings_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    return {"ok": True, "stored": norm, "error": None, "count": len(store)}


# --------------------------------------------------------------------------
# Alert evaluation
# --------------------------------------------------------------------------
def _latest_by_metric(device_id: str, readings: list) -> dict:
    """Latest reading per metric for a device -> {metric: reading}."""
    latest = {}
    for r in readings:
        if r.get("device_id") != device_id:
            continue
        m = r.get("metric")
        if m not in latest or r.get("ts", "") >= latest[m].get("ts", ""):
            latest[m] = r
    return latest


def _rule_fires(rule: dict, reading: dict) -> bool:
    op = _OPS.get(rule.get("op"))
    if op is None:
        return False
    thr = rule.get("threshold")
    val = reading.get("value")
    if rule.get("op") in ("change_to",):
        return op(val, thr)
    # numeric comparison when possible, else string compare
    nv, nt = _num(val), _num(thr)
    if nv is not None and nt is not None:
        return op(nv, nt)
    try:
        return op(val, thr)
    except TypeError:
        return False


def active_alerts(devices: dict | None = None, readings: list | None = None) -> list:
    """
    Evaluate every device's alert_rules against its latest readings.
    Returns a list of alert dicts (one per firing rule), each carrying the
    device, rule, the triggering reading, severity, and lat/lon.
    """
    if devices is None:
        devices = load_devices()
    if readings is None:
        readings = load_readings()

    alerts = []
    for device_id, dev in devices.items():
        latest = _latest_by_metric(device_id, readings)
        for rule in dev.get("alert_rules", []):
            metric = rule.get("metric")
            reading = latest.get(metric)
            if reading is None:
                continue
            if _rule_fires(rule, reading):
                alerts.append({
                    "device_id": device_id,
                    "sensor_type": dev["sensor_type"],
                    "location": dev["location"],
                    "lat": dev["lat"],
                    "lon": dev["lon"],
                    "battery": dev.get("battery"),
                    "metric": metric,
                    "value": reading["value"],
                    "ts": reading["ts"],
                    "severity": rule.get("severity", "MED"),
                    "message": rule.get("message", "Alert"),
                    "threshold": rule.get("threshold"),
                })
    return alerts


# --------------------------------------------------------------------------
# items() - decision-engine feed
# --------------------------------------------------------------------------
_SENSOR_HINT = {
    "garage_door": "Verify garage is meant to be open; close it if not.",
    "gate": "Confirm gate access is expected; secure if unexpected.",
    "mailbox": "Mail likely delivered - collect when convenient.",
    "motion": "Review camera/footage for the driveway event.",
    "water_leak": "Shut off supply and inspect for a leak immediately.",
    "freezer_temp": "Check freezer seal/power before contents thaw.",
    "battery": "Charge/replace the battery before it fails to start.",
    "temp_humidity": "Check HVAC / ventilation load at this location.",
}


def items() -> list:
    """Active sensor alerts shaped as Pineapple decision items, ranked by severity."""
    devices = load_devices()
    readings = load_readings()
    alerts = active_alerts(devices, readings)

    out = []
    for a in alerts:
        sev = a["severity"]
        risk = sev if sev in ("LOW", "MED", "HIGH") else "MED"
        clock = _fmt_clock(a["ts"])
        # e.g. "Garage opened 5:13 AM", "Bike battery 11.8V low"
        val = a["value"]
        if a["metric"] == "volts":
            title = "%s (%sV) - %s" % (a["message"], val, clock)
        elif a["metric"] == "temp_f":
            title = "%s (%s°F) - %s" % (a["message"], val, clock)
        elif a["metric"] in ("state", "door"):
            title = "%s - %s" % (a["message"], clock)
        elif a["metric"] == "open_minutes":
            title = "%s (%s min) - %s" % (a["message"], val, clock)
        else:
            title = "%s - %s" % (a["message"], clock)

        hint = _SENSOR_HINT.get(a["sensor_type"], "Check the device.")
        out.append({
            "title": title,
            "category": "RISKS",
            "source": "ESP32/IoT sensor layer (sample; LAN ingest to wire)",
            "action": "%s Device %s at %s." % (hint, a["device_id"], a["location"]),
            "est_value": None,  # safety/time signal, not a dollar opportunity
            "risk": risk,
            "location": a["location"],
            "url": "http://localhost:7777/api/sensors/ingest",  # planned LAN endpoint
            "confidence": 0.5,  # sample telemetry
            # extras (map + downstream ranking; ignored by engine if unknown)
            "lat": a["lat"],
            "lon": a["lon"],
            "device_id": a["device_id"],
            "sensor_type": a["sensor_type"],
            "metric": a["metric"],
            "value": a["value"],
            "ts": a["ts"],
            "severity": sev,
            "battery": a["battery"],
        })

    # Highest-leverage first: severity desc, then most recent reading.
    out.sort(key=lambda d: (_SEVERITY_RANK.get(d["severity"], 1), d["ts"]),
             reverse=True)
    return out


# --------------------------------------------------------------------------
# Export - writes only to 00_PROCESSED
# --------------------------------------------------------------------------
def export_alerts(out_dir: Path = PROCESSED_DIR) -> Path:
    """Write current active-alert items as JSON to 00_PROCESSED."""
    payload = {
        "module": PLUGIN["id"],
        "_status": "sample",
        "generated": datetime.now(timezone.utc).isoformat(),
        "count": None,
        "items": items(),
    }
    payload["count"] = len(payload["items"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sensors_alerts_items.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------
# PLUGIN descriptor
# --------------------------------------------------------------------------
PLUGIN = {
    "id": "sensors_esp32_ingest",
    "name": "Sensor / ESP32 Ingest Layer (RGV)",
    "category": "RISKS",
    "authority": "household",
    "status": "sample",
    "inputs": [
        "data/devices.json (Device registry: device_id, owner, location, "
        "sensor_type, last_seen, battery, lat, lon, alert_rules)",
        "data/readings.json (append-only Reading store: device_id, ts, metric, value)",
        "ingest(reading) - validated runtime readings (future HTTP POST / MQTT)",
    ],
    "outputs": [
        "ingest(reading) -> {ok, stored, error, count}",
        "active_alerts() -> firing rules with lat/lon",
        "items() active sensor alerts as decision items",
        "00_PROCESSED/sensors_alerts_items.json",
    ],
    "sources": [
        "https://www.espressif.com/en/products/socs/esp32",
        "https://docs.espressif.com/projects/arduino-esp32/en/latest/",
        "https://mqtt.org/",
        "https://mosquitto.org/",
        "https://www.home-assistant.io/integrations/esphome/",
        "https://esphome.io/",
    ],
    "safety": "Read-only toward the user; OFFLINE. Ships clearly-marked SAMPLE "
              "devices/readings (fabricated telemetry). Self-owned sensors only - "
              "no third-party device data, no PII compilation, consent-aware. No "
              "network ports are opened by this module; future LAN HTTP/MQTT ingest "
              "is documented only. Do not treat sample alerts as real events.",
}


# --------------------------------------------------------------------------
# CLI / selftest
# --------------------------------------------------------------------------
def selftest() -> int:
    try:
        # 1. files parse
        devices = load_devices()
        readings = load_readings()
        assert len(devices) >= 8, "expected >=8 devices, got %d" % len(devices)
        assert len(readings) >= 8, "expected >=8 readings, got %d" % len(readings)

        # 2. sensor-type coverage (all 8 physical channels present)
        types = {d["sensor_type"] for d in devices.values()}
        for t in SENSOR_TYPES:
            assert t in types, "missing sensor_type coverage: %s" % t

        # 3. ingest() accepts a valid reading (in-memory)
        store = []
        ok = ingest({"device_id": "esp32_garage_01", "ts": "2026-06-26T06:00:00Z",
                     "metric": "state", "value": "closed"},
                    store=store, devices=devices)
        assert ok["ok"] and ok["count"] == 1, "valid ingest failed: %s" % ok

        # 4. ingest() rejects bad readings
        bad_missing = ingest({"device_id": "x", "metric": "m"}, store=store, devices=devices)
        assert not bad_missing["ok"], "missing-keys reading not rejected"
        bad_ts = ingest({"device_id": "esp32_garage_01", "ts": "not-a-date",
                         "metric": "state", "value": "open"}, store=store, devices=devices)
        assert not bad_ts["ok"], "bad ts not rejected"
        bad_dev = ingest({"device_id": "esp32_unknown_99", "ts": "2026-06-26T06:00:00Z",
                          "metric": "state", "value": "open"}, store=store, devices=devices)
        assert not bad_dev["ok"], "unknown device not rejected"

        # 5. items() contract
        its = items()
        assert len(its) >= 1, "expected at least one active alert"
        req = ("title", "category", "source", "action", "est_value",
               "risk", "location", "url", "confidence")
        for it in its:
            for k in req:
                assert k in it, "item missing key: %s" % k
            assert it["risk"] in ("LOW", "MED", "HIGH"), "bad risk: %s" % it["risk"]
            assert 0.0 <= it["confidence"] <= 1.0, "bad confidence"
            assert it["est_value"] is None or isinstance(it["est_value"], (int, float))
            # physical place => lat/lon present and in RGV range
            assert "lat" in it and "lon" in it, "item missing lat/lon"
            assert 25.0 < it["lat"] < 27.0, "lat out of RGV range: %s" % it["lat"]
            assert -99.5 < it["lon"] < -97.0, "lon out of RGV range: %s" % it["lon"]

        # 6. ranking: severity non-increasing
        ranks = [_SEVERITY_RANK.get(i["severity"], 1) for i in its]
        assert ranks == sorted(ranks, reverse=True), "items not ranked by severity"

        # 7. known sample alerts fire (garage open, water, low bike battery)
        msgs = " | ".join(i["title"] for i in its)
        assert "Garage" in msgs, "expected garage alert"
        assert "Water detected" in msgs, "expected water-leak alert"
        assert "11.8" in msgs, "expected bike-battery low-voltage alert"

        # 8. PLUGIN shape
        for k in ("id", "name", "category", "authority", "status",
                  "inputs", "outputs", "sources", "safety"):
            assert k in PLUGIN, "PLUGIN missing %s" % k
        assert PLUGIN["status"] == "sample"
        assert PLUGIN["sources"], "PLUGIN.sources empty"

        top = its[0]
        print("OK sensors_esp32_ingest selftest")
        print("  devices        : %d (%d sensor types)" % (len(devices), len(types)))
        print("  readings       : %d" % len(readings))
        print("  active alerts  : %d  (HIGH=%d MED=%d LOW=%d)" % (
            len(its),
            sum(1 for i in its if i["severity"] == "HIGH"),
            sum(1 for i in its if i["severity"] == "MED"),
            sum(1 for i in its if i["severity"] == "LOW")))
        print("  ingest accept/reject : 1 accepted, 3 rejected (as expected)")
        print("  top alert      : %s" % top["title"])
        return 0
    except Exception as e:
        print("FAIL sensors_esp32_ingest selftest: %s" % e)
        return 1


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sensor / ESP32 Ingest Layer (RGV)")
    ap.add_argument("--selftest", action="store_true", help="run health check, exit 0 on success")
    ap.add_argument("--json", action="store_true", help="emit items() as JSON")
    ap.add_argument("--export", action="store_true", help="write alerts JSON to 00_PROCESSED")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.export:
        p = export_alerts()
        print("wrote %s" % p)
        return 0
    if args.json:
        print(json.dumps(items(), indent=2))
        return 0

    its = items()
    print("Sensor / ESP32 Ingest Layer (RGV) - SAMPLE data")
    print("active alerts: %d" % len(its))
    print("-" * 72)
    for it in its:
        batt = "" if it["battery"] is None else (" batt %s%%" % it["battery"])
        print("[%-4s] %-26s %s%s" % (it["severity"], it["device_id"], it["title"], batt))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
