"""Draw numbered circle+arrow callouts onto the captured screenshots.

Reads manual/shots/widgets.json for exact widget bboxes, draws capsule
outlines + numbered badges + arrows with PIL, writes manual/annotated/*.png
and manual/annotated/legends.json for the HTML builder.
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# Spec strings carry the buttons' emoji (📏, 💾). On a real Windows console
# they print fine, but with stdout REDIRECTED (a pipe, a CI log) Python falls
# back to the ANSI codepage with a strict encoder — and the miss report below
# would then crash before reaching its sys.exit(1). Escape what the stream
# cannot carry instead of dying on it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
from version import __version__  # noqa: E402  (repo root version.py)

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
SHOTS = os.path.join(BASE, "shots")
OUT = os.path.join(BASE, "annotated")
os.makedirs(OUT, exist_ok=True)

RED = (217, 48, 37)
WHITE = (255, 255, 255)
FONT = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 17)

manifest = json.load(open(os.path.join(SHOTS, "widgets.json"), encoding="utf-8"))
images = {img["name"]: img for img in manifest["images"]}

# Every (image, spec text) that matched no widget. The build FAILS on these
# at the end instead of shipping without them: a miss means the on-screen
# text= drifted from the spec (or the shots are stale), and the cost of
# ignoring it is a manual quietly missing a capsule and its legend row.
MISSES = []


def find(img, text):
    """Match a widget by text: exact -> ci -> startswith -> contains."""
    ws = img["widgets"]
    for match_fn in (
        lambda w: w["text"].strip() == text,
        lambda w: w["text"].strip().lower() == text.lower(),
        lambda w: w["text"].strip().startswith(text),
        lambda w: text in w["text"],
    ):
        hits = [w for w in ws if match_fn(w)]
        if hits:
            hits.sort(key=lambda w: (w["y"], w["x"]))
            return hits[0]
    return None


def resolve(img, spec):
    """Spec -> pixel rect [x, y, w, h] or None."""
    if "rect" in spec:
        return list(spec["rect"])
    texts = spec["union"] if "union" in spec else [spec["match"]]
    boxes = []
    for t in texts:
        w = find(img, t)
        if w is None:
            print(f"  !! no match for {t!r} in {img['name']}")
            MISSES.append((img["name"], t))
            continue
        boxes.append((w["x"], w["y"], w["x"] + w["w"], w["y"] + w["h"]))
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    x1 += spec.get("extend_right", 0)
    return [x0, y0, x1 - x0, y1 - y0]


# ---------------------------------------------------------------- specs
S = {}

S["overview"] = {
    "source": "01_LCR_Meter__BK_894_",
    "callouts": [
        {"match": "__tabstrip__", "label": "One tab per instrument or job — click to switch"},
        {"match": "Tools", "label": "Tools menu — bench profiles & software update"},
        {"match": "Linux bench only -- view/edit (presets OK)",
         "label": "Connection status — green once the instrument answers (amber on Windows)"},
        {"match": "Reconnect", "label": "Re-detects this one instrument after power-on or replug"},
        {"match": "Non-Linux platform", "badge_side": "top",
         "label": "Status bar — confirmations and warnings appear here"},
        {"match": f"v{__version__}", "label": "Exact version — quote it when reporting a problem"},
    ],
}

S["01_LCR_Meter__BK_894_"] = {
    "callouts": [
        {"match": "Mode:", "extend_right": 195, "label": "Measurement pair — CPD = capacitance + dissipation"},
        {"union": ["Frequency (Hz):", "Voltage (V):"], "extend_right": 160,
         "label": "AC test signal — meter clamps at 2.0 V and 500 kHz"},
        {"union": ["Open Correction...", "Short Correction..."],
         "label": "Fixture zeroing — redo both after changing fixture or leads"},
        {"match": "Apply Configuration", "label": "Nothing reaches the meter until you click this"},
        {"union": ["Single Measurement", "Start Continuous"],
         "label": "One reading now, or live readings every 0.2 s"},
        {"match": "Sweep (freq × voltage × dwell)",
         "label": "Automated frequency × voltage sweep — define both axes here"},
        {"match": "Start Sweep", "label": "Runs the sweep in the background → CSV file"},
    ],
}

S["02_Oscilloscope__MSO24_"] = {
    "callouts": [
        {"rect": [24, 179, 244, 26], "badge_side": "right",
         "label": "Per-channel setup — one inner tab per channel (CH1–CH4)"},
        {"match": "Use as trigger:", "extend_right": 60, "badge_side": "right",
         "label": "Tick the channel that should trigger acquisition"},
        {"match": "Apply CH1 Config", "label": "Sends this channel only — does not touch the trigger"},
        {"match": "Apply All Settings", "label": "The only button that sends trigger source, level and slope"},
        {"match": "Get CH1 Measurements", "badge_at": [160, 634],
         "label": "Readouts are snapshots — click to refresh"},
        {"match": "Capture CH1 Waveform", "label": "Pulls the trace into a plot window with Save CSV"},
        {"match": "Acquisition Control", "label": "Run / Stop / Single / AutoSet"},
    ],
}

S["03_Signal_Gen__BK_4055B_"] = {
    "callouts": [
        {"match": "Waveform:", "extend_right": 150, "badge_side": "right",
         "label": "Waveform type — the fields below adapt to it"},
        {"match": "Preview (~3 periods)", "label": "Drawing of your typed settings — not a measurement"},
        {"match": "Apply CH1 Settings", "label": "Pushes settings; never switches the output"},
        {"match": "Read Instrument", "label": "Pull the front-panel state back into the fields"},
        {"match": "Output: OFF", "label": "The real output switch — asks first, green while ON"},
        {"union": ["Burst", "Fire"], "label": "Burst mode — exactly N cycles per trigger; Fire sends one"},
        {"match": "Presets", "label": "Named presets store both channels; files travel by USB"},
        {"match": "Advanced mode", "label": "Reveals phase, pulse edges, load and polarity"},
    ],
}

S["04_DC_Supply__BK_9174B_"] = {
    "callouts": [
        {"union": ["Set Voltage (V):", "Current Limit (A):"], "extend_right": 55,
         "label": "Stage voltage and current ceiling (CC — not a fuse)"},
        {"match": "Apply V / I limit", "label": "Sends values — output stays untouched"},
        {"match": "Protection", "label": "OVP / OCP hardware trips — set these first"},
        {"match": "Output: OFF", "label": "Energizes the terminals — confirms first, green while ON"},
        {"match": "Live readout", "label": "Polls measured V, A and W every 0.5 s"},
        {"match": "Dual-range:", "label": "Allowed envelope: 3 A up to 35 V, 1.5 A above"},
    ],
}

S["05_DMM__BK_5493C_"] = {
    "callouts": [
        {"match": "IP:", "extend_right": 95, "label": "The meter's LAN address — this unit is Ethernet-only"},
        {"match": "Reconnect", "label": "Connect / retry at this IP"},
        {"match": "Function:", "extend_right": 130, "label": "What to measure — V, A, Ω, Hz, F (auto-ranged)"},
        {"match": "Live reading", "badge_at": [302, 178],
         "label": "Continuous display, ~2 readings per second"},
        {"match": "Read once", "label": "Single measurement"},
        {"match": "—", "label": "Reading appears here — red OVLD on overload"},
    ],
}

S["06_Data_Logging"] = {
    "callouts": [
        {"match": "Log Directory:", "extend_right": 260, "label": "All CSV files land here (default ./logs)"},
        {"match": "Sample Interval (s):", "extend_right": 60, "label": "Seconds between samples"},
        {"rect": [30, 183, 350, 335], "badge_side": "right",
         "label": "Tick every source to record — one CSV per source"},
        {"match": "Start Logging", "label": "Opens fresh timestamped CSVs and starts sampling"},
        {"match": "Stop Logging", "label": "Closes the files and ends the run"},
        {"match": "Log Status", "label": "File paths, errors, and dropped sources appear here"},
    ],
}

S["07_Battery_Data"] = {
    "callouts": [
        {"match": "Load File…", "badge_at": [19, 260], "label": "Open the raw cycler .xls/.xlsx export"},
        {"match": "No file loaded", "label": "Shows filename + rows × columns when processed"},
        {"match": "Export Processed CSV…", "label": "Translated, merged table → CSV"},
        {"union": ["Plot style:", "Time unit:"], "extend_right": 85,
         "label": "Batch options — line/scatter, time in s/min/h"},
        {"match": "Generate All Cycle Plots", "label": "Two 300-dpi PNGs per cycle (V–t and V–Q)"},
    ],
}

S["08_Webcam"] = {
    "callouts": [
        {"union": ["Camera:", "Refresh"], "extend_right": 40, "badge_at": [70, 258],
         "label": "Pick the camera; Refresh rescans devices"},
        {"match": "Start Preview", "badge_at": [268, 258], "label": "Live view — the same button stops it"},
        {"match": "Snapshot", "badge_at": [352, 258], "label": "Save one timestamped PNG"},
        {"match": "Show focus score", "label": "Sharpness number — turn the lens until it peaks"},
        {"match": "🔒 Apply & Lock", "label": "Locks every camera knob — prevents drift during runs"},
        {"match": "Start interval", "badge_side": "right", "label": "Automatic photo every N seconds"},
        {"match": "Run sweep", "label": "Steps a sig-gen voltage, one photo per level"},
        {"match": "Start timed capture", "label": "Photos at chosen delays after t=0"},
    ],
}

S["09_SLDEA_Test"] = {
    "callouts": [
        {"match": "Test Profile (voltages in kV",
         "label": "The voltage staircase — start/end/step, ramp and landing times (the 0 kV reference photo is always taken)"},
        # `#292`: ONE capsule over the three rows that define the device.
        # They were two separate callouts (diam, and concentration numbered
        # last and eleven badges away) for a pair of fields the operator
        # fills in as one flow — the same reading-order argument `#290` used
        # to move the Trek checkbutton off this block (gui.py: "those two
        # define the DEVICE and read as one flow ... this is a DRIVE setting
        # and comes after"). Trek inverts therefore stays OUT of the union.
        # The px→mm warning stays inline: it is the one field here that can
        # silently corrupt every area in the run.
        {"union": ["DEA active area diam (mm):", "Electrode:",
                   "Concentration (mL):"], "extend_right": 175,
         "label": "Defines the device: active-area diameter (sets the px→mm "
                  "scale — a wrong value corrupts every area), electrode "
                  "material, ink concentration (greyed for non-inks)"},
        {"match": "⚡ Breakdown watchdog (LIVE runs)", "label": "Aborts on sustained overcurrent — leave Enabled"},
        {"match": "📈 Scope kV/µA log", "label": "Logs kV/µA continuously to telemetry.csv — the current between photos"},
        {"match": "DRY RUN — HV OFF", "label": "Safety toggle — untick only for a live HV run"},
        {"match": "▶ Run (DRY)", "label": "Starts the run — the label shows the mode"},
        {"match": "■ Abort", "label": "Ramps to 0 kV first, then stops"},
        {"match": "🔍 Edge Review…", "badge_side": "bottom",
         "label": "Open Edge Review on a finished run — see the Edge Review section"},
        {"match": "🎚 Tune params…", "badge_side": "bottom",
         "label": "Advanced — confirmation-gated; Save rewrites the run's detection settings"},
        # `#223`. Added WITH the button rather than at the next release:
        # the shots on disk predate it, so until a fresh capture this is a
        # miss and the manual build fails on it (`#248`). That is the
        # intended state -- the build is ALREADY red on three legitimate
        # misses (the renamed 📏 button, the `#224` telemetry label, the
        # new ❓ button) waiting for the same capture, and the release
        # checklist is capture-then-annotate. A matcher deferred to
        # "later" is the failure mode `#248` exists to stop.
        {"match": "📊 Plot runs…", "badge_side": "bottom",
         "label": "Several finished runs on one figure — Export writes the PNG and its tidy CSV together"},
        # Listed last rather than in screen order (it sits above the DRY RUN
        # row) so this entry stays clear of the DEA-diam callout that `#262`
        # is rewriting three lines up. Badge numbering follows list order, so
        # the presets capsule is numbered last on the shot — cosmetic only.
        {"match": "Run configuration presets",
         "label": "Save the whole tab under a name and recall it — never the run name, and never the LIVE state"},
    ],
}

S["20_arb_editor"] = {
    "callouts": [
        {"union": ["Points:", "Full-scale ±V:"], "extend_right": 45,
         "label": "Resolution (samples) and the volt scale (max ±10 V)"},
        {"rect": [16, 96, 228, 268], "badge_side": "br",
         "label": "Breakpoint table — double-click a cell for exact values"},
        {"rect": [258, 78, 620, 452], "label": "Click to add a point, drag dots, right-click deletes"},
        {"match": "Segment after point", "badge_side": "tr",
         "label": "Shape to the next point: LINE, HOLD, SINE, EXP…"},
        {"match": "Save to Library", "label": "Store the waveform for reuse"},
        {"match": "Export .bin for 4055B flash drive...", "label": "Preferred delivery: file for the 4055B's front USB port"},
        {"match": "Export for EasyWaveX (flash drive)...", "label": "Fallback: CSV template for the EasyWaveX PC"},
        {"match": "Upload && Select", "label": "Direct upload — works over LAN only"},
    ],
}

S["40_edge_review"] = {
    "callouts": [
        {"match": "Run:", "extend_right": 310,
         "label": "Pick the run — ✓ marks already-processed runs"},
        {"match": "▶ Detect Edges",
         "label": "Traces every frame — picks/rejects from earlier passes reset"},
        {"match": "Candidates",
         "label": "Machine outlines — colors match the A/B/C tags on the image"},
        {"union": ["✔ Accept (Enter)", "✘ Reject (R)"],
         "label": "Keys: 1/2/3 pick a candidate, Enter accepts, R rejects, D traces by hand"},
        {"match": "Next unreviewed", "label": "Jump to the next frame needing a human"},
        {"match": "review queue", "label": "Frames still waiting for a decision"},
        {"match": "📏 Calibrate / re-anchor…",
         "label": "Set or re-anchor the mm-per-px scale — verify the automatic disc fit"},
        {"match": "💾 Save to data.csv…", "badge_side": "bottom",
         # bottom, not the automatic left: the `#237` detect/session clock
         # now sits left of Save, and the auto badge landed on its text
         "label": "Writes accepted areas back (keeps a .bak) — confirms first"},
        {"match": "❓ How to use…", "badge_side": "left",
         "label": "The review loop in one short read — start here"},
    ],
}

S["21_arb_bin_export"] = {
    "callouts": [
        {"match": "Save to flash drive", "label": "One click straight onto a detected USB stick"},
        {"match": "Save .bin...", "label": "…or choose any folder yourself"},
    ],
}

S["22_arb_easywavex_export"] = {
    "callouts": [
        {"union": ["Frequency (Hz):", "Phase (deg):"], "extend_right": 100,
         "badge_side": "tr",
         "label": "Header values — lab defaults pre-filled (1 V = 1 kV at the Trek)"},
        {"match": "Save CSV...", "label": "Writes the exact template EasyWaveX expects"},
    ],
}

# ------------------------------------------------------------ drawing


def rects_overlap(a, b, pad=2):
    return not (a[0] + a[2] + pad < b[0] or b[0] + b[2] + pad < a[0]
                or a[1] + a[3] + pad < b[1] or b[1] + b[3] + pad < a[1])


def place_badge(rect, occupied, img_w, img_h, soft=(), r=16, side=None):
    x, y, w, h = rect
    cx, cy = x + w / 2, y + h / 2
    if side:
        forced = {"left": (x - 30, cy), "right": (x + w + 30, cy),
                  "top": (cx, y - 30), "bottom": (cx, y + h + 30),
                  "tl": (x + 26, y), "tr": (x + w - 26, y),
                  "bl": (x + 26, y + h), "br": (x + w - 26, y + h)}[side]
        return (min(max(forced[0], r + 3), img_w - r - 3),
                min(max(forced[1], r + 3), img_h - r - 3))
    wide = w > img_w * 0.55
    on_border = [(x + w - 26, y), (x + 26, y + h),
                 (x + w - 26, y + h), (x + 26, y)]
    around = [
        (x - 30, cy), (x + w + 30, cy), (cx, y - 30), (cx, y + h + 30),
        (x - 30, y - 24), (x + w + 30, y - 24),
        (x - 30, y + h + 24), (x + w + 30, y + h + 24),
        (x - 48, cy), (x + w + 48, cy), (cx, y - 48), (cx, y + h + 48),
    ]
    cands = (on_border + around) if wide else (around + on_border)

    def ok(bx, by, check_soft):
        bb = [bx - r, by - r, 2 * r, 2 * r]
        if bb[0] < 3 or bb[1] < 3 or bb[0] + bb[2] > img_w - 3 \
                or bb[1] + bb[3] > img_h - 3:
            return False
        if any(rects_overlap(bb, o) for o in occupied):
            return False
        if check_soft and any(rects_overlap(bb, s) for s in soft):
            return False
        return True

    for bx, by in cands:
        if ok(bx, by, True):
            return bx, by
    for bx, by in cands:
        if ok(bx, by, False):
            return bx, by
    return max(3 + r, x - 30), max(3 + r, cy)


def annotate(name, spec):
    src = images[spec.get("source", name)]
    im = Image.open(os.path.join(
        SHOTS, os.path.basename(src["file"]))).convert("RGB")
    d = ImageDraw.Draw(im)
    img_w, img_h = im.size

    resolved = []
    for c in spec["callouts"]:
        rect = resolve(src, c)
        if rect is None:
            continue
        rect = [rect[0] - 5, rect[1] - 5, rect[2] + 10, rect[3] + 10]
        resolved.append((rect, c["label"], c))

    occupied = [r for r, _, _ in resolved]
    soft = [[w["x"], w["y"], w["w"], w["h"]] for w in src["widgets"]
            if w["text"].strip() and w["w"] < img_w * 0.7]
    legend = []
    placed = []
    for i, (rect, label, cspec) in enumerate(resolved, 1):
        x, y, w, h = rect
        radius = min(18, h // 2 + 6)
        # white halo then red capsule
        d.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                            outline=WHITE, width=6)
        d.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                            outline=RED, width=3)
        others = [o for o in occupied if o is not rect]
        if "badge_at" in cspec:
            bx, by = cspec["badge_at"]
        else:
            bx, by = place_badge(rect, others + placed, img_w, img_h, soft,
                                 side=cspec.get("badge_side"))
        placed.append([bx - 16, by - 16, 32, 32])
        # arrow from badge edge to capsule edge
        tx = min(max(bx, x), x + w)
        ty = min(max(by, y), y + h)
        dx, dy = tx - bx, ty - by
        dist = math.hypot(dx, dy)
        if dist > 24:
            ux, uy = dx / dist, dy / dist
            sx, sy = bx + ux * 18, by + uy * 18
            ex, ey = tx - ux * 2, ty - uy * 2
            d.line([sx, sy, ex, ey], fill=WHITE, width=6)
            d.line([sx, sy, ex, ey], fill=RED, width=3)
            # arrowhead
            for base, color in ((11, WHITE), (9, RED)):
                px, py = -uy, ux
                pts = [(ex, ey),
                       (ex - ux * base + px * base * 0.55,
                        ey - uy * base + py * base * 0.55),
                       (ex - ux * base - px * base * 0.55,
                        ey - uy * base - py * base * 0.55)]
                d.polygon(pts, fill=color)
        d.ellipse([bx - 17, by - 17, bx + 17, by + 17], fill=WHITE)
        d.ellipse([bx - 15, by - 15, bx + 15, by + 15], fill=RED)
        tb = d.textbbox((0, 0), str(i), font=FONT)
        d.text((bx - (tb[2] - tb[0]) / 2, by - (tb[3] - tb[1]) / 2 - tb[1]),
               str(i), font=FONT, fill=WHITE)
        legend.append({"n": i, "label": label})

    out = os.path.join(OUT, name + ".png")
    im.save(out, optimize=True)
    print(f"annotated {name}: {len(legend)} callouts")
    return {"file": out, "legend": legend}


legends = {}
for name, spec in S.items():
    legends[name] = annotate(name, spec)

LEGENDS_PATH = os.path.join(OUT, "legends.json")
if MISSES:
    # FAIL CLOSED (2026-08-07). An unmatched callout used to cost only the
    # "!! no match" line above: the capsule and its legend row vanished from
    # the shipped manual and the build still said DONE — the 📏 Calibrate…
    # callout was lost exactly that way when the button grew " / re-anchor"
    # (`#215`). And a legends.json from a PREVIOUS run must not survive the
    # failure either, or a chained build_manual.py would assemble the manual
    # from stale legends as if nothing were wrong — so it is removed, which
    # stops build_manual.py at its own front door.
    if os.path.exists(LEGENDS_PATH):
        os.remove(LEGENDS_PATH)
    print(f"\nFAILED — {len(MISSES)} callout string(s) matched no widget; "
          f"legends.json removed so build_manual.py cannot run:")
    for img_name, t in MISSES:
        print(f"  - {img_name}: {t!r}")
    print("Renamed control → give its spec in the S[...] tables the literal "
          "on-screen text=. Stale screenshots → re-run the capture stage "
          "first (README.md).")
    sys.exit(1)

with open(LEGENDS_PATH, "w", encoding="utf-8") as f:
    json.dump(legends, f, indent=1, ensure_ascii=False)
print("DONE")
