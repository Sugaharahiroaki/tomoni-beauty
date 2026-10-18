"""台本から Instagram リール / YouTube ショート向けの縦動画（1080x1920・30fps）を作る。

各カットを個別ファイルに書き出してから concat demuxer で結合する
（zoompan を filter_complex の concat と組み合わせるとカットが切り替わらないため）。

script の形:
{
  "speaker_notes": "話し手の指示（場面）",
  "bgm": {"file": "/abs/bgm.mp3", "start": 0, "category": "daily", "level_duck": null, "level_base": null},
  "scenes": [
    {"caption": "...", "caption_style": "hook|normal", "narration": "...", "duration": 2.0,
     "shots": [{"photo": "/abs/a.jpg", "video": "/abs/a.mp4"|null, "video_start": 0, "motion": "zoom_in",
                "tight": 1.0, "focus_x": 0.5, "focus_y": 0.5, "sec": 1.2}]}
  ],
  "cta": {"photo": "/abs/bg.jpg", "title": "サロン名", "text": "呼びかけ", "narration": "...", "duration": 2.0}
}
"""

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from .audio import FFMPEG, duration, measure_lufs

W, H, FPS = 1080, 1920, 30
SS = 3
ZOOM = 0.12

FONT_CANDIDATES = [
    "C:/Windows/Fonts/BIZ-UDGothicB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
]

CAPTION_Y = {"normal": 0.60, "hook": 0.26}
CAPTION_SIZE = {"normal": 66, "hook": 92}
SETTINGS_PATH = Path(__file__).with_name("settings.json")


class RenderError(RuntimeError):
    pass


def font_path():
    env = os.getenv("ENGINE_FONT")
    if env and Path(env).exists():
        return env
    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise RenderError("テロップ用の日本語フォントが見つかりません（ENGINE_FONT を設定するか fonts-noto-cjk を入れてください）")


def load_settings():
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


class Runner:
    def __init__(self):
        self.log = []

    def __call__(self, cmd, label):
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            self.log.append(f"[{label}] FAILED\n{r.stderr[-2000:]}")
            raise RenderError(f"{label} に失敗しました")
        self.log.append(f"[{label}] OK")


def esc(path):
    return str(path).replace("\\", "/").replace(":", "\\:")


def cover(fx=0.5, fy=0.5, tight=1.0):
    return f"scale={round(W * SS * tight)}:{round(H * SS * tight)}:force_original_aspect_ratio=increase,crop={W * SS}:{H * SS}:(iw-ow)*{fx}:(ih-oh)*{fy}"


def zoompan(motion, frames, amount=ZOOM):
    p = f"on/{max(frames - 1, 1)}"
    cx, cy = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    z, x, y = {
        "zoom_in": (f"1+{amount}*{p}", cx, cy),
        "zoom_out": (f"{1 + amount}-{amount}*{p}", cx, cy),
        "pan_right": (f"{1 + amount}", f"(iw-iw/zoom)*{p}", cy),
        "pan_left": (f"{1 + amount}", f"(iw-iw/zoom)*(1-{p})", cy),
        "static": ("1", cx, cy),
    }.get(motion, (f"1+{amount}*{p}", cx, cy))
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS}"


def drawtext(textfile, size, y, font, box=True, fade=True):
    opts = [f"fontfile='{esc(font)}'", f"textfile='{esc(textfile)}'", f"fontsize={size}", "fontcolor=white", "line_spacing=20", "x=(w-text_w)/2", f"y=h*{y}-text_h/2"]
    if fade:
        opts.append("alpha='min(t/0.15,1)'")
    if box:
        opts += ["box=1", "boxcolor=black@0.55", "boxborderw=28"]
    else:
        opts += ["borderw=5", "bordercolor=black@0.7"]
    return "drawtext=" + ":".join(opts)


def fit_size(text, base):
    return min(base, int((W - 200) / max(max(len(line) for line in text.split("\n")), 1)))


def write_text(work, name, text):
    path = work / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def encode_clip(run, src, vf, frames, out, label, pre=()):
    run([FFMPEG, "-y", *pre, "-i", str(src), "-vf", vf + ",format=yuv420p", "-frames:v", str(frames), "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(out)], label)


def split_shots(cut, frames):
    """カットの映像リストとフレーム数の組を返す。sec 指定のない映像で残りを等分する"""
    shots = cut.get("shots") or [cut]
    fixed = [round(s["sec"] * FPS) if s.get("sec") else None for s in shots]
    free = [k for k, f in enumerate(fixed) if f is None]
    rest = max(frames - sum(f for f in fixed if f), len(free))
    for n, k in enumerate(free):
        fixed[k] = rest // len(free) + (1 if n < rest % len(free) else 0)
    if not free:
        fixed[-1] += frames - sum(fixed)
    return list(zip(shots, fixed))


def shot_visual(shot, frames):
    video = shot.get("video")
    if video and Path(video).exists():
        vf = [f"fps={FPS}", f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={W}:{H}", "setsar=1", "tpad=stop_mode=clone:stop_duration=10"]
        return video, vf, ("-ss", str(shot.get("video_start", 0))), "video"
    vf = [cover(shot.get("focus_x", 0.5), shot.get("focus_y", 0.5), shot.get("tight", 1.0)), zoompan(shot.get("motion", "zoom_in"), frames), "setsar=1"]
    return shot["photo"], vf, (), shot.get("motion", "zoom_in")


def make_narration(cuts, narrator, settings, speaker=None):
    ns = settings["narration"]
    notes = []
    for i, c in enumerate(cuts):
        if not c.get("narration"):
            continue
        try:
            wav, cached = narrator.synthesize(c["narration"], hook=(i == 0), speaker=speaker, index=i)
        except FileNotFoundError:
            notes.append(f"[{c['narration']}] 声なし（テロップのみ）")
            continue
        voice = duration(wav)
        need = ns["lead_sec"] + voice + ns["tail_sec"]
        c["wav"], c["voice_sec"] = str(wav), voice
        c["duration"] = max(c.get("duration", 2.0), math.ceil(need * FPS) / FPS)
        notes.append(f"[{c['narration']}] 声 {voice:.2f}秒 → カット {c['duration']:.2f}秒{'（保存済み）' if cached else ''}")
    return notes


def duck_envelope(windows, bs):
    merged = []
    for s, e in sorted(windows):
        if merged and s - merged[-1][1] < bs["merge_gap_sec"]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    a, r = bs["duck_attack_sec"], bs["duck_release_sec"]
    traps = [f"clip((t-{s - a:.3f})/{a},0,1)*clip(({e + r:.3f}-t)/{r},0,1)" for s, e in merged]
    base, duck = bs["level_base"], bs["level_duck"]
    return f"{base}-{base - duck:.3f}*min(1,{'+'.join(traps)})"


def bgm_levels(bgm, bs):
    levels = {k: bs[k] for k in ("level_base", "level_duck")}
    levels.update(bs.get("category_levels", {}).get(bgm.get("category", ""), {}))
    levels.update({k: bgm[k] for k in ("level_base", "level_duck") if bgm.get(k) is not None})
    return levels


def mix_audio(run, video_only, total, bgm, voices, settings, work, out):
    bs, ms = dict(settings["bgm"]), settings["master"]
    inputs, chains, labels = [], [], []

    if bgm and bgm.get("file") and Path(bgm["file"]).exists():
        start = bgm.get("start", 0)
        eq = bs.get("voice_eq")
        eq_filter = f",equalizer=f={eq['freq']}:t=q:w={eq['width_q']}:g={eq['gain_db']}" if eq else ""
        bed = work / "bgm_bed.wav"
        run([FFMPEG, "-y", "-stream_loop", "-1", "-ss", str(start), "-i", str(bgm["file"]), "-t", f"{total:.3f}", "-af", f"dynaudnorm=f=250:g=11:m=8:p=0.9{eq_filter},aformat=sample_rates=48000:channel_layouts=stereo", str(bed)], "bgm leveling")
        gain = bs["reference_lufs"] - (measure_lufs(str(bed)) or bs["reference_lufs"])
        bs.update(bgm_levels(bgm, bs))
        level = f"volume='{duck_envelope([(s, s + d) for _, s, d in voices], bs)}':eval=frame" if voices else f"volume={bs['level_no_narration']}"
        inputs += ["-i", str(bed)]
        chains.append(f"[0:a]volume={gain:.2f}dB,{level},afade=t=in:d=0.2,afade=t=out:st={max(total - bs['fade_out_sec'], 0):.3f}:d={bs['fade_out_sec']}[bgm]")
        labels.append("[bgm]")

    first = 1 if labels else 0
    for k, (wav, start, _) in enumerate(voices):
        inputs += ["-i", str(wav)]
        chains.append(f"[{first + k}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=delays={round(start * 1000)}:all=1[v{k}]")
        labels.append(f"[v{k}]")

    chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[pad]")
    labels.append("[pad]")
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,atrim=0:{total:.3f}[mix]")

    mix = work / "mix.wav"
    run([FFMPEG, "-y", *inputs, "-filter_complex", ";".join(chains), "-map", "[mix]", str(mix)], "mix")

    master_gain = ms["loudness_lufs"] - (measure_lufs(str(mix)) or ms["loudness_lufs"])
    limit = 10 ** (ms["true_peak_db"] / 20)
    run([FFMPEG, "-y", "-i", str(video_only), "-i", str(mix), "-af", f"volume={master_gain:.2f}dB,alimiter=limit={limit:.3f}:level=0", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)], "master")


def render_reel(script, out_path, work_dir, narrator=None, settings=None, thumbnail_path=None):
    """台本から動画を作る。戻り値は {total, timeline, log, notes}"""
    settings = settings or load_settings()
    font = font_path()
    work = Path(work_dir)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    run = Runner()

    cuts = [dict(s) for s in script["scenes"]]
    if script.get("cta"):
        cuts.append(dict(script["cta"], cta=True))
    notes = make_narration(cuts, narrator, settings, script.get("speaker_notes")) if narrator else []

    clips, voices, t = [], [], 0.0
    for i, c in enumerate(cuts, 1):
        frames = round(c.get("duration", 2.0) * FPS)
        if c.get("cta"):
            vf = [
                cover(), zoompan("zoom_in", frames, amount=0.05), "setsar=1", "boxblur=18:2", "eq=brightness=-0.18:saturation=1.1",
                drawtext(write_text(work, "cta_title", c["title"]), fit_size(c["title"], 88), 0.42, font, box=False),
                drawtext(write_text(work, "cta_text", c["text"]), fit_size(c["text"], 58), 0.52, font),
            ]
            out = work / f"clip{i:02d}.mp4"
            encode_clip(run, c["photo"], ",".join(vf), frames, out, "cta")
            clips.append(out)
        else:
            style = c.get("caption_style", "normal")
            capfile = write_text(work, f"cap{i:02d}", c.get("caption", "") or " ")
            plan = split_shots(c, frames)
            frames = sum(n for _, n in plan)
            for k, (shot, n) in enumerate(plan):
                caption = drawtext(capfile, fit_size(c.get("caption", " ") or " ", CAPTION_SIZE[style]), CAPTION_Y[style], font, fade=(k == 0 and style != "hook"))
                src, vf, pre, kind = shot_visual(shot, n)
                out = work / f"clip{i:02d}_{k}.mp4"
                encode_clip(run, src, ",".join(vf + [caption]), n, out, f"cut{i}-{k + 1} {kind}", pre)
                clips.append(out)
        if c.get("wav"):
            voices.append((c["wav"], t + settings["narration"]["lead_sec"], c["voice_sec"]))
        t += frames / FPS
    total = t

    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{Path(c).as_posix()}'\n" for c in clips), encoding="utf-8")
    video_only = work / "video_only.mp4"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(video_only)], "concat")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mix_audio(run, video_only, total, script.get("bgm"), voices, settings, work, out_path)

    if thumbnail_path:
        run([FFMPEG, "-y", "-i", str(out_path), "-frames:v", "1", "-q:v", "3", str(thumbnail_path)], "thumbnail")

    timeline = [{"cut": i + 1, "duration": c.get("duration"), "narration": c.get("narration"), "voice_sec": c.get("voice_sec")} for i, c in enumerate(cuts)]
    return {"total": total, "timeline": timeline, "log": "\n".join(run.log), "notes": notes}
