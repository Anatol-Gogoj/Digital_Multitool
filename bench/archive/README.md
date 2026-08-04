# bench/archive — historical scripts, kept for the record

These are deliberately preserved, not live tooling. Nothing imports them
and no current workflow runs them; they document how past conclusions
were reached.

| Script | Why archived |
|---|---|
| `test_instruments.py` | Feb-2026 bring-up probe with its own raw `/dev/usbtmc` file-I/O class — predates the PyVISA migration (2026-06-04) and the `instruments.py` drivers. |
| `test_bk894_measurements.py` | Same raw-USBTMC vintage; superseded by `instruments.BK894` + headless `tests/test_bk894_parse.py`. |
| `test_arb_usb_probe.py` | The 52-byte USB-cap isolation probe. **Intentionally wedges the 4055B** (front-panel power cycle to recover). Its findings are fully written into README §"BK 4055B USB commands are hard-capped at 52 bytes" — run it again only to re-verify that claim on new firmware. |
| `test_arb_upload_only.py` | Companion wedge-isolation probe from the same investigation; same status. |

Current bench self-tests live one level up in `bench/`.
