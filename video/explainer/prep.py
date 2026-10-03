"""Prep for the presenter explainer: EDL frames, person masks, book cut-out, VAD word timing."""
import json, os, re, subprocess
import numpy as np
import cv2
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
U = "/root/.claude/uploads/bd1e6249-bf6e-5c96-a56f-a87bb5527365"
TALK = f"{U}/97ffe4d7-IMG_0814.MOV"
BOOK = "/tmp/claude-0/-home-user-Shukery-Azizan/bd1e6249-bf6e-5c96-a56f-a87bb5527365/images/1.webp"
MODEL = os.path.join(HERE, "..", "models", "selfie_multiclass_256x256.tflite")
W = os.path.join(HERE, "work")
FPS = 30

# (src_in, src_out, corrected words; "|" ends a subtitle phrase)
PIECES = [
    (4.04, 6.30, "Kalau tak couple, macam mana nak kahwin?|"),
    (8.10, 13.90, "Tahu tak sebenarnya,| Nabi ﷺ dengan Khadijah pun| tak pernah couple.|"),
    (16.00, 23.42, "Sebab kita dah terbiasa| dengan pengaruh budaya Barat.| Orang Barat ni, atau orang kafir| kebanyakannya nak couple,"),
    (24.18, 26.05, "bahkan nak berzina dulu| baru nak kahwin.|"),
    (26.08, 27.10, "Sebab tu, bila"),
    (27.45, 28.30, "perempuan…|"),
    (30.90, 39.10, "ada lelaki nak meminang dia,| nak kahwin,| dia rasa appreciated,| sebab akhirnya ada orang sudi| nak bersama sehidup semati| dengan dia.|"),
    (39.45, 40.15, "Jadi"),
    (41.10, 51.88, "dalam buku Ajari Aku Tinggalkan Maksiat,| saya ada gariskan| step one by one| macam mana nak kahwin tanpa couple,| ikut sunnah Nabi ﷺ.|"),
    (66.22, 70.30, "Dan moga-moga Allah kurniakan| jodoh yang soleh dan solehah.|"),
]
OUTRO_SRC = 0.9  # extra source seconds after last piece (presenter fades during outro)
OUTRO = 2.7       # outro length (s)


def syl(w):
    w = re.sub(r"[^a-z]", "", w.lower())
    if not w:
        return 1
    return max(1, len(re.findall(r"[aeiouy]+", w)))


def main():
    os.makedirs(f"{W}/src", exist_ok=True)
    os.makedirs(f"{W}/mask", exist_ok=True)
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", TALK, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768

    # ---------- timeline ----------
    frames = []  # out frame -> src time
    words = []   # (out_t0, out_t1, word, phrase_id)
    t_out = 0.0
    pid = 0
    for (a, b, text) in PIECES:
        n = int(round((b - a) * FPS))
        frames += [a + k / FPS for k in range(n)]
        # VAD inside piece (20 ms hops)
        hop = 320
        i0, i1 = int(a * 16000) // hop, int(b * 16000) // hop
        e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2)) for i in range(i0, i1)])
        db = 20 * np.log10(e + 1e-9)
        act = (db > -42).astype(float)
        act = ndimage.binary_closing(act, np.ones(5)).astype(float)
        cum = np.cumsum(act); tot = cum[-1]
        toks = []
        parts = text.split("|")
        for pi, ph in enumerate(parts):
            ws = ph.split()
            for k, w in enumerate(ws):
                toks.append((w, k == len(ws) - 1 and pi < len(parts) - 1))
        weights = [syl(w) + 0.4 for w, _ in toks]
        tw = sum(weights); acc = 0
        for (w, end_ph), wt in zip(toks, weights):
            f0 = acc / tw * tot; acc += wt; f1 = acc / tw * tot
            j0 = int(np.searchsorted(cum, max(f0, 0.5))); j1 = int(np.searchsorted(cum, f1))
            words.append((round(t_out + j0 * 0.02, 3), round(t_out + j1 * 0.02 + 0.02, 3), w, pid))
            if end_ph:
                pid += 1
        t_out += n / FPS
    voice_end = t_out
    last = PIECES[-1][1]
    n = int(round(OUTRO_SRC * FPS))
    frames += [last + k / FPS for k in range(n)]
    total_frames = int(round((voice_end + OUTRO) * FPS))
    while len(frames) < total_frames:
        frames.append(frames[-1])
    json.dump({"frames": frames, "words": words, "voice_end": voice_end, "pieces": PIECES,
               "total": total_frames / FPS}, open(f"{W}/timeline.json", "w"), ensure_ascii=False, indent=0)
    print("voice_end", voice_end, "total", total_frames / FPS, "frames", len(frames))

    # ---------- extract source frames ----------
    cap = cv2.VideoCapture(TALK)
    src_n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    need = sorted(set(min(src_n - 1, int(round(t * FPS))) for t in frames))
    from ai_edge_litert.interpreter import Interpreter
    it = Interpreter(model_path=MODEL); it.allocate_tensors()
    ii, oo = it.get_input_details()[0], it.get_output_details()[0]
    k, cur = 0, 0
    prev_a = None
    needset = set(need)
    while k <= need[-1]:
        ok, fr = cap.read()
        if not ok:
            break
        if k in needset:
            cv2.imwrite(f"{W}/src/{k:05d}.jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 96])
            rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
            inp = cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
            it.set_tensor(ii["index"], inp[None]); it.invoke()
            y = it.get_tensor(oo["index"])[0]
            ex = np.exp(y - y.max(-1, keepdims=True)); p = ex / ex.sum(-1, keepdims=True)
            a = 1 - p[..., 0]
            a = cv2.resize(a, (fr.shape[1], fr.shape[0]), interpolation=cv2.INTER_CUBIC)
            if prev_a is not None and k - prev_k == 1:
                a = 0.6 * a + 0.4 * prev_a
            prev_a, prev_k = a, k
            m = np.clip((a - 0.5) * 3.0 + 0.5, 0, 1)
            m = cv2.GaussianBlur(m, (0, 0), 1.6)
            cv2.imwrite(f"{W}/mask/{k:05d}.png", (m * 255).astype(np.uint8))
        k += 1
    print("frames extracted", len(need))

    # ---------- book cut-out ----------
    im = np.array(Image.open(BOOK).convert("RGB")).astype(np.float32)
    white = (im.min(-1) > 238)
    lab, _ = ndimage.label(white)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    alpha = 1 - bg.astype(np.float32)
    alpha = ndimage.binary_erosion(alpha > 0.5, iterations=2).astype(np.float32)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)
    ys, xs = np.where(alpha > 0.05)
    crop = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    rgba = np.dstack([im, alpha * 255]).astype(np.uint8)
    Image.fromarray(rgba).crop(crop).save(f"{W}/book.png")
    print("book", crop)

    # blurred wall plate for the mixed background
    fr = cv2.imread(f"{W}/src/{need[len(need)//2]:05d}.jpg")
    plate = cv2.resize(fr, (1080, 1920))
    plate = cv2.GaussianBlur(plate, (0, 0), 45)
    cv2.imwrite(f"{W}/plate.jpg", plate)


if __name__ == "__main__":
    main()
