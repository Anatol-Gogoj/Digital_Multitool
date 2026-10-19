#!/usr/bin/env python3
"""Text and banner colors for the whole app, all from Paul Tol's schemes (#462).

Lines and marks drawn on canvases and plots have their own Tol colors where
they are drawn (#450, #454). These are the colors words are written in, and
the fills that words sit on.

Source: Paul Tol, "Colour schemes", https://sronpersonalpages.nl/~pault/,
section "Qualitative colour schemes" dated 16 August 2026 (read
2026-10-19). Fig. 6 is the dark scheme, "for text and lines when
visibility on a white background is more important than distinct colours";
each of its colors has at least 4.5:1 contrast with white. Fig. 7 is the
pale scheme, "for the background of black text", and Fig. 8 the light
scheme, for labelled cells that need more distinct colors.

The bar for words is WCAG 2.1 SC 1.4.3: 4.5:1 against what they sit on
(3:1 for large text). The worst background is the Linux bench's: Tk's
default #d9d9d9 (NORMAL_BG in unix/tkUnixDefault.h, and -frame in
library/ttk/defaults.tcl). Windows paints #f0f0f0, which is lighter, so
anything that passes on the bench passes there too.

Ten Tol colors reach 4.5:1 on #d9d9d9. Among them, the state colors below
are the only set that also stays apart under simulated color blindness
beside the gray: worst-case CIEDE2000 18.0 or more over normal and
Machado-2009 deutan, protan and tritan vision (tests/test_ui_colors.py).
Tol's one passing green (#006644) is at most 11.91 from every passing red
and from the brown, and 9.96 from the gray. So "OK" is blue here, not
green, and warnings and errors share the brown. The words, and a symbol
where there is one, always say which state it is; the color only repeats
it.
"""

# ---- words on the app's light backgrounds (#d9d9d9 bench, #f0f0f0 Windows,
# white canvases and entry fields) --------------------------------------
TEXT = '#000000'          # plain text (Tol high-contrast: black)
TEXT_MUTED = '#444444'    # secondary text, hints, idle, busy (Tol dark: grey)
TEXT_OK = '#2255AA'       # connected, done, saved, in range (dark: sapphire)
TEXT_ACCENT = TEXT_OK     # the app's accent: summaries, readouts, ▶ Detect
TEXT_ALERT = '#775500'    # connecting, warnings and errors (dark: brown)

# ---- filled buttons and banners, written on in white. A Tk button also needs
# activeforeground, or its words turn black under the pointer. -------------
TEXT_ON_FILL = '#FFFFFF'
TEXT_ON_FILL_MUTED = '#AACCEE'   # second line on a dark banner (pale: blue)
# Red means energized, wherever it is: the LIVE run button, and an SG or PSU
# Output: ON (an SG output can drive the Trek). The DRY run button is blue.
# Normal and pointer-over colors of the one stay 21.5 or more from both of
# the other's under every simulated vision.
FILL_DRY = '#2255AA'          # ▶ Run (DRY), no HV (dark: sapphire)
FILL_DRY_ACTIVE = '#004488'   # the same under the pointer (high-contrast blue)
FILL_LIVE = '#CC4466'         # ▶ Run, LIVE HV, and Output: ON (dark: red)
FILL_LIVE_ACTIVE = '#994455'  # the same under the pointer (medium: dark red)
BANNER_ALERT = '#775500'     # a state banner over an image (dark: brown)
BANNER_ERROR = '#993366'     # a frame that cannot be shown (dark: maroon)
BANNER_INFO = '#004488'      # the splash, a loaded run (high-contrast blue)
BANNER_EMPTY = '#444444'     # nothing loaded (dark: grey)

# ---- backgrounds written on in black ---------------------------------------
ROW_DRY = '#AACCEE'          # the DRY RUN row (pale: blue)
ROW_LIVE = '#EE8866'         # the LIVE row (light: orange). Tol's pale red
#                              is only 10.6 from the pale blue for a
#                              protanope; this is 36.8.
TOOLTIP_BG = '#EEEEBB'       # hover help (pale: yellow)
PALE_CODE = '#DDDDDD'        # a code sample in help text (pale: grey)

# ---- words on a dark image canvas -------------------------------------------
TEXT_ON_DARK = '#DDDDDD'     # a hint over an empty viewer (pale: grey)
