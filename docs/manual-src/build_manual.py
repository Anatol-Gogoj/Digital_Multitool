# -*- coding: utf-8 -*-
"""Assemble the Digital Multitool user manual HTML from captured assets."""
import base64
import html
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(_HERE, "build")
ANN = os.path.join(BASE, "annotated")
SHOTS = os.path.join(BASE, "shots")

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
    "Three stand-alone programs for recorded SLDEA runs — they touch no "
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

shell = content["app-shell"]
shell_steps = steps("app-shell")
shell_caut = cautions("app-shell", keep=[0, 1, 4])

# --------------------------------------------------------------- sections
body = []

body.append(f"""
<header class="hero">
  <div class="hero-text">
    <p class="eyebrow">SCPI_Control · v0.32.2</p>
    <h1>Digital Multitool</h1>
    <p class="sub">User manual for the lab bench-control app — one window for the
    LCR meter, oscilloscope, signal generator, DC supply, DMM, data logging,
    battery post-processing, webcam captures and automated SLDEA tests.</p>
  </div>
  <figure class="splash"><img src="{b64(os.path.join(SHOTS, '00_splash.png'))}" alt="Digital Multitool splash screen"></figure>
</header>
<nav class="toc">{nav_html}</nav>
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
ct_caut = cautions("Companion tools", keep=[0, 1, 3])
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
      pick (keys 1/2/3, R rejects, D traces by hand), then
      <b>💾 Save to data.csv…</b> writes the areas back (a .bak is kept).
      Open it from the SLDEA tab (<b>🔍 Edge Review…</b>) or run
      <code>python sldea_edge_gui.py &lt;run folder&gt; --auto</code>.</p></div>
    <div class="tool"><h4>🩺 Diagnostic</h4>
      <p>When sliders can't fix a run, stop tuning and measure why:
      <code>Tune_SLDEA_Windows.bat /diag</code> writes
      <code>sldea_diag.txt/.json/.png</code> into the run folder and changes
      nothing. No window needed.</p></div>
  </div>
  {fig('30_tuner_selftest', 'Detection panels: baseline, mid-run, late frame with outlines', 'wide')}
  <p class="cap">What the detector shows per frame: cyan = detected outline, orange = resting-disc
  reference. Confidence and area (mm²) are printed above each panel.</p>
  {fig('31_diag_selftest', 'Diagnostic self-test sheet', 'wide')}
  <p class="cap">The diagnostic's verdict panels — run <code>--selftest</code> any time to check the
  stack without data.</p>
  <div class="use"><h4>Typical tuning session</h4><ol>
  {"".join(f"<li>{esc(strip_num(s))}</li>" for s in ct["workflow"])}
  </ol></div>
  {ct_caut}
  <details><summary>Shortcuts, environment and every tool control</summary>
  <div class="tblwrap"><table>
  {"".join(f'<tr><td class="cl">{esc(c["label"])}</td><td>{esc(c["what"])}</td></tr>' for c in ct["controls"])}
  </table></div></details>
</section>""")

body.append("""
<footer class="foot">
  <p>Built from the live app (v0.32.2+9725a59) — every screenshot is a real capture, every
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
.foot { max-width:1060px; margin:60px auto 0; border-top:1px solid var(--line);
  padding-top:14px; color:var(--steel); font-size:13px; }
@media (max-width:700px) { .hero h1 { font-size:34px; } }
@media (prefers-reduced-motion: no-preference) {
  html { scroll-behavior:smooth; } }
"""

page = ("<title>Digital Multitool — User Manual</title>\n"
        f"<style>{CSS}</style>\n" + "\n".join(body))

out = os.path.join(os.path.dirname(_HERE), "digital-multitool-manual.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
print("wrote", out, f"{os.path.getsize(out)/1e6:.2f} MB")
