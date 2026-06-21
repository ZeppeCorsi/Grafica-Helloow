"""Gera os PNGs do logo Zappe Hub (icone 500x500 + logo completo)."""
from PIL import Image, ImageDraw, ImageFont

INDIGO = (85, 70, 232, 255)   # #5546E8
INK = (30, 35, 48, 255)       # #1E2330
AMBER = (255, 176, 32, 255)   # #FFB020
BRANCO = (255, 255, 255, 255)

bold = "C:/Windows/Fonts/arialbd.ttf"


def icone(tam=500):
    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = tam / 80.0
    # balao (quadrado arredondado) + cauda
    d.rounded_rectangle([8 * s, 12 * s, 72 * s, 68 * s], radius=16 * s, fill=INDIGO)
    d.polygon([(24 * s, 68 * s), (24 * s, 82 * s), (42 * s, 68 * s)], fill=INDIGO)
    # Z
    fz = ImageFont.truetype(bold, int(30 * s))
    d.text((40 * s, 35 * s), "Z", font=fz, fill=BRANCO, anchor="mm")
    # 3 pontinhos (um laranja)
    r = 4 * s
    for cx, cor in [(29, BRANCO), (40, BRANCO), (51, AMBER)]:
        d.ellipse([cx * s - r, 56 * s - r, cx * s + r, 56 * s + r], fill=cor)
    img.save("zappehub-icone.png")
    print("zappehub-icone.png", img.size)


def logo():
    s = 4
    img = Image.new("RGBA", (262 * s, 88 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4 * s, 8 * s, 66 * s, 62 * s], radius=15 * s, fill=INDIGO)
    d.polygon([(18 * s, 62 * s), (18 * s, 74 * s), (36 * s, 62 * s)], fill=INDIGO)
    fz = ImageFont.truetype(bold, int(26 * s))
    d.text((35 * s, 33 * s), "Z", font=fz, fill=BRANCO, anchor="mm")
    r = 3.6 * s
    for cx, cor in [(25, BRANCO), (35, BRANCO), (45, AMBER)]:
        d.ellipse([cx * s - r, 50 * s - r, cx * s + r, 50 * s + r], fill=cor)
    # wordmark
    fw = ImageFont.truetype(bold, int(28 * s))
    x0, base = 80 * s, 48 * s
    d.text((x0, base), "Zappe", font=fw, fill=INK, anchor="ls")
    w1 = d.textlength("Zappe", font=fw)
    d.text((x0 + w1, base), " Hub", font=fw, fill=INDIGO, anchor="ls")
    w2 = d.textlength(" Hub", font=fw)
    rd = 5 * s
    dot_x = x0 + w1 + w2 + 12 * s
    d.ellipse([dot_x - rd, 44 * s - rd, dot_x + rd, 44 * s + rd], fill=AMBER)
    img.save("zappehub-logo.png")
    print("zappehub-logo.png", img.size)


icone()
logo()
