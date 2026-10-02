#!/usr/bin/env python
"""Split-screen ad compositor (9:16): brand header, grey-box card on top, final-render card below.

Replicates the layout measured in compose/layout_measurements.json: cream background with
slowly morphing thin wave lines, an orange rounded-square logo + header text that animate in
during the first second, two rounded 16:9 cards with soft shadows (both videos cut in perfect
sync, centre-cropped to fill the card), dark pill badges (top-left of each card) and thin
progress lines that grow along the bottom edge of each card over the clip duration.

Everything except the two video streams is drawn with Pillow/numpy (4x supersampled), frames
are piped to ffmpeg for the final H.264/AAC encode.

Examples (run from the project dir):
  python compose/compose_ad.py --top out/previs.mp4 --bottom out/final_ai.mp4 --out out/ad.mp4
  python compose/compose_ad.py --top a.mp4 --bottom b.mp4 --out ad_1080.mp4 --scale 1.5 --audio music.wav \\
         --header "Opus 5.5" --badge-top Blender --badge-bottom "Kleo AI" --icon-bottom kleo
  python compose/compose_ad.py --top a.mp4 --bottom b.mp4 --out x.mp4 --png-at 0.3,2,6.5,12 --png-dir /tmp/frames
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 4  # supersampling factor for everything drawn by Pillow


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------
def ease_out_cubic(p):
    p = min(max(p, 0.0), 1.0)
    return 1.0 - (1.0 - p) ** 3


def pingpong(t, period):
    m = t % (2.0 * period)
    return m if m <= period else 2.0 * period - m


def catmull_rom(p0, p1, p2, p3, u):
    return 0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def rgb(c):
    return np.array(c[:3], dtype=np.float32)


def find_font(name_candidates):
    for p in name_candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("no usable font among: %s" % name_candidates)


def ss_font(path, size_px):
    return ImageFont.truetype(path, max(1, int(round(size_px * SS))))


def rounded_mask(w, h, radius, supersample=SS):
    """Anti-aliased rounded-rectangle coverage mask, float32 (h, w) in [0, 1]."""
    im = Image.new("L", (w * supersample, h * supersample), 0)
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w * supersample - 1, h * supersample - 1],
                                         radius=radius * supersample, fill=255)
    return np.asarray(im.reduce(supersample), dtype=np.float32) / 255.0


def gaussian_blur_np(a, sigma):
    """Exact separable Gaussian blur of a float32 (h, w) array (zero padding)."""
    r = int(math.ceil(3.0 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k = (k / k.sum()).astype(np.float32)
    out = a.astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(out, pad)
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, w in enumerate(k):
            acc += w * (p[i:i + n, :] if axis == 0 else p[:, i:i + n])
        out = acc
    return out


def blend(dst, src_rgb, alpha):
    """dst (h,w,3 float32) <- src over dst, alpha (h,w) float32 (src_rgb scalar triple or (h,w,3))."""
    a = alpha[..., None]
    dst *= (1.0 - a)
    dst += np.asarray(src_rgb, dtype=np.float32) * a


def tracked_layout(font, text, tracking_px):
    """x offsets (SS pixels) of each glyph with pair kerning + tracking, and total advance width."""
    xs, x = [], 0.0
    for i, ch in enumerate(text):
        xs.append(x)
        adv = font.getlength(ch)
        if i + 1 < len(text):
            adv += font.getlength(text[i:i + 2]) - font.getlength(ch) - font.getlength(text[i + 1])
            adv += tracking_px * SS
        x += adv
    return xs, x


# --------------------------------------------------------------------------------------
# ffprobe / decoding
# --------------------------------------------------------------------------------------
def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,duration,nb_frames,color_space,color_range,avg_frame_rate:format=duration",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    st = j["streams"][0]
    dur = st.get("duration")
    if dur in (None, "N/A"):
        dur = j.get("format", {}).get("duration")
    return {
        "w": int(st["width"]), "h": int(st["height"]), "duration": float(dur),
        "space": st.get("color_space", "unknown"), "range": st.get("color_range", "unknown"),
    }


def pick_matrix(info, forced):
    if forced != "auto":
        return forced
    sp = info["space"]
    if sp in ("bt709",):
        return "bt709"
    if sp in ("smpte170m", "bt470bg"):
        return "bt601"
    if sp == "bt2020nc":
        return "bt2020"
    # untagged: HD material is bt709 by convention (ffmpeg would otherwise assume bt601)
    return "bt709" if (info["h"] >= 720 or info["w"] >= 1280) else "bt601"


def open_decoder(path, w, h, fps, matrix, info, quiet_stderr=False):
    rng = "pc" if info["range"] == "pc" else "tv"
    vf = ("fps=%s,scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos:in_color_matrix=%s:in_range=%s,"
          "crop=%d:%d,format=rgb24") % (fps, w, h, matrix, rng, w, h)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL if quiet_stderr else None)


def read_frame(proc, w, h, last):
    n = w * h * 3
    buf = proc.stdout.read(n)
    if len(buf) < n:  # stream ended early (rounding): hold the last frame
        return last
    return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)


# --------------------------------------------------------------------------------------
# the compositor
# --------------------------------------------------------------------------------------
class Compositor:
    def __init__(self, layout, waves, scale, header, badge_top, badge_bottom, icon_bottom="seedance"):
        self.L = layout
        self.s = float(scale)
        s = self.s
        self.W = int(round(layout["canvas"]["w"] * s))
        self.H = int(round(layout["canvas"]["h"] * s))
        self.fps = layout["canvas"]["fps"]
        self.font_bold = find_font([os.path.join(HERE, "fonts", "HankenGrotesk_700Bold.ttf"),
                                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"])
        self._build_background()
        self._build_cards()
        self._build_waves(waves)
        self._build_header(header)
        self.badges = [self._build_badge(badge_top, "blender", self.card_top),
                       self._build_badge(badge_bottom, icon_bottom, self.card_bottom)]
        self.prog = self.L["progress"]

    # ------------------------------------------------------------------ background / shadow
    def _build_background(self):
        g = self.L["background"]["grid"]
        H, W, s = self.H, self.W, self.s
        xn = np.array(g["x_nodes"], dtype=np.float64) * s
        yn = np.array(g["y_nodes"], dtype=np.float64) * s
        nodes = np.array(g["rgb"], dtype=np.float64)            # (rows, cols, 3)
        xq = np.arange(W) + 0.5
        yq = np.arange(H) + 0.5
        # bilinear interpolation (clamped beyond the outer nodes), separable
        rows = np.stack([np.stack([np.interp(xq, xn, nodes[r, :, ch]) for ch in range(3)], axis=-1)
                         for r in range(nodes.shape[0])])         # (rows, W, 3)
        bg = np.empty((H, W, 3), dtype=np.float32)
        for ch in range(3):
            for x0 in range(0, W, 256):                          # interp each column block against y nodes
                blk = rows[:, x0:x0 + 256, ch]                   # (rows, wblk)
                f = np.clip(np.interp(yq, yn, np.arange(len(yn))), 0, len(yn) - 1)
                i0 = np.minimum(f.astype(int), len(yn) - 2)
                u = (f - i0)[:, None]
                bg[:, x0:x0 + 256, ch] = blk[i0] * (1 - u) + blk[i0 + 1] * u
        self.bg = bg

    def _card_rect(self, key):
        c = self.L["cards"][key]
        s = self.s
        return {"x": int(round(c["x"] * s)), "y": int(round(c["y"] * s)),
                "w": int(round(c["w"] * s)), "h": int(round(c["h"] * s)), "r": c["radius"] * s}

    def _build_cards(self):
        s = self.s
        self.card_top = self._card_rect("top")
        self.card_bottom = self._card_rect("bottom")
        sh = self.L["cards"]["shadow"]
        shade = np.ones((self.H, self.W), dtype=np.float32)
        for card in (self.card_top, self.card_bottom):
            im = Image.new("L", (self.W * SS, self.H * SS), 0)
            ImageDraw.Draw(im).rounded_rectangle(
                [card["x"] * SS, (card["y"] + sh["offset_y"] * s) * SS, (card["x"] + card["w"]) * SS - 1,
                 (card["y"] + card["h"] + sh["offset_y"] * s) * SS - 1], radius=card["r"] * SS, fill=255)
            m = np.asarray(im.reduce(SS), dtype=np.float32) / 255.0
            a = gaussian_blur_np(m, sh["gaussian_sigma"] * s) * sh["alpha"]
            shade *= (1.0 - a)
            card["mask"] = rounded_mask(card["w"], card["h"], card["r"])
        self.shade = shade[..., None]

    # ------------------------------------------------------------------ waves
    def _build_waves(self, model):
        self.wave_model = model
        self.wave_styles = self.L["waves"]["styles"]
        self.key_times = model["key_times"]
        self.wave_curves = []
        for c in model["curves"]:
            self.wave_curves.append({
                "name": c["name"], "x": np.array(c["x"], dtype=np.float64),
                "Y": np.array(c["y"], dtype=np.float64)})

    def _wave_y(self, curve, t):
        kt = self.key_times
        T = kt[-1]
        u = pingpong(t, T)
        n = len(kt)
        f = min(max(u / (kt[1] - kt[0]), 0.0), n - 1.0)
        j = min(int(f), n - 2)
        v = f - j
        Y = curve["Y"]
        return catmull_rom(Y[max(j - 1, 0)], Y[j], Y[j + 1], Y[min(j + 2, n - 1)], v)

    def _draw_waves(self, img, t):
        s = self.s
        W, H = self.W, self.H
        for c in self.wave_curves:
            st = self.wave_styles[c["name"]]
            xs = c["x"]
            ys = self._wave_y(c, t)
            h = xs[1] - xs[0]
            ext = 28.0
            xa = max(xs[0] - ext, -4.0 / s) if xs[0] > 0 else -4.0 / s
            xb = min(xs[-1] + ext, 724.0) if xs[-1] < 719 - 1 else 724.0
            xq = np.arange(math.floor(xa), math.ceil(xb) + 1, 1.0)
            f = np.clip((xq - xs[0]) / h, 0, len(xs) - 1.000001)
            j = np.floor(f).astype(int)
            u = f - j
            p0 = ys[np.clip(j - 1, 0, None)]
            p1 = ys[j]
            p2 = ys[np.clip(j + 1, None, len(xs) - 1)]
            p3 = ys[np.clip(j + 2, None, len(xs) - 1)]
            yq = catmull_rom(p0, p1, p2, p3, u)
            # linear extrapolation beyond the measured ends
            sl_a = (ys[1] - ys[0]) / h
            sl_b = (ys[-1] - ys[-2]) / h
            yq = np.where(xq < xs[0], ys[0] + sl_a * (xq - xs[0]), yq)
            yq = np.where(xq > xs[-1], ys[-1] + sl_b * (xq - xs[-1]), yq)
            wpx = st["width"] * s
            y_lo = int(math.floor(yq.min() * s - wpx - 2))
            y_hi = int(math.ceil(yq.max() * s + wpx + 2))
            y_lo, y_hi = max(y_lo, 0), min(y_hi, H)
            x_lo = max(int(math.floor(xq.min() * s)) - 2, 0)
            x_hi = min(int(math.ceil(xq.max() * s)) + 2, W)
            if y_hi <= y_lo or x_hi <= x_lo:
                continue
            cv = Image.new("L", ((x_hi - x_lo) * SS, (y_hi - y_lo) * SS), 0)
            d = ImageDraw.Draw(cv)
            pts = [((x * s - x_lo) * SS, (y * s - y_lo) * SS) for x, y in zip(xq, yq)]
            d.line(pts, fill=255, width=max(1, int(round(wpx * SS))), joint="curve")
            cov = np.asarray(cv.reduce(SS), dtype=np.float32) / 255.0
            reg = img[y_lo:y_hi, x_lo:x_hi]
            blend(reg, rgb(st["rgb"]), cov)

    # ------------------------------------------------------------------ header (logo + text)
    LOGO_MARGIN = 8  # px of transparent margin around the logo tile (room for the intro rotation)

    def _logo_tile(self):
        lg = self.L["header"]["logo"]
        s = self.s
        m = self.LOGO_MARGIN
        lx, ly, lw, lh = lg["x"] * s, lg["y"] * s, lg["w"] * s, lg["h"] * s
        ix, iy = int(math.floor(lx)) - m, int(math.floor(ly)) - m           # integer tile origin on the canvas
        tw, th = int(math.ceil(lw)) + 2 * m + 1, int(math.ceil(lh)) + 2 * m + 1
        im = Image.new("RGBA", (tw * SS, th * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        bx0, by0 = (lx - ix) * SS, (ly - iy) * SS
        d.rounded_rectangle([bx0, by0, bx0 + lw * SS - 1, by0 + lh * SS - 1], radius=lg["radius"] * s * SS,
                            fill=tuple(lg["rgb"]) + (255,))
        # clean 8-ray starburst (own drawing): eight round-capped rays that merge into a hub
        cx, cy = bx0 + lw * SS / 2.0, by0 + lh * SS / 2.0
        r_out, wd = 22.0 * s * SS, 5.4 * s * SS
        for k in range(8):
            a = math.pi / 8 + k * math.pi / 4
            x2, y2 = cx + r_out * math.cos(a), cy + r_out * math.sin(a)
            d.line([(cx, cy), (x2, y2)], fill=(255, 255, 255, 255), width=int(round(wd)))
            d.ellipse([x2 - wd / 2, y2 - wd / 2, x2 + wd / 2, y2 + wd / 2], fill=(255, 255, 255, 255))
        d.ellipse([cx - wd * 0.6, cy - wd * 0.6, cx + wd * 0.6, cy + wd * 0.6], fill=(255, 255, 255, 255))
        self.logo_origin = (ix, iy)
        self.logo_center = (lx + lw / 2.0, ly + lh / 2.0)
        return im

    def _build_header(self, header_text):
        s = self.s
        hd = self.L["header"]
        self.header_text = header_text
        self.logo_tile = self._logo_tile()
        tx = hd["text"]
        self.words = []
        if header_text:
            font = ss_font(self.font_bold, tx["size_px"] * s)
            xs, total = tracked_layout(font, header_text, tx["tracking_em"] * tx["size_px"] * s)
            off_x, off_y = tx.get("render_offset_px", [0.0, 0.0])
            left = ((tx["bbox"]["centre_x"] + off_x) * s) * SS - total / 2.0
            baseline = (tx["bbox"]["baseline_y"] + off_y) * s * SS
            asc, desc = font.getmetrics()
            idx = 0
            for wi, word in enumerate(header_text.split(" ")):
                # find the word's characters in the full string
                start = header_text.index(word, idx)
                idx = start + len(word)
                x0 = left + xs[start]
                wx1 = left + (xs[idx - 1] + font.getlength(header_text[idx - 1]))
                pad = int(14 * s * SS)
                tw = int(wx1 - x0) + 2 * pad
                th = asc + desc + 2 * pad
                tile = Image.new("L", (tw, th), 0)
                d = ImageDraw.Draw(tile)
                for k in range(start, idx):
                    d.text((left + xs[k] - x0 + pad, asc + pad), header_text[k], font=font, fill=255, anchor="ls")
                # tile origin in SS canvas coordinates
                ox, oy = x0 - pad, baseline - asc - pad
                self.words.append({"tile": tile, "ox": ox, "oy": oy, "i": wi})
        # static (post-intro) header layer
        self.intro_end = self._intro_end_time()
        self._header_static = None

    def _word_timing(self, i):
        ia = self.L["intro_animation"]
        ws = ia["words"]
        w = ws[min(i, len(ws) - 1)]
        return w["t0_s"] + (i - min(i, len(ws) - 1)) * ia["word_stagger_s"], w["dur_s"]

    def _intro_end_time(self):
        e = max(self.L["intro_animation"]["logo"]["opacity_dur_s"], self.L["intro_animation"]["logo"]["rotation_deg"]["dur_s"],
                self.L["intro_animation"]["logo"]["rise_px"]["dur_s"], self.L["intro_animation"]["logo"]["scale_keys"][-1][0])
        for i in range(len(self.words)):
            t0, dur = self._word_timing(i)
            e = max(e, t0 + dur)
        return e

    def _draw_header(self, img, t, animate=True):
        s = self.s
        ia = self.L["intro_animation"]
        # ---- logo
        lg = ia["logo"]
        op = min(max(t / lg["opacity_dur_s"], 0.0), 1.0) if animate else 1.0
        if op > 0:
            tile = self.logo_tile
            sk = np.array(lg["scale_keys"])
            sc = float(np.interp(t, sk[:, 0], sk[:, 1])) if animate else 1.0
            rot = lg["rotation_deg"]
            ang = rot["start"] * max(1.0 - t / rot["dur_s"], 0.0) ** 2 if animate else 0.0
            ris = lg["rise_px"]
            rise = ris["start"] * s * max(1.0 - t / ris["dur_s"], 0.0) ** 2 if animate else 0.0
            if abs(sc - 1.0) > 1e-3 or ang > 1e-2 or rise > 1e-2 or op < 1.0:
                sz = tile.size
                t2 = tile.resize((max(2, int(sz[0] * sc)), max(2, int(sz[1] * sc))), Image.BICUBIC)
                if ang > 1e-2:
                    t2 = t2.rotate(-ang, resample=Image.BICUBIC, expand=True)
                small = t2.reduce(SS)
                blur = lg["blur_px"] * s * max(1.0 - op, 0.0)
                if blur > 0.3:
                    small = small.filter(ImageFilter.GaussianBlur(blur))
                cx, cy = self.logo_center
                ox = int(round(cx - small.size[0] / 2.0))
                oy = int(round(cy + rise - small.size[1] / 2.0))
            else:
                small = tile.reduce(SS)
                ox, oy = self.logo_origin
            self._paste_rgba(img, small, ox, oy, op)
        # ---- words
        tx = self.L["header"]["text"]
        col = rgb(tx["rgb"])
        we = ia["word_effect"]
        for w in self.words:
            t0, dur = self._word_timing(w["i"])
            p = (t - t0) / dur if animate else 1.0
            if p <= 0:
                continue
            p = min(p, 1.0)
            tile = w["tile"]
            if p < 1.0:
                dy = we["rise_px"] * (1.0 - p) ** we["rise_pow"] * s * SS
                blur = we["blur_px"] * (1.0 - p) ** we["blur_pow"] * s * SS
                big = Image.new("L", (tile.size[0], tile.size[1] + int(dy) + int(4 * blur) + 2), 0)
                big.paste(tile, (0, int(round(dy))))
                if blur > 0.5:
                    big = big.filter(ImageFilter.GaussianBlur(blur))
                alpha_img, op_w = big, 1.0 - (1.0 - p) ** we["opacity_pow"]
            else:
                alpha_img, op_w = tile, 1.0
            ox, oy = int(round(w["ox"])), int(round(w["oy"]))
            gx, gy = ox // SS, oy // SS
            fx, fy = ox - gx * SS, oy - gy * SS
            padded = Image.new("L", (alpha_img.size[0] + fx + SS, alpha_img.size[1] + fy + SS), 0)
            padded.paste(alpha_img, (fx, fy))
            pw, ph = padded.size
            padded = padded.crop((0, 0, pw - pw % SS, ph - ph % SS))
            a = np.asarray(padded.reduce(SS), dtype=np.float32) / 255.0 * op_w
            h_, w_ = a.shape
            ya, xa = max(gy, 0), max(gx, 0)
            yb, xb = min(gy + h_, self.H), min(gx + w_, self.W)
            if yb > ya and xb > xa:
                reg = img[ya:yb, xa:xb]
                blend(reg, col, a[ya - gy:yb - gy, xa - gx:xb - gx])

    @staticmethod
    def _paste_rgba(img, tile, ox, oy, opacity):
        a = np.asarray(tile, dtype=np.float32) / 255.0
        h, w = a.shape[:2]
        ya, xa = max(oy, 0), max(ox, 0)
        yb, xb = min(oy + h, img.shape[0]), min(ox + w, img.shape[1])
        if yb <= ya or xb <= xa:
            return
        sub = a[ya - oy:yb - oy, xa - ox:xb - ox]
        reg = img[ya:yb, xa:xb]
        blend(reg, sub[..., :3] * 255.0, sub[..., 3] * opacity)

    # ------------------------------------------------------------------ badges
    def _build_badge(self, label, icon_kind, card):
        if not label:
            return None
        s = self.s
        b = self.L["badge"]
        font = ss_font(self.font_bold, b["text"]["size_px"] * s)
        trk = b["text"]["tracking_em"] * b["text"]["size_px"] * s
        xs, tw = tracked_layout(font, label, trk)
        text_w = tw / SS
        ph = int(round(b["height"] * s))
        pw = int(round((b["pad_left"] + b["icon_box"] + b["gap_icon_text"] + b["pad_right"]) * s + text_w))
        rad = b["radius"] * s
        ow = b["outline_w"] * s
        outer = rounded_mask(pw, ph, rad)
        # inner (fill) mask inset by the outline width
        inner_im = Image.new("L", (pw * SS, ph * SS), 0)
        ImageDraw.Draw(inner_im).rounded_rectangle(
            [ow * SS, ow * SS, pw * SS - 1 - ow * SS, ph * SS - 1 - ow * SS], radius=max(rad - ow, 1) * SS, fill=255)
        inner = np.asarray(inner_im.reduce(SS), dtype=np.float32) / 255.0
        ring = np.clip(outer - inner, 0, 1)
        # overlay (icon + label), supersampled
        ov = Image.new("RGBA", (pw * SS, ph * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        icon = b["icon_box"] * s * SS
        ix = b["pad_left"] * s * SS
        iy = (ph * SS - icon) / 2.0 - 0.5 * s * SS
        self._draw_icon(ov, icon_kind, ix, iy, icon)
        tx = ix + icon + b["gap_icon_text"] * s * SS
        baseline = ph * SS / 2.0 + 5.8 * s * SS
        for k, ch in enumerate(label):
            d.text((tx + xs[k], baseline), ch, font=font, fill=tuple(b["text"]["rgb"]) + (255,), anchor="ls")
        ovs = np.asarray(ov.reduce(SS), dtype=np.float32)
        return {"x": card["x"] + int(round(b["offset_from_card"]["x"] * s)),
                "y": card["y"] + int(round(b["offset_from_card"]["y"] * s)),
                "w": pw, "h": ph, "inner": inner, "ring": ring, "ov": ovs}

    @staticmethod
    def _draw_icon(ov, kind, x, y, size):
        d = ImageDraw.Draw(ov)
        k = size / 24.0
        if kind == "blender":
            # simple Blender-like glyph (own drawing): orange ring with white inner ring and blue eye, two orange arms
            orange, blue = (234, 118, 0, 255), (52, 104, 168, 255)
            cx, cy = x + 15.2 * k, y + 13.0 * k
            d.line([(x + 10.2 * k, y + 6.6 * k), (x + 2.2 * k, y + 8.4 * k)], fill=orange, width=int(round(2.6 * k)))
            d.line([(x + 9.0 * k, y + 15.2 * k), (x + 1.8 * k, y + 19.2 * k)], fill=orange, width=int(round(2.6 * k)))
            d.line([(x + 12.4 * k, y + 5.2 * k), (x + 17.5 * k, y + 2.6 * k)], fill=orange, width=int(round(2.4 * k)))
            for (px, py) in ((x + 2.2 * k, y + 8.4 * k), (x + 1.8 * k, y + 19.2 * k), (x + 17.5 * k, y + 2.6 * k)):
                r = 1.3 * k
                d.ellipse([px - r, py - r, px + r, py + r], fill=orange)
            for r, col in ((8.2, orange), (5.4, (255, 255, 255, 255)), (3.6, blue)):
                d.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k], fill=col)
        elif kind == "kleo":
            # Kleo AI mark (kleooai.com/brand/kleo-favicon.svg geometry, 100-unit box): amber rounded square with a
            # square bottom-left corner and a dark, round-joined play triangle
            sz = size * (22.0 / 24.0)
            ox, oy = x + (size - sz) / 2.0, y + (size - sz) / 2.0
            u = sz / 100.0
            amber, ink = (243, 181, 63, 255), (26, 18, 0, 255)
            d.rounded_rectangle([ox, oy, ox + sz - 1, oy + sz - 1], radius=27 * u, fill=amber,
                                corners=(True, True, True, False))
            tri = [(ox + 39 * u, oy + 30 * u), (ox + 69 * u, oy + 50 * u), (ox + 39 * u, oy + 70 * u)]
            w, r = 9 * u, 4.5 * u
            d.polygon(tri, fill=ink)
            for i in range(3):
                p, q = tri[i], tri[(i + 1) % 3]
                d.line([p, q], fill=ink, width=int(round(w)))
                d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=ink)
        else:
            # small rounded-square icon: teal -> orange diagonal gradient with a white 4-point sparkle
            sz = int(round(22 * k))
            g = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
            px = np.zeros((sz, sz, 4), dtype=np.uint8)
            yy, xx = np.mgrid[0:sz, 0:sz]
            tt = (xx + yy) / (2.0 * sz)
            c0, c1 = np.array([22, 170, 160]), np.array([255, 140, 66])
            for ch in range(3):
                px[..., ch] = (c0[ch] * (1 - tt) + c1[ch] * tt).astype(np.uint8)
            px[..., 3] = 255
            g = Image.fromarray(px, "RGBA")
            m = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, sz - 1, sz - 1], radius=6.0 * k, fill=255)
            g.putalpha(m)
            gd = ImageDraw.Draw(g)
            c, a, b_ = sz / 2.0, 7.2 * k, 1.8 * k
            gd.polygon([(c, c - a), (c + b_, c - b_), (c + a, c), (c + b_, c + b_), (c, c + a), (c - b_, c + b_),
                        (c - a, c), (c - b_, c - b_)], fill=(255, 255, 255, 255))
            ov.paste(g, (int(round(x + (size - sz) / 2.0)), int(round(y + (size - sz) / 2.0))), g)

    def _draw_badge(self, img, bd, blur_px):
        if bd is None:
            return
        b = self.L["badge"]
        x, y, w, h = bd["x"], bd["y"], bd["w"], bd["h"]
        reg = img[y:y + h, x:x + w]
        # backdrop blur
        tmp = Image.fromarray(np.clip(reg + 0.5, 0, 255).astype(np.uint8))
        reg[:] = np.asarray(tmp.filter(ImageFilter.GaussianBlur(blur_px)), dtype=np.float32)
        fr = b["fill_rgba"]
        blend(reg, rgb(fr), bd["inner"] * fr[3])
        orr = b["outline_rgba"]
        blend(reg, rgb(orr), bd["ring"] * orr[3])
        ov = bd["ov"]
        blend(reg, ov[..., :3], ov[..., 3] / 255.0)

    # ------------------------------------------------------------------ progress lines
    def _draw_progress(self, img, card, frac, fill_rgb):
        s = self.s
        p = self.prog
        bh = int(round(p["height"] * s))
        x0, y1, w = card["x"], card["y"] + card["h"], card["w"]
        rows = slice(y1 - bh, y1)
        m = card["mask"][card["h"] - bh:card["h"]]            # (bh, w)
        reg = img[rows, x0:x0 + w]
        tr = p["track_rgba"]
        blend(reg, rgb(tr), m * tr[3])
        xe = frac * w
        cov = np.clip(xe - np.arange(w, dtype=np.float32), 0.0, 1.0)[None, :]
        blend(reg, rgb(fill_rgb), m * cov)

    # ------------------------------------------------------------------ one frame
    def render(self, t, top_frame, bottom_frame, duration):
        img = self.bg.copy()
        self._draw_waves(img, t)
        img *= self.shade
        animate = t < self.intro_end + 1e-6
        self._draw_header(img, t, animate=animate)
        for card, frame in ((self.card_top, top_frame), (self.card_bottom, bottom_frame)):
            x, y, w, h = card["x"], card["y"], card["w"], card["h"]
            reg = img[y:y + h, x:x + w]
            m = card["mask"][..., None]
            reg *= (1.0 - m)
            reg += frame.astype(np.float32) * m
        frac = min(max(t / duration, 0.0), 1.0)
        self._draw_progress(img, self.card_top, frac, self.prog["top_fill_rgb"])
        self._draw_progress(img, self.card_bottom, frac, self.prog["bottom_fill_rgb"])
        blur = self.L["badge"]["backdrop_blur_px"] * self.s
        for bd in self.badges:
            self._draw_badge(img, bd, blur)
        return np.clip(img + 0.5, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", required=True, help="top video (Blender grey-box previs), any size/fps")
    ap.add_argument("--bottom", required=True, help="bottom video (final render), any size/fps")
    ap.add_argument("--out", required=True, help="output .mp4 (H.264 yuv420p, +faststart)")
    ap.add_argument("--audio", help="optional audio file; trimmed/padded to the video duration, encoded AAC")
    ap.add_argument("--scale", type=float, default=1.0, help="1 -> 720x1280 (default), 1.5 -> 1080x1920")
    ap.add_argument("--header", default="Sonnet 5.5", help="header text under the logo (reference ad: 'Opus 5.5'; '' hides)")
    ap.add_argument("--badge-top", default="Blender", help="label of the top card badge ('' hides)")
    ap.add_argument("--badge-bottom", default="Kleo AI", help="label of the bottom card badge ('' hides)")
    ap.add_argument("--icon-bottom", default="kleo", choices=["seedance", "kleo", "blender"],
                    help="icon of the bottom card badge (kleo = Kleo AI mark from kleooai.com)")
    ap.add_argument("--fps", type=float, default=None, help="output fps (default 24)")
    ap.add_argument("--duration", type=float, default=None, help="override duration in s (default: shorter input)")
    ap.add_argument("--crf", type=int, default=18, help="x264 CRF (default 18)")
    ap.add_argument("--preset", default="medium", help="x264 preset (default medium)")
    ap.add_argument("--src-matrix", default="auto", choices=["auto", "bt709", "bt601"],
                    help="YUV matrix of the inputs when untagged (auto: bt709 for >=720p)")
    ap.add_argument("--layout", default=os.path.join(HERE, "layout_measurements.json"), help="layout json")
    ap.add_argument("--waves", default=os.path.join(HERE, "wave_model.json"), help="wave model json")
    ap.add_argument("--png-at", default=None,
                    help="comma list of times (s): write PNG frames at those times and exit (no encode); for tuning")
    ap.add_argument("--png-dir", default=".", help="directory for --png-at frames")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    layout = json.load(open(a.layout))
    waves = json.load(open(a.waves))
    fps = a.fps or layout["canvas"]["fps"]
    layout["canvas"]["fps"] = fps
    header = layout["header"]["text"]["default"] if a.header is None else a.header

    comp = Compositor(layout, waves, a.scale, header, a.badge_top, a.badge_bottom, a.icon_bottom)
    W, H = comp.W, comp.H

    info_t, info_b = probe(a.top), probe(a.bottom)
    duration = a.duration or min(info_t["duration"], info_b["duration"])
    nframes = int(round(duration * fps))
    duration = nframes / fps
    if not a.quiet:
        print("canvas %dx%d @%g fps, %d frames (%.3f s) | top %dx%d %.2fs | bottom %dx%d %.2fs" % (
            W, H, fps, nframes, duration, info_t["w"], info_t["h"], info_t["duration"],
            info_b["w"], info_b["h"], info_b["duration"]), file=sys.stderr)

    ct, cb = comp.card_top, comp.card_bottom
    dec_t = open_decoder(a.top, ct["w"], ct["h"], fps, pick_matrix(info_t, a.src_matrix), info_t, bool(a.png_at))
    dec_b = open_decoder(a.bottom, cb["w"], cb["h"], fps, pick_matrix(info_b, a.src_matrix), info_b, bool(a.png_at))

    png_times = None
    if a.png_at:
        png_times = {int(round(float(x) * fps)): float(x) for x in a.png_at.split(",")}
        os.makedirs(a.png_dir, exist_ok=True)

    enc = None
    if png_times is None:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
               "-r", "%g" % fps, "-i", "-"]
        if a.audio:
            cmd += ["-i", a.audio]
        cmd += ["-map", "0:v:0"]
        if a.audio:
            cmd += ["-map", "1:a:0", "-af", "apad", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                "-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf),
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                "-t", "%.6f" % duration, "-movflags", "+faststart", a.out]
        enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    last_t = last_b = None
    last_needed = max(png_times) if png_times else nframes - 1
    try:
        for i in range(nframes):
            if png_times is not None and i > last_needed:
                break
            tf = read_frame(dec_t, ct["w"], ct["h"], last_t)
            bf = read_frame(dec_b, cb["w"], cb["h"], last_b)
            if tf is None or bf is None:
                raise RuntimeError("no frames decoded from input (empty video?)")
            last_t, last_b = tf, bf
            t = i / fps
            if png_times is not None and i not in png_times:
                continue
            out = comp.render(t, tf, bf, duration)
            if png_times is not None:
                p = os.path.join(a.png_dir, "frame_%05.2f.png" % png_times[i])
                Image.fromarray(out).save(p)
                if not a.quiet:
                    print("wrote", p, file=sys.stderr)
            else:
                enc.stdin.write(out.tobytes())
                if not a.quiet and i % 48 == 0:
                    print("frame %d/%d" % (i, nframes), file=sys.stderr)
    finally:
        for p in (dec_t, dec_b):
            try:
                p.stdout.close()
            except Exception:
                pass
            p.kill()
        if enc is not None:
            enc.stdin.close()
            rc = enc.wait()
            if rc != 0:
                raise SystemExit("ffmpeg encode failed (exit %d)" % rc)
    if enc is not None and not a.quiet:
        print("wrote", a.out, file=sys.stderr)


if __name__ == "__main__":
    main()
