export const meta = {
  name: 'audit',
  description: 'Comprehensive audit: RUNTIME verification first, then static finders, then adversarial verify',
  whenToUse: 'Run before/after a release round, or when asked for a comprehensive audit of the Digital Multitool.',
  phases: [
    { title: 'Runtime', detail: 'actually run it: suites, launch every GUI, exercise real paths' },
    { title: 'Audit', detail: 'parallel static finders, each a distinct focus' },
    { title: 'Verify', detail: 'adversarial check of significant findings' },
  ],
}

const REPO = '/home/amg17031/projects/SCPI_Control'

// ---------------------------------------------------------------------------
// WHY THE RUNTIME PHASE EXISTS (2026-07-27 post-mortem)
//
// The first run of this audit was scoped read-only: the finders were told
// never to execute gui.py. It produced 34 confirmed findings and still shipped
// a GUI that was DEAD ON ARRIVAL -- one emoji (U+1F39A) resolved to a colour
// bitmap font, Tk's RenderAddGlyphs overflowed, X returned BadLength, and Xlib
// aborted the process. No amount of source reading can see a render-time
// protocol abort. Worse, the developer's own smoke environment carried a font
// workaround that production did not, which masked the failure for five
// releases.
//
// Hence: RUN IT FIRST. Static analysis is the second opinion, not the first.
// The runtime agents must strip developer-local workarounds (FONTCONFIG_FILE,
// XDG_CONFIG_HOME) so they see what a user sees.
// ---------------------------------------------------------------------------

const SAFETY = `HARDWARE SAFETY (this repo drives a real lab bench):
- NEVER drive high voltage: no SG output enable, no LIVE SLDEA run, no PSU output on. Nobody may be in the room.
- Read-only instrument queries are allowed (IDN, scope settings/measurements). ALWAYS close sessions (VXI-11 link leaks wedge the BK4055B).
- Check first that nobody is using the bench: \`pgrep -af gui.py\` and \`who\`. If a GUI is running, do NOT touch instruments or /dev/video0 -- report and skip that check.
- Camera: another user's preview may hold /dev/video0. Never power-cycle anything.`

const DESIGN = `DELIBERATE DESIGN -- do NOT report these as bugs:
- BK9174B suffix channel model (VOLT vs VOLT2), no INST:SEL.
- pyvisa '@py' backend only; 4055B arb over USB capped at 52 B (LAN-only upload).
- Camera firmware auto-gain cannot be disabled over UVC; gain pinned at 0; preview re-stamps locked controls ~1 Hz EXCLUDING gain.
- Wrinkled region counts as ACTIVE area. _BREAKDOWN renaming is intentional; frames are never deleted.
- Emoji in the UI are intentional, but they MUST survive tk_fontfix (see tests/test_app_launch.py).
- Instrument I/O is gated to Linux; the Windows launcher is view-only.`

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          title: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'major', 'minor', 'nit'] },
          category: { type: 'string' },
          description: { type: 'string' },
          failure_scenario: { type: 'string' },
          suggested_fix: { type: 'string' },
          evidence: { type: 'string', description: 'command output / observed behaviour, for runtime findings' },
          confidence: { type: 'number' },
        },
        required: ['file', 'title', 'severity', 'description', 'failure_scenario', 'suggested_fix'],
      },
    },
    summary: { type: 'string' },
  },
  required: ['findings', 'summary'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['CONFIRMED', 'REFUTED', 'UNCERTAIN'] },
    corrected_severity: { type: 'string', enum: ['critical', 'major', 'minor', 'nit'] },
    justification: { type: 'string' },
  },
  required: ['verdict', 'justification'],
}

// ---------------------------------------------------------------------------
// PHASE 1 -- RUNTIME. These agents EXECUTE things.
// ---------------------------------------------------------------------------
const RUNTIME = [
  {
    key: 'launch',
    prompt: `Prove every entry point actually runs, as a USER experiences it.
1. cd ${REPO} && .venv/bin/python run_tests.py (redirect to /tmp, tail it). Report any failure verbatim.
2. Run tests/test_app_launch.py -- it launches gui.py, sldea_edge_gui.py and sldea_tuner.py under Xvfb and asserts a viewable window. CRITICAL: run it with FONTCONFIG_FILE and XDG_CONFIG_HOME UNSET, so no developer workaround masks a production failure.
3. Launch the DEPLOYED build the way the desktop icon does: bash /mnt/shareDrive/_software/launch_gui.sh under Xvfb with SCPI_CACHE pointed at a fresh temp dir (COLD cache -- what every user hits after a deploy). Confirm a viewable window and check the launch.log it writes.
4. Grep the app for characters outside Latin-1 in Tk widget text; for any NEW ones, render each in a throwaway Tk process to prove it does not abort (that is exactly how the 2026-07-27 outage happened).
Report each failure as a finding with the exact output in 'evidence'.`,
  },
  {
    key: 'workflows',
    prompt: `Exercise real user workflows end-to-end, headless, with NO hardware.
1. Edge Review on a synthetic run: build a run dir, run detect_all_sync + the save path, and verify data.csv/plot/overlays land and are re-runnable (save twice -- notes must not duplicate, rejected rows must not keep stale mm2).
2. sldea_tuner.py --selftest to a PNG.
3. sldea_profile: build profiles at the extremes (zero ramp, single landing, up/down + repeat, 0 steps) and check kv_at/snapshot scheduling never divides by zero or schedules past the end.
4. Re-open a REAL run from /mnt/shareDrive/robot_incubator/SLDEA_data read-only and confirm load_run/load_settings still parse it (back-compat: old runs use 'pre'/'post' tags and lack wrinkle_idx).
Report anything that raises, corrupts, or silently produces wrong numbers, with evidence.`,
  },
  {
    key: 'bench-readonly',
    prompt: `${SAFETY}
Verify the bench-facing paths against REAL hardware, read-only.
1. Confirm nobody is using the bench first; if they are, say so and skip to reporting.
2. Enumerate instruments (lsusb, /dev/ttyUSB*, /dev/video*, ping the LAN IPs). Open each driver, read *IDN?, CLOSE the session.
3. Read the scope's per-channel SCALE and PROBEFUNC:EXTATTEN and run sldea_profile.monitor_problems() against a 10 kV run -- the Trek monitors must be able to represent 0-10 V at 1x. (A 2.6 mV/div CH2 silently blanked measured_kV in five runs.)
4. Check the camera's locked controls are the pinned profile (gain 0) and that webcam.apply_locked re-stamps.
Report misconfiguration as findings with the actual values in 'evidence'. Change NOTHING.`,
  },
]

phase('Runtime')
const runtime = (await parallel(RUNTIME.map(r => () =>
  agent(`You are auditing the bench-control app "Digital Multitool" at ${REPO}.
${DESIGN}

RUNTIME PHASE -- you EXECUTE, you do not just read. Report only real, reproduced problems, each with the command output in 'evidence'. Severity: critical (data loss/crash/safety), major (wrong behaviour users hit), minor, nit.

${r.prompt}`,
    { label: 'runtime:' + r.key, phase: 'Runtime', schema: FINDINGS_SCHEMA })
    .then(x => ({ focus: 'runtime-' + r.key, ...x }))))).filter(Boolean)

const runtimeFindings = runtime.flatMap(r => (r.findings || []).map(f => ({ ...f, focus: r.focus })))
const blockers = runtimeFindings.filter(f => f.severity === 'critical')
log(`runtime: ${runtimeFindings.length} findings (${blockers.length} critical)`)
if (blockers.length) {
  log(`⚠ RUNTIME BLOCKERS -- the app does not work; static findings are secondary:`)
  blockers.forEach(b => log(`   • ${b.title} (${b.file})`))
}

// ---------------------------------------------------------------------------
// PHASE 2 -- STATIC finders (the previous audit's six foci)
// ---------------------------------------------------------------------------
const FOCI = [
  { key: 'instruments', prompt: `instruments.py (all driver classes) and gui.py's concurrent use of them: locking coverage (every session now has an _io_lock -- find call sites that bypass it), reply desync, timeouts, session leaks on error paths, go_local/close ordering, envelope math, unit parsing, swallowed exceptions that matter.` },
  { key: 'gui-threading', prompt: `gui.py threading + state machine: Tk widgets touched off the main thread (the historical hang class), after()-job leaks, generation-token coverage for every worker (logging/sweep/camera/SLDEA), busy-key interleaving, connect/disconnect/quit paths, worker exceptions that vanish.` },
  { key: 'sldea-stack', prompt: `the SLDEA stack (sldea_profile, gui SLDEA worker/capture/preflight, sldea_edge, sldea_edge_gui, sldea_tuner): math edge cases, file I/O integrity and atomicity, CSV schema evolution/back-compat, snapshot timing, watchdog+capture interaction, kV/uA unit handling, the px->mm scale path.` },
  { key: 'accessibility-ux', prompt: `accessibility + UX (gui.py, ui_widgets.py, sldea_edge_gui.py, sldea_tuner.py): information carried by colour alone, contrast of hardcoded colours, keyboard/focus/modal traps, HV-action affordances and confirmation defaults, error messages that say what to DO, tooltip coverage on newer panels.` },
  { key: 'robustness-deploy', prompt: `failure modes + deployment: presets_path, webcam settings, deploy/*.sh(.reference) vs the LIVE copies on the share (diff them), the Windows .bat, battery deps. Share-down paths, root-owned-dir class bugs, write atomicity, disk-full, second-user divergence, stale caches, version stamping order, shell quoting.` },
  { key: 'tests-coverage', prompt: `test suite quality: map modules to tests, find the riskiest UNTESTED paths, flag BRITTLE tests (synthetic scenes tuned to thresholds), tests that don't test what their name claims, and propose the highest-value additions. Note especially anything that could only be caught by RUNNING the app -- that gap caused a production outage.` },
]

phase('Audit')
const statics = (await parallel(FOCI.map(f => () =>
  agent(`You are auditing the bench-control app "Digital Multitool" at ${REPO} (Python 3.11, Tk, pyvisa-py). STATIC review pass.
${SAFETY}
${DESIGN}
You MAY read anything and run pure-Python snippets that import repo modules without doing I/O. Report ONLY genuine issues you can cite at file:line with a concrete failure scenario. No style nits unless they cause real failures.

FOCUS: ${f.prompt}`,
    { label: 'audit:' + f.key, phase: 'Audit', schema: FINDINGS_SCHEMA })
    .then(x => ({ focus: f.key, ...x }))))).filter(Boolean)

const all = [...runtimeFindings,
             ...statics.flatMap(r => (r.findings || []).map(f => ({ ...f, focus: r.focus })))]

// converge: same file + nearby line + same category = one issue
const buckets = new Map()
for (const f of all) {
  const key = String(f.file).replace(/^.*\//, '') + ':' + Math.round((f.line || 0) / 40) + ':' + (f.category || '')
  if (!buckets.has(key)) buckets.set(key, [])
  buckets.get(key).push(f)
}
const SEV = { critical: 3, major: 2, minor: 1, nit: 0 }
const merged = []
for (const g of buckets.values()) {
  g.sort((a, b) => (SEV[b.severity] || 0) - (SEV[a.severity] || 0))
  merged.push({ ...g[0], converged: g.length, foci: [...new Set(g.map(x => x.focus))] })
}
merged.sort((a, b) => (SEV[b.severity] || 0) - (SEV[a.severity] || 0))
const significant = merged.filter(f => SEV[f.severity] >= 2 || (f.converged >= 2 && SEV[f.severity] >= 1))
const minors = merged.filter(f => !significant.includes(f))
log(`${merged.length} unique (${significant.length} to verify, ${minors.length} minor)`)

phase('Verify')
const verified = (await parallel(significant.map(f => () =>
  agent(`${SAFETY}
${DESIGN}
You are an adversarial VERIFIER for ${REPO}. Default stance: REFUTE. Read the cited code and its callers; only CONFIRM if the failure is real and reachable. A finding tagged focus "runtime-*" came with reproduced evidence -- try to reproduce it yourself before refuting.

CLAIM (focus ${f.focus}, converged by ${f.converged}):
${f.file}${f.line ? ':' + f.line : ''}
title: ${f.title}
severity: ${f.severity}
description: ${f.description}
failure_scenario: ${f.failure_scenario}
evidence: ${f.evidence || '(none)'}

Return CONFIRMED only with a concrete reachable path, UNCERTAIN if it needs hardware/a human to decide, else REFUTED with the reason. Correct the severity if mis-rated.`,
    { label: `verify:${String(f.title).slice(0, 40)}`, phase: 'Verify', schema: VERDICT_SCHEMA })
    .then(v => ({ ...f, verdict: v ? v.verdict : 'UNCERTAIN',
                  corrected_severity: (v && v.corrected_severity) || f.severity,
                  justification: v ? v.justification : 'verifier died' }))))).filter(Boolean)

const confirmed = verified.filter(f => f.verdict === 'CONFIRMED')
const uncertain = verified.filter(f => f.verdict === 'UNCERTAIN')
const refuted = verified.filter(f => f.verdict === 'REFUTED')
log(`verify: ${confirmed.length} confirmed, ${uncertain.length} uncertain, ${refuted.length} refuted`)

return {
  runs: true,
  runtime_blockers: blockers,
  stats: {
    runtime_findings: runtimeFindings.length, static_findings: all.length - runtimeFindings.length,
    unique: merged.length, confirmed: confirmed.length,
    uncertain: uncertain.length, refuted: refuted.length, minors: minors.length,
  },
  summaries: [...runtime, ...statics].map(r => ({ focus: r.focus, summary: r.summary })),
  confirmed, uncertain, refuted, minors,
}
