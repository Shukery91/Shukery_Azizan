"""Presenter-led 2.5D explainer renderer (bg -> original -> graphics -> presenter cut-out -> subtitles)."""
import json, math, os, subprocess, sys
from multiprocessing import Pool
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
W_ = os.path.join(HERE, "work")
FD = os.path.join(HERE, "..", "fonts")
U = "/root/.claude/uploads/bd1e6249-bf6e-5c96-a56f-a87bb5527365"
TALK = f"{U}/97ffe4d7-IMG_0814.MOV"
MUSIC = f"{U}/2c4e060a-berdamai_dengna_takdir_instrumental.mp3"
OUT = "/home/user/Shukery_Azizan/video/C_Explainer_Kahwin_Tanpa_Couple.mp4"
W, H, FPS = 1080, 1920, 30

TL = json.load(open(f"{W_}/timeline.json"))
FRAMES, WORDS, VEND, TOTAL = TL["frames"], TL["words"], TL["voice_end"], TL["total"]
NF = len(FRAMES)

# ---------------- fonts / colours ----------------
def F(name, size):
    return ImageFont.truetype(os.path.join(FD, name), size)

SUB = F("Inter-Medium.ttf", 54)
SUB_AR = F("Amiri-Regular.ttf", 60)
SERIF = F("Cormorant-SemiBold.ttf", 100)
SERIF_IT = F("Cormorant-SemiBoldItalic.ttf", 98)
SERIF_IT_S = F("Cormorant-SemiBoldItalic.ttf", 54)
AR_BIG = F("Amiri-Regular.ttf", 80)
AR_S = F("Amiri-Regular.ttf", 46)
LABEL = F("Inter-Light.ttf", 32)
SMALL = F("Inter-Light.ttf", 30)
PILL = F("Inter-Medium.ttf", 40)
STEP = F("Inter-Medium.ttf", 34)
CTA = F("Inter-Medium.ttf", 50)
NUM = F("Inter-Medium.ttf", 28)
HEART = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)

WHITE = (246, 242, 234)
GOLD = (233, 200, 128)
ROSE = (214, 162, 160)
NAVY_T, NAVY_B = np.array([30, 44, 56], np.float32), np.array([9, 15, 21], np.float32)

KEYS = {"Khadijah", "berzina", "appreciated,", "sehidup", "semati", "Ajari", "Aku", "Tinggalkan", "Maksiat,",
        "step", "one", "by", "sunnah", "jodoh", "soleh", "solehah."}


# ---------------- helpers ----------------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return x * x * x * (x * (6 * x - 15) + 10)


def fade(t, t0, d=0.5):
    return ease((t - t0) / d)


def word_t(text, after=0.0):
    for a, b, w, p in WORDS:
        if a >= after - 0.01 and w.strip(",.?…").lower() == text.lower():
            return a
    raise KeyError(text)


# scene boundaries (output seconds) from the piece list
_b, _t = [], 0.0
for a, b, _ in TL["pieces"]:
    _b.append(_t); _t += round((b - a) * FPS) / FPS
S1, S2, S3, S4a, S4b, S4c, S5a, S5b, S6 = _b[0], _b[1], _b[2], _b[4], _b[5], _b[6], _b[7], _b[8], _b[9]
OUTRO = VEND

# triggers
T_NABI = word_t("Nabi", S2)
T_DENGAN = word_t("dengan", T_NABI)
T_KHAD = word_t("Khadijah", S2)
T_COUPLE1 = word_t("couple", T_KHAD)
T_BARAT = word_t("Barat", S3)
T_COUPLE2 = word_t("couple", T_BARAT + 0.5)
T_ZINA = word_t("berzina", S3)
T_KAHWIN = word_t("kahwin", T_ZINA)
T_SEHIDUP = word_t("sehidup", S4a)
T_BUKU = word_t("buku", S5a)
T_STEP = word_t("step", S5a)
T_SUNNAH = word_t("sunnah", S5a)

# presenter state transitions: (start, duration, {key: target})
STATE0 = dict(s=1.0, dx=0.0, dy=0.0, cut=0.0, pal=1.0, glow=0.0)
TRANS = [
    (0.0, S2, dict(s=1.035)),                                   # slow push-in, hook
    (S2 - 0.05, 0.55, dict(cut=1.0, glow=1.0)),
    (S2 + 0.35, 0.95, dict(s=0.84, dx=250.0)),
    (S3 + 0.15, 1.1, dict(dx=-250.0)),
    (S4a - 0.05, 0.95, dict(s=1.0, dx=0.0)),
    (S4a + 0.85, 0.6, dict(cut=0.0, glow=0.0)),
    (S4a + 1.4, S5a - S4a - 1.8, dict(s=1.04)),
    (S5a - 0.1, 0.55, dict(cut=1.0, glow=1.0)),
    (S5a + 0.3, 0.95, dict(s=0.8, dx=-270.0)),
    (S6 + 0.05, 0.95, dict(s=1.0, dx=0.0)),
    (S6 + 0.95, 0.6, dict(cut=0.0, glow=0.0)),
    (S6 + 1.5, OUTRO - S6 - 1.5, dict(s=1.035)),
    (OUTRO - 0.05, 0.5, dict(cut=1.0, glow=1.0)),
    (OUTRO + 0.05, 0.8, dict(pal=0.0, s=0.96)),
]


def state(t):
    st = dict(STATE0)
    for t0, d, tgt in TRANS:
        if t < t0:
            continue
        p = ease((t - t0) / d) if d > 0 else 1.0
        for k, v in tgt.items():
            st[k] = st[k] + (v - st[k]) * p
    return st


def camera(t):
    # very slow drift: parallax cue, never busy
    return 7.0 * math.sin(2 * math.pi * t / 13.0), 5.0 * math.sin(2 * math.pi * t / 17.0 + 1.0)


# ---------------- static assets ----------------
def make_bg():
    g = np.linspace(0, 1, H + 80, dtype=np.float32)[:, None, None]
    base = NAVY_T * (1 - g) + NAVY_B * g
    base = np.repeat(base, W + 80, axis=1)
    plate = cv2.imread(f"{W_}/plate.jpg")[:, :, ::-1].astype(np.float32)
    plate = cv2.resize(plate, (W + 80, H + 80))
    base = base * 0.78 + plate * 0.22 * 0.55
    return base


BG = make_bg()
YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)
GLOW = np.exp(-(((XX - 540) / 420) ** 2 + ((YY - 820) / 560) ** 2))[..., None] * np.array([70, 52, 30], np.float32)
VIG_SRC = None

rng = np.random.default_rng(7)
BOKEH = [dict(x=rng.uniform(0, W), y=rng.uniform(0, H), r=rng.uniform(10, 34), a=rng.uniform(0.05, 0.16),
              vy=rng.uniform(-9, -3), d=rng.uniform(0.3, 0.6)) for _ in range(22)]


def bokeh_sprite(r):
    s = int(r * 3)
    yy, xx = np.mgrid[-s:s + 1, -s:s + 1].astype(np.float32)
    d = np.sqrt(xx ** 2 + yy ** 2)
    return np.clip((r - d) / (r * 0.35), 0, 1) ** 1.5


SPR = {}

BOOK = Image.open(f"{W_}/book.png").convert("RGBA")


def edge_ramp(h=1280, w=720, px=36):
    r = np.ones((h, w), np.float32)
    ramp = np.linspace(0, 1, px, dtype=np.float32)
    r[:, :px] *= ramp[None, :]
    r[:, -px:] *= ramp[None, ::-1]
    r[-40:, :] *= np.linspace(1, 0, 40, dtype=np.float32)[:, None]
    # drop the stray blue print in the bottom-left corner of the source
    blk = np.ones((h, w), np.float32)
    blk[1150:, :240] = 0
    blk = cv2.GaussianBlur(blk, (0, 0), 18)
    return r * blk


RAMP = edge_ramp()


def make_bag(size=180):
    S = size * 4
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    body = [S * 0.14, S * 0.34, S * 0.86, S * 0.92]
    # soft shadow
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([body[0] + 10, body[1] + 26, body[2] + 10, body[3] + 26], radius=S * 0.09,
                                         fill=(0, 0, 0, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(S * 0.03))
    im.alpha_composite(sh)
    d = ImageDraw.Draw(im)
    d.arc([S * 0.32, S * 0.10, S * 0.68, S * 0.56], 180, 360, fill=(214, 150, 10, 255), width=int(S * 0.055))
    d.rounded_rectangle(body, radius=S * 0.09, fill=(255, 196, 28, 255))
    d.rounded_rectangle([body[0], body[1], body[2], body[1] + S * 0.12], radius=S * 0.06, fill=(255, 212, 80, 255))
    for cx in (0.35, 0.65):
        d.ellipse([S * cx - S * 0.035, S * 0.40, S * cx + S * 0.035, S * 0.47], fill=(196, 135, 8, 255))
    return im.resize((size, size), Image.LANCZOS)


BAG = make_bag(230)

_g = (np.clip(1 - np.linspace(0, 1, 560), 0, 1) ** 1.0 * 205).astype(np.uint8)


def TOPSHADE_IM(a):
    im = np.zeros((H, W, 4), np.uint8)
    im[:560, :, 0:3] = (12, 16, 20)
    im[:560, :, 3] = (_g * a).astype(np.uint8)[:, None]
    return Image.fromarray(im, "RGBA")


# ---------------- drawing helpers (PIL overlay) ----------------
def spaced(d, xy, text, font, fill, spacing, anchor_center=True):
    widths = [font.getlength(c) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    if anchor_center:
        x -= total / 2
    for c, w in zip(text, widths):
        d.text((x, y), c, font=font, fill=fill, anchor="lm")
        x += w + spacing


def shadowed(ov, draw_fn, blur=8, alpha=150):
    sh = Image.new("RGBA", ov.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(sh), (0, 0, 0, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    ov.alpha_composite(sh)
    draw_fn(ImageDraw.Draw(ov), None)


def rgba(c, a):
    return (c[0], c[1], c[2], int(255 * clamp(a)))


def text_fade(ov, t, t0, xy, text, font, color, rise=14, out_t=None, glow=False, dur=0.6):
    a = fade(t, t0, dur)
    if out_t is not None:
        a *= 1 - fade(t, out_t, 0.5)
    if a <= 0:
        return
    x, y = xy[0], xy[1] + rise * (1 - a)

    def fn(d, col):
        d.text((x, y), text, font=font, fill=(col if col else rgba(color, a)) if col is None else (0, 0, 0, int(150 * a)),
               anchor="mm")
    shadowed(ov, fn, blur=10 if glow else 7)


def line_draw(d, t, t0, p0, p1, color, width=3, dur=0.6, out_t=None, a_mul=1.0):
    p = ease((t - t0) / dur)
    a = a_mul * (1 - (fade(t, out_t, 0.5) if out_t else 0))
    if p <= 0 or a <= 0:
        return
    x = p0[0] + (p1[0] - p0[0]) * p
    y = p0[1] + (p1[1] - p0[1]) * p
    d.line([p0, (x, y)], fill=rgba(color, a), width=width)


# ---------------- subtitles ----------------
PHRASES = {}
for a, b, w, p in WORDS:
    PHRASES.setdefault(p, []).append((a, b, w))
PH_LIST = sorted(PHRASES.items())


def layout(words, maxw=860):
    items = []
    for a, b, w in words:
        if "ﷺ" in w:
            w = "ﷺ"
        f = SUB_AR if "ﷺ" in w else SUB
        items.append((a, b, w, f, f.getlength(w)))
    sp = SUB.getlength(" ")
    lines, cur, cw = [], [], 0
    for it in items:
        add = it[4] + (sp if cur else 0)
        if cur and cw + add > maxw:
            lines.append(cur); cur, cw = [], 0; add = it[4]
        cur.append(it); cw += add
    if cur:
        lines.append(cur)
    out = []
    lh = 66
    y0 = 1372 - (len(lines) - 1) * lh / 2
    for li, ln in enumerate(lines):
        tw = sum(i[4] for i in ln) + sp * (len(ln) - 1)
        x = 540 - tw / 2
        for it in ln:
            out.append((it, x, y0 + li * lh))
            x += it[4] + sp
    return out


LAYOUTS = {p: layout(ws) for p, ws in PH_LIST}


def draw_subs(ov, t):
    for idx, (p, ws) in enumerate(PH_LIST):
        start = ws[0][0] - 0.1
        nxt = PH_LIST[idx + 1][1][0][0] - 0.1 if idx + 1 < len(PH_LIST) else 1e9
        end = min(ws[-1][1] + 0.7, nxt)
        if not (start <= t < end):
            continue
        out_a = 1 - ease((t - (end - 0.2)) / 0.2) if end - t < 0.2 and end != nxt else 1.0
        sub = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
        y_off = 1372 - 150
        items = []
        for (a, b, w, f, wl), x, y in LAYOUTS[p]:
            al = ease((t - a + 0.06) / 0.3) * out_a
            if al <= 0:
                continue
            col = GOLD if w in KEYS else WHITE
            items.append((x, y - y_off + 8 * (1 - al), w, f, col, al))

        def fn(d, col_override):
            for x, y, w, f, col, al in items:
                fill = (0, 0, 0, int(170 * al)) if col_override else rgba(col, al)
                d.text((x, y), w, font=f, fill=fill, anchor="lm")
        shadowed(sub, fn, blur=6)
        ov.alpha_composite(sub, (0, y_off))


# ---------------- scene graphics ----------------
def draw_graphics(ov, t, cam):
    gx, gy = cam[0] * 0.7, cam[1] * 0.7
    d = ImageDraw.Draw(ov)
    # S2: Nabi & Khadijah
    if S2 <= t < S3 + 1.0:
        out_t = S3 + 0.45
        cx = 290 + gx
        a = fade(t, T_NABI, 0.6) * (1 - fade(t, out_t, 0.5))
        if a > 0:
            y = 520 + gy + 14 * (1 - fade(t, T_NABI, 0.6))
            wn = SERIF.getlength("Nabi ")
            war = AR_BIG.getlength("ﷺ")
            x0 = cx - (wn + war) / 2

            def fn(dd, c):
                dd.text((x0, y), "Nabi", font=SERIF, fill=(0, 0, 0, int(140 * a)) if c else rgba(WHITE, a), anchor="lm")
                dd.text((x0 + wn, y + 6), "ﷺ", font=AR_BIG, fill=(0, 0, 0, int(140 * a)) if c else rgba(GOLD, a), anchor="lm")
            shadowed(ov, fn)
        line_draw(d, t, T_DENGAN, (cx, 590 + gy), (cx, 700 + gy), GOLD, 2, 0.7, out_t, 0.8)
        ha = fade(t, T_DENGAN + 0.35, 0.5) * (1 - fade(t, out_t, 0.5))
        if ha > 0:
            d.ellipse([cx - 30, 615 + gy, cx + 30, 675 + gy], fill=(18, 26, 34, int(255 * ha)))
            d.text((cx, 646 + gy), "♡", font=HEART, fill=rgba(GOLD, ha), anchor="mm")
        text_fade(ov, t, T_KHAD, (cx, 770 + gy), "Khadijah", SERIF, WHITE, out_t=out_t)
        text_fade(ov, t, T_KHAD + 0.2, (cx, 845 + gy), "r.a.", SMALL, WHITE, out_t=out_t)
        line_draw(d, t, T_COUPLE1 - 0.1, (cx - 70, 915 + gy), (cx + 70, 915 + gy), GOLD, 2, 0.5, out_t, 0.7)
        ca = fade(t, T_COUPLE1, 0.6) * (1 - fade(t, out_t, 0.5))
        if ca > 0:
            spaced(d, (cx, 970 + gy + 10 * (1 - ca)), "TAK PERNAH COUPLE", LABEL, rgba(GOLD, ca), 6)
    # S3: budaya Barat chain
    if S3 <= t < S4a + 0.9:
        out_t = S4a + 0.3
        cx = 755 + gx
        la = fade(t, T_BARAT, 0.6) * (1 - fade(t, out_t, 0.5))
        if la > 0:
            spaced(d, (cx, 430 + gy), "BUDAYA BARAT", LABEL, rgba(WHITE, 0.75 * la), 7)
            d.line([(cx - 60, 470 + gy), (cx + 60, 470 + gy)], fill=rgba(WHITE, 0.4 * la), width=2)
        pills = [(T_COUPLE2, "Couple", 560), (T_ZINA, "Zina", 730), (T_KAHWIN, "Baru kahwin", 900)]
        for i, (tp, txt, y) in enumerate(pills):
            pa = fade(t, tp - 0.05, 0.55) * (1 - fade(t, out_t, 0.5))
            if pa <= 0:
                continue
            yy = y + gy + 12 * (1 - pa)
            wpx = PILL.getlength(txt) + 90
            d.rounded_rectangle([cx - wpx / 2, yy - 42, cx + wpx / 2, yy + 42], radius=42,
                                fill=(14, 20, 27, int(170 * pa)), outline=rgba(ROSE, pa), width=2)
            d.text((cx, yy), txt, font=PILL, fill=rgba(WHITE, pa), anchor="mm")
            if i < 2:
                nt = pills[i + 1][0]
                y0, y1 = y + 48 + gy, pills[i + 1][2] - 50 + gy
                line_draw(d, t, nt - 0.55, (cx, y0), (cx, y1), ROSE, 2, 0.5, out_t)
                aa = fade(t, nt - 0.1, 0.3) * (1 - fade(t, out_t, 0.5))
                if aa > 0:
                    d.line([(cx - 10, y1 - 12), (cx, y1), (cx + 10, y1 - 12)], fill=rgba(ROSE, aa), width=2, joint="curve")
    # S4: keyword behind the head
    if S4a <= t < S5a + 0.6:
        out_t = S5a + 0.1
        da = fade(t, T_SEHIDUP - 0.4, 0.9) * (1 - fade(t, out_t, 0.5))
        if da > 0:
            ov.alpha_composite(TOPSHADE_IM(da))
        text_fade(ov, t, T_SEHIDUP - 0.1, (540 + gx, 238 + gy), "sehidup semati", SERIF_IT, GOLD, out_t=out_t,
                  glow=True, dur=0.9)
    # S5: book + steps
    if S5a <= t < S6 + 1.0:
        out_t = S6 + 0.45
        cx = 760 + gx
        ba = fade(t, T_BUKU - 0.1, 0.7) * (1 - fade(t, out_t, 0.5))
        if ba > 0:
            k = ease((t - T_STEP + 0.2) / 0.9)
            h = 560 + (300 - 560) * k
            cy = 650 + (390 - 650) * k + 6 * math.sin(2 * math.pi * t / 5.0) + gy + 16 * (1 - ba)
            bw = int(BOOK.width * h / BOOK.height)
            bk = BOOK.resize((bw, int(h)), Image.LANCZOS)
            if ba < 1:
                al = bk.getchannel("A").point(lambda v: int(v * ba))
                bk.putalpha(al)
            sh = Image.new("RGBA", (bw + 80, int(h) + 80), (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle([40, 50, bw + 40, int(h) + 40], radius=12, fill=(0, 0, 0, int(150 * ba)))
            sh = sh.filter(ImageFilter.GaussianBlur(22))
            ov.alpha_composite(sh, (int(cx - bw / 2 - 30), int(cy - h / 2 - 30)))
            ov.alpha_composite(bk, (int(cx - bw / 2), int(cy - h / 2)))
        steps = ["Persediaan diri", "Orang tengah", "Ta'aruf & istikharah", "Khitbah → nikah"]
        x0 = 600 + gx
        for i, s in enumerate(steps):
            ts = T_STEP + 0.45 + i * 0.5
            sa = fade(t, ts, 0.5) * (1 - fade(t, out_t, 0.5))
            if sa <= 0:
                continue
            y = 640 + i * 108 + gy + 10 * (1 - sa)
            if i > 0:
                yp = 640 + (i - 1) * 108 + gy
                line_draw(d, t, ts - 0.25, (x0, yp + 26), (x0, yp + 82), GOLD, 2, 0.3, out_t, 0.6)
            d.ellipse([x0 - 24, y - 24, x0 + 24, y + 24], fill=(14, 20, 27, int(200 * sa)), outline=rgba(GOLD, sa), width=2)
            d.text((x0, y + 1), str(i + 1), font=NUM, fill=rgba(GOLD, sa), anchor="mm")
            d.text((x0 + 44, y), s, font=STEP, fill=rgba(WHITE, sa), anchor="lm")
        ta = fade(t, T_SUNNAH - 0.1, 0.6) * (1 - fade(t, out_t, 0.5))
        if ta > 0:
            y = 1090 + gy + 10 * (1 - ta)
            w1 = SERIF_IT_S.getlength("ikut sunnah Nabi ")
            w2 = AR_S.getlength("ﷺ")
            xx = cx - (w1 + w2) / 2
            d.text((xx, y), "ikut sunnah Nabi", font=SERIF_IT_S, fill=rgba(GOLD, ta), anchor="lm")
            d.text((xx + w1, y + 4), "ﷺ", font=AR_S, fill=rgba(GOLD, ta), anchor="lm")
    # outro: book + yellow bag + arrow (no words)
    if t >= OUTRO:
        ba = fade(t, OUTRO + 0.15, 0.8)
        h = 660
        cy = 640 + 8 * math.sin(2 * math.pi * (t - OUTRO) / 4.0) + 20 * (1 - ba) + gy
        bw = int(BOOK.width * h / BOOK.height)
        bk = BOOK.resize((bw, h), Image.LANCZOS)
        bk.putalpha(bk.getchannel("A").point(lambda v: int(v * ba)))
        sh = Image.new("RGBA", (bw + 120, h + 120), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([60, 80, bw + 60, h + 60], radius=14, fill=(0, 0, 0, int(160 * ba)))
        sh = sh.filter(ImageFilter.GaussianBlur(28))
        ov.alpha_composite(sh, (int(540 + gx - bw / 2 - 50), int(cy - h / 2 - 50)))
        ov.alpha_composite(bk, (int(540 + gx - bw / 2), int(cy - h / 2)))
        ga = fade(t, OUTRO + 0.75, 0.6)
        if ga > 0:
            sc = 0.9 + 0.1 * ga
            sz = int(BAG.width * sc)
            bg_ = BAG.resize((sz, sz), Image.LANCZOS)
            bg_.putalpha(bg_.getchannel("A").point(lambda v: int(v * ga)))
            ov.alpha_composite(bg_, (int(540 - sz / 2), int(1140 - sz / 2)))
        ca = fade(t, OUTRO + 0.95, 0.6)
        if ca > 0:
            text_fade(ov, t, OUTRO + 0.95, (540, 1330), "Beg kuning di bawah", CTA, (255, 205, 60))
        aa = fade(t, OUTRO + 1.15, 0.5)
        if aa > 0:
            ph = (t - OUTRO - 1.15)
            for k in range(2):
                off = 10 * (0.5 - 0.5 * math.cos(2 * math.pi * ph / 1.3))
                y = 1395 + k * 44 + off
                al = aa * (0.95 - 0.35 * k)
                d.line([(500, y), (540, y + 34), (580, y)], fill=(255, 196, 28, int(255 * al)), width=12, joint="curve")


# ---------------- frame compositor ----------------
def render_frame(i, cache):
    t = i / FPS
    st = state(t)
    cam = camera(t)
    src_t = FRAMES[i]
    k = min(2144, int(round(src_t * FPS)))
    while not os.path.exists(f"{W_}/src/{k:05d}.jpg"):
        k -= 1
    if cache.get("k") != k:
        fr = cv2.imread(f"{W_}/src/{k:05d}.jpg")[:, :, ::-1]
        m = cv2.imread(f"{W_}/mask/{k:05d}.png", 0).astype(np.float32) / 255 * RAMP
        cache.update(k=k, fr=fr, m=m)
    fr, m = cache["fr"], cache["m"]

    # background (depth 0.35)
    bx, by = 40 + cam[0] * 0.35, 40 + cam[1] * 0.35
    M = np.float32([[1, 0, -bx], [0, 1, -by]])
    bg = cv2.warpAffine(BG, M, (W, H), flags=cv2.INTER_LINEAR)
    bg += GLOW * st["glow"] * 0.8
    for b in BOKEH:
        r = b["r"]
        key = int(r)
        if key not in SPR:
            SPR[key] = bokeh_sprite(key)
        sp = SPR[key]
        y = (b["y"] + b["vy"] * t + cam[1] * b["d"]) % (H + 200) - 100
        x = b["x"] + cam[0] * b["d"]
        x0, y0 = int(x) - sp.shape[1] // 2, int(y) - sp.shape[0] // 2
        xa, ya = max(0, x0), max(0, y0)
        xb, yb = min(W, x0 + sp.shape[1]), min(H, y0 + sp.shape[0])
        if xa < xb and ya < yb:
            bg[ya:yb, xa:xb] += sp[ya - y0:yb - y0, xa - x0:xb - x0, None] * (255 * b["a"]) * np.array([1.0, 0.85, 0.6])
    comp = bg

    # presenter transform (anchor bottom-centre), depth 1.0
    s = st["s"] * 1.5
    tx = 540 - 540 * st["s"] + st["dx"] + cam[0]
    ty = 1920 * (1 - st["s"]) + st["dy"] + cam[1]
    M = np.float32([[s, 0, tx], [0, s, ty]])
    frw = cv2.warpAffine(fr, M, (W, H), flags=cv2.INTER_LINEAR).astype(np.float32)
    if st["cut"] < 1:
        cov = cv2.warpAffine(np.ones(fr.shape[:2], np.float32), M, (W, H))[..., None] * (1 - st["cut"])
        comp = comp * (1 - cov) + frw * cov
    # mid graphics (behind presenter)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_graphics(ov, t, cam)
    ova = np.asarray(ov).astype(np.float32)
    a = ova[..., 3:] / 255
    comp = comp * (1 - a) + ova[..., :3] * a
    # presenter cut-out
    mw = cv2.warpAffine(m, M, (W, H))[..., None] * st["pal"]
    if st["pal"] > 0:
        comp = comp * (1 - mw) + frw * mw
    # subtitles
    so = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_subs(so, t)
    soa = np.asarray(so).astype(np.float32)
    a = soa[..., 3:] / 255
    comp = comp * (1 - a) + soa[..., :3] * a
    return np.clip(comp, 0, 255).astype(np.uint8)


def worker(args):
    wi, a, b = args
    out = f"{W_}/seg_{wi}.mp4"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "13",
                          "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    cache = {}
    for i in range(a, b):
        p.stdin.write(render_frame(i, cache).tobytes())
    p.stdin.close(); p.wait()
    return out


def audio(out_wav):
    ins, fc, labels = [], [], []
    for n, (a, b, _) in enumerate(TL["pieces"]):
        fc.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,afade=t=in:d=0.015,afade=t=out:st={b - a - 0.02:.3f}:d=0.02[p{n}]")
        labels.append(f"[p{n}]")
    fc.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1,highpass=f=70,afftdn=nf=-28,"
              "acompressor=threshold=-20dB:ratio=3:attack=10:release=160,loudnorm=I=-15:TP=-2:LRA=7,"
              f"aresample=48000,apad,atrim=0:{TOTAL}[vo]")
    fc.append("[vo]asplit[v1][key]")
    fc.append(f"[1:a]atrim=0:{TOTAL},asetpts=PTS-STARTPTS,aresample=48000,volume=-5dB,afade=t=in:d=1.2,"
              f"afade=t=out:st={TOTAL - 1.6:.2f}:d=1.6[mus]")
    fc.append("[mus][key]sidechaincompress=threshold=0.025:ratio=7:attack=40:release=700[duck]")
    fc.append("[v1][duck]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=9[out]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", TALK, "-i", MUSIC, "-filter_complex", ";".join(fc),
                    "-map", "[out]", "-ar", "48000", out_wav], check=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "still":
        cache = {}
        for t in map(float, sys.argv[2:]):
            Image.fromarray(render_frame(min(NF - 1, int(t * FPS)), cache)).save(f"{W_}/still_{t:05.2f}.png")
        return
    n = 4
    cuts = [round(NF * k / n) for k in range(n + 1)]
    with Pool(n) as pool:
        segs = pool.map(worker, [(k, cuts[k], cuts[k + 1]) for k in range(n)])
    lst = f"{W_}/segs.txt"
    open(lst, "w").write("".join(f"file '{s}'\n" for s in segs))
    wav = f"{W_}/mix.wav"
    audio(wav)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    vf = ("eq=contrast=1.03:saturation=0.96,colorbalance=rs=0.03:gs=0.01:bs=-0.03:rh=0.02:bh=-0.02,"
          "vignette=angle=PI/5.2,noise=alls=2:allf=t")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", wav,
                    "-vf", vf, "-map", "0:v", "-map", "1:a", "-t", f"{TOTAL}", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", "30", "-c:a", "aac",
                    "-b:a", "192k", "-movflags", "+faststart", OUT], check=True)
    print(OUT)


if __name__ == "__main__":
    main()
