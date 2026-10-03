"""Whisper-base (ONNX, q8) greedy transcription with segment + DTW word timestamps."""
import json, subprocess, sys
import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor, WhisperTokenizer

M = "package/models/Xenova/whisper-base"
src = sys.argv[1]
chunks = [tuple(map(float, c.split(":"))) for c in sys.argv[2].split(",")]
lang = sys.argv[3] if len(sys.argv) > 3 else "<|ms|>"
prompt_text = sys.argv[4] if len(sys.argv) > 4 else ""

fe = WhisperFeatureExtractor.from_pretrained(M)
tok = WhisperTokenizer.from_pretrained(M)
gc = json.load(open(f"{M}/generation_config.json"))
enc = ort.InferenceSession(f"{M}/onnx/encoder_model_quantized.onnx")
dec = ort.InferenceSession(f"{M}/onnx/decoder_model_merged_quantized.onnx")
out_names = [o.name for o in dec.get_outputs()]
heads = gc["alignment_heads"]
SOT, EOT, TRANS, NOTS = 50258, 50257, 50359, 50363
TS0 = 50364
LANG = gc["lang_to_id"][lang]
suppress = set(gc["suppress_tokens"])

pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                     capture_output=True, check=True).stdout
audio = np.frombuffer(pcm, dtype=np.float32)


def run_chunk(a0, a1):
    seg = audio[int(a0 * 16000):int(a1 * 16000)]
    feats = fe(seg, sampling_rate=16000, return_tensors="np").input_features.astype(np.float32)
    eo = enc.run(None, {"input_features": feats})
    hidden = eo[0]
    prev = []
    if prompt_text:
        prev = [50361] + tok.encode(" " + prompt_text.strip(), add_special_tokens=False)[-200:]
    ids = prev + [SOT, LANG, TRANS]
    n_prompt = len(ids)
    past = {}
    for l in range(6):
        for k in ("decoder", "encoder"):
            for kv in ("key", "value"):
                n = 0 if k == "decoder" else 1500
                past[f"past_key_values.{l}.{k}.{kv}"] = np.zeros((1, 8, 0 if k == "decoder" else 0, 64), np.float32)
    gen, attn = [], []
    use_cache = False
    cur = np.array([ids], np.int64)
    max_ts = int((a1 - a0) / 0.02)
    for step in range(220):
        feed = {"input_ids": cur, "encoder_hidden_states": hidden, "use_cache_branch": np.array([use_cache])}
        feed.update(past)
        res = dict(zip(out_names, dec.run(None, feed)))
        logits = res["logits"][0, -1].astype(np.float64)
        # cross attentions for alignment heads (last query position)
        ca = []
        for (l, h) in heads:
            ca.append(res[f"cross_attentions.{l}"][0, h, -1])
        if step == 0:
            pass
        attn.append(np.stack(ca))
        for l in range(6):
            past[f"past_key_values.{l}.decoder.key"] = res[f"present.{l}.decoder.key"]
            past[f"past_key_values.{l}.decoder.value"] = res[f"present.{l}.decoder.value"]
            if not use_cache:
                past[f"past_key_values.{l}.encoder.key"] = res[f"present.{l}.encoder.key"]
                past[f"past_key_values.{l}.encoder.value"] = res[f"present.{l}.encoder.value"]
        use_cache = True
        # --- logit rules ---
        for t in suppress:
            logits[t] = -np.inf
        logits[NOTS] = -np.inf
        logits[SOT:TS0] = -np.inf  # other specials
        logits[TS0 + max_ts + 1:] = -np.inf
        if step == 0:
            logits[:TS0] = -np.inf
            logits[TS0 + 50:] = -np.inf
        else:
            last_ts = gen[-1] >= TS0
            pen_ts = len(gen) < 2 or gen[-2] >= TS0
            if last_ts:
                if pen_ts:
                    logits[TS0:] = -np.inf
                else:
                    logits[:EOT] = -np.inf
            tss = [t for t in gen if t >= TS0]
            if tss:
                lo = tss[-1] + (0 if last_ts and not pen_ts else 1)
                logits[TS0:lo] = -np.inf
            lp = logits - np.logaddexp.reduce(logits[np.isfinite(logits)])
            ts_lp = np.logaddexp.reduce(lp[TS0:][np.isfinite(lp[TS0:])]) if np.isfinite(lp[TS0:]).any() else -np.inf
            if ts_lp > lp[:TS0].max():
                logits[:TS0] = -np.inf
        nxt = int(np.argmax(logits))
        gen.append(nxt)
        if nxt == EOT:
            break
        cur = np.array([[nxt]], np.int64)
    return gen, np.array(attn), n_prompt


def dtw(cost):
    N, M_ = cost.shape
    D = np.full((N + 1, M_ + 1), np.inf); D[0, 0] = 0
    T = np.zeros((N + 1, M_ + 1), np.int8)
    for i in range(1, N + 1):
        for j in range(1, M_ + 1):
            c = [D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]]
            k = int(np.argmin(c)); D[i, j] = cost[i - 1, j - 1] + c[k]; T[i, j] = k
    i, j, path = N, M_, []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        k = T[i, j]
        if k == 0: i, j = i - 1, j - 1
        elif k == 1: i -= 1
        else: j -= 1
    return path[::-1]


words_out, segs_out = [], []
for a0, a1 in chunks:
    gen, attn, _ = run_chunk(a0, a1)
    # attn[k] is attention while *predicting* gen[k]; token gen[k] position aligns to attn[k+1]
    # segments
    cur_start, cur_toks = None, []
    for t in gen:
        if t >= TS0:
            if cur_start is None:
                cur_start = (t - TS0) * 0.02
            else:
                segs_out.append((a0 + cur_start, a0 + (t - TS0) * 0.02, tok.decode(cur_toks).strip()))
                cur_start, cur_toks = None, []
        elif t != EOT:
            cur_toks.append(t)
    # DTW word alignment on text tokens
    frames = int(round((a1 - a0) / 0.02))
    W_ = attn[:, :, :frames]  # steps x heads x frames
    W_ = W_ / (W_.std(axis=0, keepdims=True) + 1e-6) if False else W_
    W_ = (W_ - W_.mean(axis=2, keepdims=True)) / (W_.std(axis=2, keepdims=True) + 1e-6)
    from scipy.ndimage import median_filter
    W_ = median_filter(W_, size=(1, 1, 7))
    mat = W_.mean(axis=1)  # steps x frames
    text_idx = [k for k, t in enumerate(gen) if t < EOT]
    if not text_idx:
        continue
    rows = np.array([mat[min(k + 1, len(mat) - 1)] for k in text_idx])
    path = dtw(-rows)
    tok_start = {}
    for i, j in path:
        tok_start.setdefault(i, j)
    tok_end = {}
    for i, j in path:
        tok_end[i] = j
    # group to words
    cur_w, ws, we = "", None, None
    for n, k in enumerate(text_idx):
        piece = tok.decode([gen[k]])
        if piece.startswith(" ") and cur_w:
            words_out.append((a0 + ws * 0.02, a0 + we * 0.02, cur_w.strip()))
            cur_w, ws = "", None
        if ws is None:
            ws = tok_start[n]
        we = tok_end[n]
        cur_w += piece
    if cur_w:
        words_out.append((a0 + ws * 0.02, a0 + we * 0.02, cur_w.strip()))

json.dump({"segments": segs_out, "words": words_out}, open(sys.argv[5] if len(sys.argv) > 5 else "out.json", "w"),
          ensure_ascii=False, indent=1)
for s in segs_out:
    print(f"[{s[0]:6.2f}-{s[1]:6.2f}] {s[2]}")
