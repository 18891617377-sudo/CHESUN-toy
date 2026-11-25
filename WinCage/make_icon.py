"""Generate WinCage Metro-style app icon (multi-size ICO + preview PNG).

Pure Pillow, no external assets. Design: Win8 tile blue with a white
"cage" glyph (window inside bars) - matches the app name and tile UI.
"""
from PIL import Image, ImageDraw

OUT_ICO = r"C:\Users\18891\WorkBuddy\2026-11-24-18-10-45\WinCage\app.ico"
OUT_PNG = r"C:\Users\18891\WorkBuddy\2026-11-24-18-10-45\WinCage\app_icon.png"
S = 256
BLUE_TOP = (18, 132, 214)
BLUE_BOT = (8, 90, 164)
WHITE = (255, 255, 255)
SHADOW = (5, 62, 120)


def build(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / S

    def P(*pts):
        return [(int(x * s), int(y * s)) for x, y in pts]

    # gradient background (vertical)
    for y in range(size):
        t = y / max(1, size - 1)
        c = tuple(int(BLUE_TOP[i] + (BLUE_BOT[i] - BLUE_TOP[i]) * t) for i in range(3))
        d.line([(0, y), (size, y)], fill=c + (255,))

    # cage outer frame
    lw = max(2, int(13 * s))
    d.rounded_rectangle(P((58, 56), (198, 200)), radius=int(14 * s),
                        outline=WHITE + (255,), width=lw)
    # top bar
    d.line(P((72, 88), (184, 88)), fill=WHITE + (255,), width=max(2, int(11 * s)))
    # three vertical bars (the "cage")
    for x in (98, 128, 158):
        d.line(P((x, 96), (x, 186)), fill=WHITE + (255,), width=max(2, int(10 * s)))
    # small base line
    d.line(P((72, 186), (184, 186)), fill=WHITE + (255,), width=max(2, int(8 * s)))

    return img


if __name__ == "__main__":
    master = build(S)
    master.save(OUT_PNG)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(OUT_ICO, format="ICO", sizes=sizes)
    print("ICO:", OUT_ICO)
    print("PNG:", OUT_PNG)
    from PIL import IcoImagePlugin
    with IcoImagePlugin.IcoFile(OUT_ICO) as ico:
        for sz in sizes:
            print("  size", sz, "->", ico.getimage(sz).size)
