# -*- coding: utf-8 -*-
"""Assemble the Digital Multitool user manual HTML from captured assets."""
import base64
import html
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(_HERE, "build")
ANN = os.path.join(BASE, "annotated")
SHOTS = os.path.join(BASE, "shots")

# Version comes from the app itself (repo root version.py) so the manual
# cover and footer always name the build being documented.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
from version import __version__, version_string  # noqa: E402

content = json.load(open(os.path.join(_HERE, "content.json"), encoding="utf-8"))
legends = json.load(open(os.path.join(ANN, "legends.json"), encoding="utf-8"))

# ---- audit corrections (verified against gui.py / instruments.py) --------
_sh = content["app-shell"]
_sh["workflow"][6] = ("7. Close the window when done — sig-gen outputs and "
                      "LCR bias switch off automatically; the DC supply "
                      "output is left as-is.")
_sh["cautions"][0] = (
    "Closing the window switches off sig-gen outputs and LCR bias and stops "
    "a running SLDEA test (best-effort, a few seconds to ramp) — but the DC "
    "supply output is never touched. End a live HV run with ■ Abort, not the "
    "close button.")
_sh["cautions"][1] = (
    "Loading a bench profile immediately rewrites every connected "
    "instrument's settings — sig-gen outputs are never switched, but the LCR "
    "DC bias follows the profile's Bias ON state. Don't load one "
    "mid-measurement.")
_sh["cautions"][4] = (
    "On Windows the amber “Linux bench only” connection lines and "
    "the greyed-out Update Software… are normal, not faults.")

_lcr = content["LCR Meter (BK 894)"]
_lcr["cautions"][0] = (
    "The app enforces the meter's limits — voltage 0.01–2.0 V, frequency "
    "100 Hz–500 kHz; out-of-range entries are rejected with a Configuration "
    "Error on Apply.")
_lcr["cautions"][4] = (
    "Open/Short corrections belong to the current fixture and leads — redo "
    "both after changing either, or every reading carries the wrong offset.")
_lcr["cautions"].append(
    "Each correction sweep takes tens of seconds and the meter is busy "
    "until it finishes.")

_sl = content["SLDEA Test"]
_sl["purpose"] = _sl["purpose"].replace(
    "single-layer DEA",
    "single-layer dielectric elastomer actuator (SLDEA)")
_sl["cautions"][0] = (
    "A live run drives real HV up to 10 kV through the Trek. Stop with "
    "■ Abort (it ramps to 0 kV first); closing the window also stops the run "
    "best-effort — if the SG link is dead the Trek can stay energized and "
    "the app raises an HV NOT ZEROED alarm.")

_arb = content["Arb Editor"]
_arb["cautions"] = [
    "The export buttons only save a file — nothing is sent to the "
    "instrument. The .bin holds the shape only; the EasyWaveX CSV embeds "
    "frequency/amp/offset in its header.",
    "After recalling the .bin on the 4055B front panel, click Apply CHx "
    "Settings on the Signal Gen tab to push frequency, amplitude and offset "
    "(the export pre-fills them).",
    _arb["cautions"][1],
    _arb["cautions"][2],
    _arb["cautions"][3],
    _arb["cautions"][4],
]

for _c in content["Webcam"]["controls"]:
    if "cap_0003" in _c["what"]:
        _c["what"] = _c["what"].replace(
            "cap_0003_1p9V_….png", "cap_0003_20260728-141230_1p9V.png")

content["Companion tools"]["purpose"] = (
    "Four stand-alone programs for recorded SLDEA runs — they touch no "
    "instruments, so any PC with a copy of the run data works.")
# --------------------------------------------------------------------------


def b64(path):
    return "data:image/png;base64," + base64.b64encode(
        open(path, "rb").read()).decode()


def esc(s):
    return html.escape(s, quote=False)


def strip_num(step):
    s = step.strip()
    i = 0
    while i < len(s) and (s[i].isdigit() or s[i] in ".) "):
        i += 1
    return s[i:] if i and i < len(s) else s


def fig(name, alt, cls=""):
    path = os.path.join(ANN, name + ".png")
    if not os.path.exists(path):
        path = os.path.join(SHOTS, name + ".png")
    return (f'<figure class="shot {cls}"><img src="{b64(path)}" '
            f'alt="{esc(alt)}" loading="lazy"></figure>')


def legend_grid(key):
    items = legends[key]["legend"]
    rows = []
    for it in items:
        rows.append(f'<div class="chip"><span class="n">{it["n"]}</span>'
                    f'<span class="t">{esc(it["label"])}</span></div>')
    return '<div class="legend">' + "".join(rows) + "</div>"


def steps(area, limit=7):
    ws = [strip_num(s) for s in content[area]["workflow"]][:limit]
    lis = "".join(f"<li>{esc(s)}</li>" for s in ws)
    return f'<div class="use"><h4>Typical use</h4><ol>{lis}</ol></div>'


def cautions(area, keep=None):
    cs = content[area]["cautions"]
    if keep is not None:
        cs = [cs[i] for i in keep if i < len(cs)]
    if not cs:
        return ""
    lis = "".join(f'<div class="c">{esc(c)}</div>' for c in cs)
    return f'<div class="cautions"><h4>Watch out</h4>{lis}</div>'


def controls_details(area, label="Every control on this tab"):
    rows = "".join(
        f'<tr><td class="cl">{esc(c["label"])}</td>'
        f'<td>{esc(c["what"])}</td></tr>'
        for c in content[area]["controls"])
    return (f'<details><summary>{esc(label)}</summary>'
            f'<div class="tblwrap"><table>{rows}</table></div></details>')


def section(sid, tab_label, area, img_key, extra_html="", caution_keep=None,
            purpose=None):
    a = content[area]
    return f"""
<section id="{sid}">
  <header class="band">
    <h2>{esc(tab_label)}</h2>
    <p class="purpose">{esc(purpose or a["purpose"])}</p>
  </header>
  {fig(img_key, tab_label + " — annotated screenshot")}
  {legend_grid(img_key)}
  {steps(area)}
  {cautions(area, caution_keep)}
  {controls_details(area)}
  {extra_html}
</section>"""


NAV = [
    ("start", "Getting started"), ("lcr", "LCR Meter"), ("scope", "Scope"),
    ("siggen", "Signal Gen"), ("arb", "Arb Editor"), ("psu", "DC Supply"),
    ("dmm", "DMM"), ("logging", "Logging"), ("battery", "Battery"),
    ("webcam", "Webcam"), ("sldea", "SLDEA Test"), ("tools", "SLDEA Tools"),
]
nav_html = "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in NAV)

# Full section titles, in document order. Must match the <h2> band titles
# exactly — make_pdf.py locates each section's page by this text and the
# print-only table of contents links to these ids.
SECTIONS = [
    ("start", "Getting started"),
    ("lcr", "LCR Meter — BK 894"),
    ("scope", "Oscilloscope — Tektronix MSO24"),
    ("siggen", "Signal Generator — BK 4055B"),
    ("arb", "Arbitrary Waveform Editor"),
    ("psu", "DC Supply — BK 9174B"),
    ("dmm", "Digital Multimeter — BK 5493C"),
    ("logging", "Data Logging"),
    ("battery", "Battery Data"),
    ("webcam", "Webcam"),
    ("sldea", "SLDEA Test"),
    ("tools", "SLDEA companion tools"),
]
print_toc_html = "".join(
    f'<li><a href="#{i}">{esc(t)}</a></li>' for i, t in SECTIONS)

shell = content["app-shell"]
shell_steps = steps("app-shell")
shell_caut = cautions("app-shell", keep=[0, 1, 4])

# --------------------------------------------------------------- sections
body = []

body.append(f"""
<header class="hero">
  <div class="hero-text">
    <p class="eyebrow">Digital Multitool · v{__version__}</p>
    <h1>Digital Multitool</h1>
    <p class="sub">User manual for the lab bench-control app — one window for the
    LCR meter, oscilloscope, signal generator, DC supply, DMM, data logging,
    battery post-processing, webcam captures and automated SLDEA tests.</p>
  </div>
  <figure class="splash"><img src="{b64(os.path.join(SHOTS, '00_splash.png'))}" alt="Digital Multitool splash screen"></figure>
</header>
<nav class="toc">{nav_html}</nav>
<nav class="print-toc"><h4>Contents</h4><ol>{print_toc_html}</ol>
<p class="print-note">Tip: this PDF has the same chapters in the bookmarks
sidebar of your PDF viewer — keep it open for one-click navigation.</p></nav>
""")

body.append(f"""
<section id="start">
  <header class="band"><h2>Getting started</h2>
  <p class="purpose">{esc(shell["purpose"])}</p></header>
  <div class="startgrid">
    <div class="launch">
      <h4>Launching</h4>
      <ul>
        <li><b>Bench PC (Linux):</b> double-click the desktop icon, or run <code>.venv/bin/python gui.py</code>.</li>
        <li><b>Windows lab PC:</b> double-click <code>_software\\Launch_SCPI_Control_Windows.bat</code> on the ShareDrive. First run needs Python 3.10+ and internet.</li>
        <li>On Windows the instrument tabs are <b>view/edit only</b> (amber note in each tab) — Battery Data and Webcam (snapshots and timelapse; not sig-gen-driven sweeps) are fully functional, and presets and bench profiles can be prepared and shared.</li>
      </ul>
    </div>
  </div>
  {fig('overview', 'Main window anatomy — annotated')}
  {legend_grid('overview')}
  {shell_steps}
  {shell_caut}
  {controls_details('app-shell', 'The app shell, menu and profiles in detail')}
</section>""")

body.append(section("lcr", "LCR Meter — BK 894", "LCR Meter (BK 894)",
                    "01_LCR_Meter__BK_894_", caution_keep=[0, 1, 3, 4, 5]))
body.append(section("scope", "Oscilloscope — Tektronix MSO24",
                    "Oscilloscope (MSO24)", "02_Oscilloscope__MSO24_",
                    caution_keep=[0, 1, 2]))
body.append(section("siggen", "Signal Generator — BK 4055B",
                    "Signal Gen (BK 4055B)", "03_Signal_Gen__BK_4055B_",
                    caution_keep=[0, 2, 3, 6]))

arb_extra = f"""
<div class="dialogpair">
  <div>{fig('21_arb_bin_export', 'Export .bin dialog')}{legend_grid('21_arb_bin_export')}</div>
  <div>{fig('22_arb_easywavex_export', 'EasyWaveX export dialog')}{legend_grid('22_arb_easywavex_export')}</div>
</div>"""
body.append(section("arb", "Arbitrary Waveform Editor", "Arb Editor",
                    "20_arb_editor", extra_html=arb_extra,
                    caution_keep=[0, 1, 2, 4]))

body.append(section("psu", "DC Supply — BK 9174B", "DC Supply (BK 9174B)",
                    "04_DC_Supply__BK_9174B_", caution_keep=[0, 1, 2, 3]))
body.append(section("dmm", "Digital Multimeter — BK 5493C", "DMM (BK 5493C)",
                    "05_DMM__BK_5493C_", caution_keep=[0, 1, 2]))
body.append(section("logging", "Data Logging", "Data Logging",
                    "06_Data_Logging", caution_keep=[0, 1, 2]))
body.append(section("battery", "Battery Data", "Battery Data",
                    "07_Battery_Data", caution_keep=[0, 2, 4]))
body.append(section("webcam", "Webcam", "Webcam", "08_Webcam",
                    caution_keep=[1, 2, 4]))
body.append(section("sldea", "SLDEA Test", "SLDEA Test", "09_SLDEA_Test",
                    caution_keep=[0, 1, 2, 4]))

ct = content["Companion tools"]
ct_caut = cautions("Companion tools", keep=[0, 1, 2, 3])
body.append(f"""
<section id="tools">
  <header class="band"><h2>SLDEA companion tools</h2>
  <p class="purpose">{esc(ct["purpose"])}</p></header>
  <div class="threecols">
    <div class="tool"><h4>🎚 Edge tuner</h4>
      <p>Drag sliders, watch the outlines redraw live on baseline / mid-run /
      late frames. <b>💾 Save</b> writes the values into that run's
      <code>setup.txt</code>. Open it from the SLDEA tab
      (<b>🎚 Tune params…</b>) or double-click
      <code>Tune_SLDEA_Windows.bat</code> — or drag a run folder onto it.</p></div>
    <div class="tool"><h4>🔍 Edge Review</h4>
      <p>Traces every frame of a run, queues the uncertain ones for a human
      pick, then writes the accepted areas back into the run's
      <code>data.csv</code>. Full walkthrough below.</p></div>
    <div class="tool"><h4>🩺 Diagnostic</h4>
      <p>When sliders can't fix a run, stop tuning and measure why:
      <code>Tune_SLDEA_Windows.bat /diag</code> writes
      <code>sldea_diag.txt/.json/.png</code> into the run folder and changes
      nothing. No window needed.</p></div>
    <div class="tool"><h4>📊 Plot tool</h4>
      <p>Puts several finished runs on one figure:
      <code>python sldea_plot.py RUN1 RUN2 --mode area</code>. Writes a
      300 dpi PNG <i>and</i> the tidy CSV behind it, so any figure can be
      traced back to its numbers. <code>--mode current</code> works on raw
      runs, before anyone has reviewed a frame.</p></div>
  </div>
  <h3 class="subh">Edge Review — reviewing a run</h3>
  {fig('40_edge_review', 'SLDEA Edge Review on a real bench run — annotated')}
  <p class="cap">A real review frame (bench run P3_1 at 2.25 kV, pre-ramp): A = disc-fit
  (green), B/C = difference outlines. The machine's best pick is preselected — Enter agrees
  and moves on.</p>
  {legend_grid('40_edge_review')}
  <div class="use"><h4>Reviewing a run</h4><ol>
    <li>Open it from the SLDEA tab (🔍 Edge Review…) — or run <code>python sldea_edge_gui.py &lt;run folder&gt; --auto</code>.</li>
    <li>Pick the run and click ▶ Detect Edges. Most frames auto-accept; the review queue holds the uncertain ones.</li>
    <li>On each queued frame, pick the outline that hugs the electrode: keys 1/2/3 (A/B/C), R rejects, 4/D opens the hand tracer.</li>
    <li>Enter accepts and moves on; Next unreviewed jumps ahead.</li>
    <li>If areas look wrong by a constant factor, 📏 Calibrate / re-anchor… — accept the machine's disc fit (measure by hand only if it refuses). Mid-review the corrected anchor is applied at the next Save; on a saved run it re-anchors — every mm² in data.csv is re-derived from the stored px immediately.</li>
    <li>Queue empty → 💾 Save to data.csv… — read the counts in the confirm prompt before answering Yes.</li>
  </ol></div>
  <h3 class="subh">When outlines look wrong — tuning and diagnosis</h3>
  <div class="advbox">
    <div>{fig('41_tuner_warning', 'Tune params advanced-tool confirmation dialog')}</div>
    <div>
      <h4>🎚 Tune params is an advanced tool</h4>
      <p>It asks you to confirm before it opens. Its <b>Save</b> rewrites the
      run's <code>setup.txt</code> — the detection settings Edge Review and
      every later analysis pass will use for that run — so badly tuned values
      silently change every area number. Reach for it only when Edge Review's
      outlines are consistently wrong across a run, and prefer per-frame
      picks or a hand trace for one-off bad frames.</p>
    </div>
  </div>
  {fig('30_tuner_selftest', 'Detection panels: baseline, mid-run, late frame with outlines', 'wide')}
  <p class="cap">What the detector shows per frame: cyan = detected outline, orange = resting-disc
  reference. Confidence and area (mm²) are printed above each panel.</p>
  {fig('31_diag_selftest', 'Diagnostic self-test sheet', 'wide')}
  <p class="cap">The diagnostic's verdict panels — run <code>--selftest</code> any time to check the
  stack without data.</p>
  <h3 class="subh">Comparing finished runs — the plot tool</h3>
  {fig('32_plot_selftest', 'Two runs on one figure: active area and expansion vs voltage', 'wide')}
  <p class="cap">The plot tool's own self-test figure. Left: active area against voltage. Right: the
  same curves normalised to each run's baseline, so runs that started at different sizes can be
  compared. Shaded bands are the measurement uncertainty; open markers mean a hand-traced boundary;
  ✕ marks a current-confirmed breakdown.</p>
  <div class="use"><h4>Putting runs on one figure</h4><ol>
    <li>Review the runs first for <code>--mode area</code> — it plots measured areas, so it skips runs nobody has reviewed. <code>--mode current</code> and <code>--mode power</code> need no review at all.</li>
    <li><code>python sldea_plot.py RUN1 RUN2 --mode area --out ~/figures</code> — each RUN is a run folder, a parent full of runs, or a bench shortcut, exactly as for the tuner.</li>
    <li>You get a PNG and a CSV of the same name. Keep them together: the CSV is the figure's evidence.</li>
    <li>Breakdown ✕ marks are recomputed from the recorded currents every time, never read off the frame filenames — a saved brand the currents do not support is reported as stale rather than drawn.</li>
  </ol></div>
  <div class="use"><h4>Typical tuning session</h4><ol>
  {"".join(f"<li>{esc(strip_num(s))}</li>" for s in ct["workflow"])}
  </ol></div>
  {ct_caut}
  <details><summary>Shortcuts, environment and every tool control</summary>
  <div class="tblwrap"><table>
  {"".join(f'<tr><td class="cl">{esc(c["label"])}</td><td>{esc(c["what"])}</td></tr>' for c in ct["controls"])}
  </table></div></details>
</section>""")

body.append(f"""
<footer class="foot">
  <p>Built from the live app ({esc(version_string())}) — every screenshot is a real capture, every
  callout is anchored to the actual control. Sources: <code>README.md</code>,
  <code>SLDEA_HANDOFF.md</code>, <code>SLDEA_MEASUREMENT.md</code> and the code itself.</p>
</footer>""")

CSS = """
:root {
  --paper:#FAFBFC; --ink:#1C2733; --navy:#1F3A5F; --navy-ink:#FFFFFF;
  --red:#D93025; --steel:#5B6B7C; --line:#D8DEE5; --card:#FFFFFF;
  --code-bg:#EEF1F5; --band:#1F3A5F; --chip:#F2F5F8; --caut:#FDF3F2;
}
@media (prefers-color-scheme: dark) { :root {
  --paper:#10161D; --ink:#E2E8EF; --navy:#8FB0DC; --navy-ink:#0E1622;
  --red:#F2554A; --steel:#93A3B4; --line:#2A3441; --card:#161E27;
  --code-bg:#1E2833; --band:#182C47; --caut:#2A1A19; --chip:#1B242E;
}}
:root[data-theme="dark"] {
  --paper:#10161D; --ink:#E2E8EF; --navy:#8FB0DC; --navy-ink:#0E1622;
  --red:#F2554A; --steel:#93A3B4; --line:#2A3441; --card:#161E27;
  --code-bg:#1E2833; --band:#182C47; --caut:#2A1A19; --chip:#1B242E;
}
:root[data-theme="light"] {
  --paper:#FAFBFC; --ink:#1C2733; --navy:#1F3A5F; --navy-ink:#FFFFFF;
  --red:#D93025; --steel:#5B6B7C; --line:#D8DEE5; --card:#FFFFFF;
  --code-bg:#EEF1F5; --band:#1F3A5F; --caut:#FDF3F2; --chip:#F2F5F8;
}
* { box-sizing:border-box; }
body { background:var(--paper); color:var(--ink);
  font:16px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif;
  margin:0; padding:0 16px 60px; }
code { font-family:Consolas, "Cascadia Mono", monospace; font-size:.86em;
  background:var(--code-bg); padding:1px 5px; border-radius:4px; }
.eyebrow { font-family:Consolas, monospace; text-transform:uppercase;
  letter-spacing:.14em; font-size:12px; color:var(--steel); margin:0 0 6px; }
.hero { max-width:1060px; margin:40px auto 10px; display:flex; gap:32px;
  align-items:center; flex-wrap:wrap; }
.hero-text { flex:1 1 420px; }
.hero h1 { font-size:44px; line-height:1.05; margin:0 0 12px;
  letter-spacing:-.015em; color:var(--navy); text-wrap:balance; }
.hero .sub { color:var(--steel); max-width:56ch; margin:0; }
.splash { flex:0 1 300px; margin:0; }
.splash img { width:100%; border-radius:10px;
  box-shadow:0 10px 30px rgba(15,30,50,.25); }
.toc { max-width:1060px; margin:22px auto 0; display:flex; flex-wrap:wrap;
  gap:8px; position:sticky; top:0; z-index:9; background:var(--paper);
  padding:12px 0 8px; border-bottom:1px solid var(--line); }
section { scroll-margin-top:72px; }
.toc a { font-family:Consolas, monospace; font-size:12.5px;
  text-decoration:none; color:var(--navy); border:1px solid var(--line);
  background:var(--card); border-radius:999px; padding:5px 12px; }
.toc a:hover, .toc a:focus-visible { border-color:var(--navy); outline:none; }
section { max-width:1060px; margin:46px auto 0; }
.band { background:var(--band); color:var(--navy-ink); border-radius:12px;
  padding:16px 22px; }
.band h2 { margin:0 0 4px; font-size:23px; letter-spacing:-.01em; }
.band .purpose { margin:0; font-size:14.5px; opacity:.85; max-width:90ch; }
:root[data-theme="dark"] .band h2, :root[data-theme="dark"] .band .purpose
 { color:var(--ink); }
@media (prefers-color-scheme: dark) { .band h2, .band .purpose { color:var(--ink); } }
:root[data-theme="light"] .band h2, :root[data-theme="light"] .band .purpose
 { color:var(--navy-ink); }
.shot { margin:18px 0 0; border:1px solid var(--line); border-radius:10px;
  overflow:hidden; background:var(--card); }
.shot img { display:block; width:100%; height:auto; }
.legend { display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr));
  gap:8px 14px; margin-top:12px; }
.chip { display:flex; gap:10px; align-items:flex-start; background:var(--chip);
  border:1px solid var(--line); border-radius:8px; padding:8px 11px;
  font-size:14px; }
.chip .n { flex:0 0 auto; width:24px; height:24px; border-radius:50%;
  background:var(--red); color:#fff; font-weight:700; font-size:13.5px;
  display:flex; align-items:center; justify-content:center; margin-top:1px;
  font-variant-numeric:tabular-nums; }
.use { margin-top:20px; }
h4 { font-family:Consolas, monospace; text-transform:uppercase;
  letter-spacing:.12em; font-size:12.5px; color:var(--steel); margin:0 0 8px; }
.use ol { margin:0; padding-left:22px; max-width:78ch; }
.use li { margin:3px 0; }
.cautions { margin-top:20px; display:grid; gap:6px; }
.cautions .c { background:var(--caut); border-left:3px solid var(--red);
  border-radius:0 8px 8px 0; padding:8px 12px; font-size:14px; max-width:100ch; }
details { margin-top:16px; border:1px solid var(--line); border-radius:10px;
  background:var(--card); }
summary { cursor:pointer; padding:10px 16px; font-family:Consolas, monospace;
  font-size:13px; color:var(--navy); }
summary:focus-visible { outline:2px solid var(--navy); border-radius:10px; }
.tblwrap { overflow-x:auto; padding:0 10px 10px; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
td { border-top:1px solid var(--line); padding:7px 10px; vertical-align:top; }
td.cl { white-space:nowrap; font-weight:600; color:var(--navy); }
.startgrid { margin-top:16px; }
.launch ul { margin:0; padding-left:20px; max-width:90ch; }
.launch li { margin:4px 0; }
.dialogpair { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
  gap:20px; margin-top:26px; align-items:start; }
.dialogpair .shot { margin-top:0; }
.threecols { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:14px; margin-top:18px; }
.tool { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; }
.tool h4 { margin-bottom:6px; }
.tool p { margin:0; font-size:14px; }
.cap { color:var(--steel); font-size:13px; margin:6px 2px 0; }
.subh { color:var(--navy); font-size:19px; letter-spacing:-.01em;
  margin:34px 0 0; }
.advbox { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
  gap:20px; margin-top:18px; align-items:center; }
.advbox .shot { margin-top:0; }
.advbox p { margin:0; font-size:14.5px; max-width:60ch; }
.foot { max-width:1060px; margin:60px auto 0; border-top:1px solid var(--line);
  padding-top:14px; color:var(--steel); font-size:13px; }
@media (max-width:700px) { .hero h1 { font-size:34px; } }
@media (prefers-reduced-motion: no-preference) {
  html { scroll-behavior:smooth; } }

/* ---- print / PDF (Edge headless via make_pdf.py, or Ctrl+P) ---------- */
.print-toc { display:none; }
@page { size:A4; margin:12mm 11mm 16mm; }
@media print {
  :root { --paper:#FFFFFF; }
  * { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  body { padding:0; font-size:13px; }
  .toc { display:none; }
  .hero { margin:28mm auto 8mm; }
  .print-toc { display:block; max-width:1060px; margin:10mm auto 0;
    border-top:1px solid var(--line); padding-top:14px; }
  .print-toc ol { columns:2; column-gap:40px; margin:0; padding-left:22px;
    font-size:14.5px; }
  .print-toc li { margin:4px 0; }
  .print-toc a { color:var(--navy); text-decoration:none; }
  .print-note { color:var(--steel); font-size:12px; margin:14px 0 0; }
  section { break-before:page; margin-top:0; }
  .band { break-after:avoid; }
  .shot, .chip, .cautions .c, .tool, .use, details tr { break-inside:avoid; }
  .dialogpair > div, .advbox { break-inside:avoid; }
  .subh { break-after:avoid; }
  details { border:none; }
  summary { color:var(--steel); }
  .foot { break-inside:avoid; }
}
"""

page = ("<title>Digital Multitool — User Manual</title>\n"
        f"<style>{CSS}</style>\n" + "\n".join(body))

out = os.path.join(os.path.dirname(_HERE), "digital-multitool-manual.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
print("wrote", out, f"{os.path.getsize(out)/1e6:.2f} MB")

# Section manifest for make_pdf.py (bookmarks + running footers).
with open(os.path.join(BASE, "sections.json"), "w", encoding="utf-8") as f:
    json.dump([{"id": i, "title": t} for i, t in SECTIONS], f, indent=1,
              ensure_ascii=False)
