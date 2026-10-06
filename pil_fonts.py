#!/usr/bin/env python3
"""PIL fonts for text the Tk tools draw INTO images.

One fallback chain, cached per size, shared by Edge Review's letter tags
(sldea_edge_gui._tag_font, #173) and the SLDEA live view's banners
(sldea_liveview, #376). It lives in its own small module so the live view
does not have to import the whole Edge Review program to get it.

The chain: a bold TrueType face (Windows arialbd, Linux DejaVuSans-Bold),
then the regular faces, then PIL's built-in font at the size asked for
(Pillow 10.1 and later), and last the fixed-size built-in bitmap font of
older Pillow. The TrueType steps come first because the built-in bitmap
is unreadably small on a picture (#173), and on an older Pillow it is the
only size there is.
"""

BOLD_CHAIN = ('arialbd.ttf', 'DejaVuSans-Bold.ttf', 'arial.ttf',
              'DejaVuSans.ttf')

_CACHE = {}


def bold_font(size):
    """A PIL font about `size` px high, bold where a bold face resolves.
    Cached per size: a font is built once per process, not once per
    drawing."""
    size = int(size)
    font = _CACHE.get(size)
    if font is None:
        from PIL import ImageFont
        for name in BOLD_CHAIN:
            try:
                font = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        else:
            try:
                font = ImageFont.load_default(size)
            except TypeError:              # Pillow < 10.1: no size arg
                font = ImageFont.load_default()
        _CACHE[size] = font
    return font
