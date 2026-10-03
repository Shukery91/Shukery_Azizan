#!/usr/bin/env python3
"""Build two 40s vertical edits (A: kinetic captions, B: minimal cinematic)."""
import os, re, subprocess, sys

U = "/root/.claude/uploads/bd1e6249-bf6e-5c96-a56f-a87bb5527365"
S = os.path.dirname(os.path.abspath(__file__))
OUT = "/home/user/Shukery_Azizan/video"
FONTS = os.path.join(S, "fonts")
TMP = os.path.join(S, "work")
os.makedirs(TMP, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

AUDIO = f"{U}/486ebb41-Audio_Bukti_Cinta_Seorang_Lelaki.mp3"
SRC = {
    "toc": f"{U}/60a45c1d-IMG_0781.MOV",
    "page": f"{U}/972c88ba-video6273930579222208685.mp4",
    "cover": f"{U}/a34d21e4-IMG_0777.MOV",
    "quote": f"{U}/d9dc55f9-IMG_0779.MOV",
}
W, H, FPS, TOTAL = 1080, 1920, 30, 40.0

# ---------- grades ----------
G = {
    "punch": "eq=contrast=1.08:saturation=1.1",
    "desat": "eq=contrast=1.05:brightness=-0.04:saturation=0.3,colorbalance=bs=0.05:bm=0.03",
    "warm": "eq=contrast=1.06:brightness=0.02:saturation=1.15,colorbalance=rs=0.07:gs=0.02:bs=-0.07:rm=0.05:bm=-0.05",
    "soft": "eq=saturation=0.8:brightness=-0.03,colorbalance=rs=0.05:bs=-0.04,vignette=angle=PI/3.2,gblur=sigma=1.2",
    # B: muted filmic teal/orange
    "film": "eq=contrast=1.1:saturation=0.7:brightness=-0.02,colorbalance=rs=-0.04:bs=0.07:rh=0.06:bh=-0.05,vignette=angle=PI/4.5,noise=alls=3:allf=t",
    "filmwarm": "eq=contrast=1.08:saturation=0.85,colorbalance=rs=0.04:bs=-0.03:rh=0.07:bh=-0.06,vignette=angle=PI/4.5,noise=alls=3:allf=t",
    "dark": "eq=brightness=-0.22:saturation=0.5,gblur=sigma=6,vignette=angle=PI/3.5,noise=alls=3:allf=t",
    "darker": "eq=brightness=-0.38:saturation=0.4,gblur=sigma=14,vignette=angle=PI/3.5",
}


def shot(name, src, ss, dur, z0=1.0, z1=1.1, cx=0.5, cy=0.5, speed=1.0, grade="punch",
         fin=None, fout=None, size=(W, H)):
    """Render one shot to an intermediate clip of exactly `dur` seconds."""
    out = os.path.join(TMP, name + ".mp4")
    src_dur = dur * speed + 0.1
    pre = []
    if speed < 1.0:
        pre.append(f"setpts=PTS/{speed}")
        pre.append(f"minterpolate=fps={FPS}:mi_mode=blend")
    zx = f"({z0}+({z1}-{z0})*t/{dur})"
    ow, oh = size
    vf = pre + [
        f"fps={FPS}",
        f"scale=w='2*trunc({W/2}*{zx})':h='2*trunc({H/2}*{zx})':eval=frame:flags=lanczos",
        f"crop={ow}:{oh}:x='(iw-{ow})*{cx}':y='(ih-{oh})*{cy}'",
        "setsar=1",
        G[grade],
    ]
    if fin:
        col, d = fin
        vf.append(f"fade=in:st=0:d={d}:color={col}")
    if fout:
        col, d = fout
        vf.append(f"fade=out:st={dur-d:.3f}:d={d}:color={col}")
    vf.append(f"trim=duration={dur}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", f"{src_dur:.3f}", "-i", SRC[src],
           "-vf", ",".join(vf), "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
           "-crf", "14", "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True)
    return out


def concat(clips, name):
    lst = os.path.join(TMP, name + ".txt")
    with open(lst, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    out = os.path.join(TMP, name + "_v.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", out], check=True)
    return out


# ---------- script timing (audio seconds, from waveform pauses) ----------
PHRASES = [
    (0.81, 2.50, "Pelik dengan perempuan zaman sekarang ni."),
    (3.23, 8.23, "Ramai yang fikir bahawa bukti cinta seorang lelaki mesti berkouple dan bercinta dengan mereka."),
    (8.78, 13.38, "Atau at least diajak dating bersama bahkan sampai tahap membiarkan lelaki menyentuhnya."),
    (13.85, 17.75, "Sebab perempuan ni rasa, ya kot inilah bukti cinta seorang lelaki."),
    (18.28, 22.76, "Padahal bukti cinta yang sebenar adalah apabila lelaki tu jaga ikhtilat,"),
    (23.14, 26.45, "kemudian datang ke rumah perempuan tu, lalu berjumpa orang tuanya,"),
    (26.65, 28.05, "kemudian beritahu,"),
    (28.45, 30.25, "“Pakcik, makcik, saya nak halalkan anak pakcik.”"),
    (30.60, 32.10, "Inilah bukti cinta."),
]


def syl(w):
    w = re.sub(r"[^a-z]", "", w.lower())
    n = len(re.findall(r"[aeiou]+", w.replace("ai", "a").replace("au", "a")))
    return max(1, n)


def word_times(p):
    s, e, text = PHRASES[p]
    words = text.split()
    weights = [syl(w) + 0.3 for w in words]
    tot = sum(weights)
    t, out = s, []
    for w, k in zip(words, weights):
        d = (e - s) * k / tot
        out.append((t, t + d, w))
        t += d
    return out


def ts(t):
    t = max(0.0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); sec = t % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def ass_header(styles):
    return ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n" + "\n".join(styles) +
            "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def ev(st, en, style, text, layer=0):
    return f"Dialogue: {layer},{ts(st)},{ts(en)},{style},,0,0,0,,{text}\n"


# ================= VIDEO A : kinetic captions =================
YEL, RED, WHT = "&H0000D4FF&", "&H004D4DFF&", "&H00FFFFFF&"
CHUNKS_A = [
    ["PELIK DENGAN", "PEREMPUAN", "ZAMAN SEKARANG NI"],
    ["RAMAI YANG FIKIR", "BAHAWA", "BUKTI CINTA", "SEORANG LELAKI", "MESTI BERKOUPLE", "DAN BERCINTA", "DENGAN MEREKA"],
    ["ATAU AT LEAST", "DIAJAK DATING", "BERSAMA", "BAHKAN SAMPAI TAHAP", "MEMBIARKAN LELAKI", "MENYENTUHNYA"],
    ["SEBAB PEREMPUAN", "NI RASA", "YA KOT", "INILAH BUKTI CINTA", "SEORANG LELAKI"],
    ["PADAHAL", "BUKTI CINTA", "YANG SEBENAR", "ADALAH APABILA", "LELAKI TU", "JAGA IKHTILAT"],
    ["KEMUDIAN DATANG", "KE RUMAH", "PEREMPUAN TU", "LALU BERJUMPA", "ORANG TUANYA"],
    ["KEMUDIAN BERITAHU"],
    ["“Pakcik, makcik…", "saya nak halalkan", "anak pakcik.”"],
    ["INILAH", "BUKTI CINTA."],
]
KEY = {  # phrase index -> {word: colour}
    1: {"BERKOUPLE": RED, "BERCINTA": RED},
    2: {"DATING": RED, "MENYENTUHNYA": RED},
    4: {"BUKTI": YEL, "CINTA": YEL, "IKHTILAT": YEL},
    5: {"ORANG": YEL, "TUANYA": YEL},
    7: {"halalkan": YEL},
    8: {"BUKTI": YEL, "CINTA.": YEL},
}
POP = r"\fscx72\fscy72\t(0,90,\fscx108\fscy108)\t(90,170,\fscx100\fscy100)"


def chunk_events(p, chunks, style, pos, extra=""):
    wt = word_times(p)
    out, i, spans = [], 0, []
    for c in chunks:
        n = len(c.split())
        spans.append((wt[i][0], c))
        i += n
    nxt = PHRASES[p + 1][0] if p + 1 < len(PHRASES) else TOTAL
    end_phrase = min(PHRASES[p][1] + 0.35, nxt) if nxt - PHRASES[p][1] > 0.7 else nxt
    for k, (st, c) in enumerate(spans):
        en = spans[k + 1][0] if k + 1 < len(spans) else end_phrase
        cols = KEY.get(p, {})
        txt = " ".join((f"{{\\c{cols[w]}}}{w}{{\\c{WHT}}}" if w in cols else w) for w in c.split())
        out.append(ev(st, en, style, f"{{\\pos({pos[0]},{pos[1]}){POP}{extra}}}{txt}"))
    return out


def build_a():
    clips = [
        shot("a1", "toc", 6.8, 3.23, 1.55, 1.68, 0.08, 0.36, grade="punch"),
        shot("a2", "page", 4.6, 5.55, 1.08, 1.22, 0.5, 0.45, grade="desat"),
        shot("a3", "toc", 0.0, 5.07, 1.10, 1.25, 0.3, 0.4, grade="desat"),
        shot("a4", "toc", 11.0, 4.43, 1.10, 1.22, 0.3, 0.5, grade="desat"),
        shot("a5", "quote", 0.0, 4.86, 1.00, 1.12, 0.5, 0.45, grade="warm", fin=("white", 0.3)),
        shot("a6", "page", 0.0, 5.31, 1.22, 1.38, 0.45, 0.62, speed=0.75, grade="warm"),
        shot("a7", "cover", 0.0, 2.15, 1.05, 1.15, 0.5, 0.5, speed=0.5, grade="soft", fin=("black", 0.25)),
        shot("a8", "page", 12.6, 1.80, 1.00, 1.10, 0.5, 0.4, grade="warm", fin=("white", 0.2)),
        shot("a9", "cover", 0.9, 7.60, 1.00, 1.14, 0.5, 0.5, grade="punch", fout=("black", 0.4)),
    ]
    v = concat(clips, "A")

    styles = [
        "Style: Cap,Montserrat Black,138,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1",
        "Style: Whisper,Cormorant Garamond Medium,132,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,1,0,0,100,100,0,0,1,3,2,5,60,60,0,1",
        "Style: Hook,Montserrat Black,94,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,3,18,0,5,60,60,0,1",
        "Style: Label,Montserrat SemiBold,56,&H00111111,&H00111111,&H0000D4FF,&H0000D4FF,0,0,0,0,100,100,0,0,3,16,0,5,60,60,0,1",
        "Style: CTA,Montserrat Black,104,&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,0,0,0,0,100,100,0,0,3,26,0,5,60,60,0,1",
        "Style: Big,Montserrat Black,190,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,8,4,5,60,60,0,1",
    ]
    e = []
    # hook (top) for first 3.2s
    e.append(ev(0.0, 3.2, "Hook", r"{\pos(540,430)\fad(0,150)}BUKTI CINTA LELAKI\N= AJAK {\c&H0000D4FF&}COUPLE{\c&H00FFFFFF&}?"))
    # chapter labels
    e.append(ev(3.4, 8.7, "Label", r"{\pos(540,380)\fad(200,200)}BAB 2.7 · KENAPA COUPLE HARAM?"))
    e.append(ev(23.2, 28.4, "Label", r"{\pos(540,380)\fad(200,200)}BAB 2.8 · CARA BERKAHWIN TANPA COUPLE"))
    for p, chunks in enumerate(CHUNKS_A):
        if p == 7:
            e += chunk_events(p, chunks, "Whisper", (540, 1130), r"\fad(120,0)\blur1")
        elif p == 8:
            e += chunk_events(p, chunks, "Big", (540, 1100))
        else:
            e += chunk_events(p, chunks, "Cap", (540, 1180))
    # CTA
    e.append(ev(32.6, 36.0, "CTA", r"{\pos(540,1230)\fad(150,150)" + POP + r"}NAK TAHU CARA\N{\c&H0000D4FF&}KAHWIN TANPA COUPLE{\c&H00FFFFFF&}?"))
    e.append(ev(36.0, 40.0, "CTA", r"{\pos(540,1230)\fad(150,300)" + POP + r"}DAPATKAN BUKU INI\N{\c&H0000D4FF&}LINK DI BIO"))
    ass = os.path.join(TMP, "A.ass")
    with open(ass, "w") as f:
        f.write(ass_header(styles) + "".join(e))

    out = os.path.join(OUT, "A_Kinetic_Bukti_Cinta.mp4")
    af = "loudnorm=I=-12.5:TP=-1.5:LRA=9,apad,atrim=0:40,afade=t=out:st=39.3:d=0.7"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", v, "-i", AUDIO,
                    "-filter_complex", f"[0:v]ass={ass}:fontsdir={FONTS}[v];[1:a]{af}[a]",
                    "-map", "[v]", "-map", "[a]", "-t", "40", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", "30",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out], check=True)
    return out


# ================= VIDEO B : minimal cinematic =================
O = 3.2  # main voice-over offset in B (cold open before it)
LINES_B = [
    [None],
    ["Ramai yang fikir bahawa bukti cinta seorang lelaki", "mesti berkouple dan bercinta dengan mereka."],
    ["Atau at least diajak dating bersama,", "bahkan sampai tahap membiarkan lelaki menyentuhnya."],
    ["Sebab perempuan ni rasa,", "ya kot inilah bukti cinta seorang lelaki."],
    ["Padahal bukti cinta yang sebenar", "adalah apabila lelaki tu jaga ikhtilat,"],
    ["kemudian datang ke rumah perempuan tu,", "lalu berjumpa orang tuanya,"],
    [None],
    [None],
    [None],
]


def build_b():
    k = 0.25
    sq = (1080, 1080)
    PY = 220  # picture top; picture 170..1250, subtitle band below (inside TikTok safe zone)
    clips = [
        shot("b0", "quote", 3.0, 3.20, 1.25, 1.32, 0.5, 0.42, grade="dark", fin=("black", 0.8), fout=("black", 0.3), size=sq),
        shot("b1", "cover", 4.5, 3.23, 1.00, 1.06, 0.5, 0.45, grade="film", fin=("black", k), fout=("black", k), size=sq),
        shot("b2", "toc", 5.5, 5.55, 1.15, 1.25, 0.05, 0.5, grade="film", fin=("black", k), fout=("black", k), size=sq),
        shot("b3", "page", 5.0, 5.07, 1.30, 1.40, 0.75, 0.55, grade="film", fin=("black", k), fout=("black", k), size=sq),
        shot("b4", "toc", 12.5, 4.43, 1.10, 1.18, 0.2, 0.35, grade="film", fin=("black", k), fout=("black", k), size=sq),
        shot("b5", "page", 0.0, 4.86, 1.00, 1.08, 0.5, 0.5, grade="filmwarm", fin=("black", 0.5), fout=("black", k), size=sq),
        shot("b6", "cover", 0.3, 5.31, 1.12, 1.02, 0.5, 0.45, speed=0.75, grade="filmwarm", fin=("black", k), fout=("black", k), size=sq),
        shot("b7", "page", 9.5, 2.15, 1.10, 1.18, 0.5, 0.5, speed=0.6, grade="filmwarm", fin=("black", k), fout=("black", 0.15), size=sq),
        shot("b8", "page", 13.6, 1.80, 1.00, 1.06, 0.5, 0.35, grade="filmwarm", fin=("black", 0.15), fout=("black", k), size=sq),
        shot("b9", "quote", 0.0, 4.40, 1.20, 1.28, 0.5, 0.42, grade="darker", fin=("black", 0.5), fout=("black", 0.6), size=sq),
    ]
    v = concat(clips, "B")

    styles = [
        "Style: Sub,Cormorant Garamond SemiBold,88,&H00F2F2F2,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0.5,0,1,0,0,5,70,70,0,1",
        "Style: Ital,Cormorant Garamond Medium,98,&H00F2F2F2,&H00FFFFFF,&H00000000,&H96000000,0,1,0,0,100,100,0,0,1,0,2,5,90,90,0,1",
        "Style: Spaced,Inter Light,46,&H00E6E6E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,14,0,1,0,0,5,60,60,0,1",
        "Style: Title,Cormorant Garamond SemiBold,124,&H00F2F2F2,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,0,2,5,80,80,0,1",
    ]
    BAND = 1395
    e = []
    F = r"\fad(220,220)"
    P = r"{\pos(540,%d)" % BAND + F + "}"
    # cold open: whisper teaser over dark quote page, then title in band
    e.append(ev(0.45, 2.55, "Ital", r"{\pos(540,760)\fad(350,250)}" + "“Pakcik, makcik,\\Nsaya nak halalkan\\Nanak pakcik.”"))
    e.append(ev(2.6, O + 0.75, "Spaced", r"{\pos(540,1355)\fad(400,300)}BUKTI CINTA"))
    e.append(ev(2.6, O + 0.75, "Ital", r"{\pos(540,1440)\fad(400,300)\fs74}seorang lelaki"))
    e.append(ev(O + 0.81, O + 2.85, "Sub", P + "Pelik dengan perempuan\\Nzaman sekarang ni."))
    for p in range(1, 6):
        lines = LINES_B[p]
        wt = word_times(p)
        n1 = len(lines[0].split())
        s1, s2 = wt[0][0], wt[n1][0]
        nxt = PHRASES[p + 1][0]
        end = min(PHRASES[p][1] + 0.3, nxt)
        e.append(ev(O + s1 - 0.05, O + s2, "Sub", P + lines[0]))
        e.append(ev(O + s2, O + end, "Sub", P + lines[1]))
    e.append(ev(O + 26.6, O + 28.3, "Sub", P + "kemudian beritahu,"))
    e.append(ev(O + 28.4, O + 30.45, "Ital", r"{\pos(540,%d)\fad(300,250)}" % BAND + "“Pakcik, makcik,\\Nsaya nak halalkan anak pakcik.”"))
    e.append(ev(O + 30.55, O + 32.4, "Title", r"{\pos(540,%d)\fad(300,300)}Inilah bukti cinta." % BAND))
    # outro over dark quote page + link in band
    e.append(ev(36.0, 40.0, "Title", r"{\pos(540,700)\fad(500,500)}Ajari Aku\NTinggalkan Maksiat"))
    e.append(ev(36.4, 40.0, "Spaced", r"{\pos(540,935)\fad(500,500)}SHUKERY AZIZAN"))
    e.append(ev(37.0, 40.0, "Spaced", r"{\pos(540,%d)\fad(500,500)\fs42\c&H00B0E0F0&}DAPATKAN DI LINK BIO" % BAND))
    ass = os.path.join(TMP, "B.ass")
    with open(ass, "w") as f:
        f.write(ass_header(styles) + "".join(e))

    out = os.path.join(OUT, "B_Cinematic_Bukti_Cinta.mp4")
    crf = "21"
    vf = (f"[0:v]pad=1080:1920:0:{PY}:color=black,"
          f"drawbox=x=0:y={PY}:w=iw:h=1080:color=0x2a2a2a@0.9:t=1,"
          f"ass={ass}:fontsdir={FONTS}[v]")
    # cold-open teaser (whisper) + full VO offset by O
    af = (f"[1:a]atrim=28.42:30.30,asetpts=PTS-STARTPTS,afade=t=in:d=0.05,afade=t=out:st=1.7:d=0.18,"
          f"aecho=0.8:0.6:120:0.25,adelay=450|450[t];"
          f"[2:a]adelay={int(O*1000)}|{int(O*1000)}[m];"
          f"[t][m]amix=inputs=2:normalize=0,loudnorm=I=-12.5:TP=-1.5:LRA=9,apad,atrim=0:40,"
          f"afade=t=out:st=39.2:d=0.8[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", v, "-i", AUDIO, "-i", AUDIO,
                    "-filter_complex", vf + ";" + af,
                    "-map", "[v]", "-map", "[a]", "-t", "40", "-c:v", "libx264", "-preset", "slow",
                    "-crf", crf, "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", "30",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out], check=True)
    return out


if __name__ == "__main__":
    which = sys.argv[1:] or ["A", "B"]
    if "A" in which:
        print(build_a())
    if "B" in which:
        print(build_b())
