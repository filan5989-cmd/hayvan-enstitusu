"""
The Institute for Animal Affairs - otomatik video uretim scripti
Konu -> Gemini (metin) tam senaryo -> Gemini (gorsel) sahne uretimi ->
Google TTS seslendirme -> ffmpeg montaj -> kapak -> YouTube yukleme (opsiyonel)

Kullanim:
    python generate_video.py queue/XXX_konu.json
"""

import os
import sys
import json
import base64
import subprocess
import urllib.parse
import urllib.request
import urllib.error

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GOOGLE_TTS_KEY = os.environ.get("GOOGLE_TTS_API_KEY", "")
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "")

OUTPUT_DIR = "output"
IMG_DIR = os.path.join(OUTPUT_DIR, "images")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
CLIP_DIR = os.path.join(OUTPUT_DIR, "clips")

for d in (IMG_DIR, AUDIO_DIR, CLIP_DIR):
    os.makedirs(d, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

IMAGE_MODEL = "gemini-2.5-flash-image"
TEXT_MODEL = "gemini-3.6-flash"

STYLE_GUIDE = """Wes Anderson cinematic style, fully symmetrical, dead-center frontal one-point-perspective composition, as if the viewer sits in the exact middle of a small theater. Soft pastel storybook color palette (dusty salmon pink, butter yellow, powder blue, muted teal, warm cream) with a single recurring pop of deep vermillion red. Meticulously arranged, diorama-like sets, obsessive small props, even flat diffuse lighting, no harsh shadows, gentle 35mm film grain. All animal characters are fully anthropomorphic and gently caricatured: they stand upright on two legs, wear period-appropriate human clothing suited to their role, use human hand gestures, and interact with human props and furniture. Their faces keep the animal's recognizable features but carry expressive, human-like emotion. Dignified storybook caricature, not realistic wildlife. No text, no letters, no captions anywhere in the image."""


def expand_topic_to_scenes(topic: str, num_scenes: int = 30) -> dict:
    """Bir hayvan/tema konusunu 'The Institute for Animal Affairs' formatinda tam video planina cevirir."""
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY tanımlı değil.")

    system_prompt = f"""You are the head writer for "The Institute for Animal Affairs" — a deadpan mock-documentary
YouTube channel. Each episode studies one animal's well-known cliche, uses it as a lens onto one human
institution (press, law, politics, banking, academia, etc.), and lands on one universal human flaw, ending
on a quiet philosophical question. The animal is a mask: the episode is really a civilization critique
(like Orwell's Animal Farm), but the word "human" is NEVER used and the connection is never spelled out —
the viewer draws it themselves.

TOPIC (animal + institution + implied flaw): {topic}

Write the full episode as STRICT JSON (no markdown fences, no commentary, just the JSON object).

NARRATION VOICE: a dry, precise, faintly amused narrator, certain of every word, never raising his voice,
delivering the funniest lines with the straightest face. Use em dashes for a held beat, ellipses for a dry
trailing drop, short fragments for comic timing. Build one continuous argument scene by scene: setup ->
the animal's cliche introduced -> the institution introduced -> the flaw demonstrated through small concrete
moments -> escalation -> a calm, quietly devastating final line that is a small, flat, ironic punchline.

STRUCTURE (exactly {num_scenes} scenes total):
- Scene 1 is ALWAYS the channel's opening notice card: image_prompt describes a simple centered pastel
  title-card illustration (following the style guide, but plain/symmetrical background only, no characters),
  and narration is exactly: "This channel studies animals exclusively. Any resemblance to humans is entirely
  in the imagination of the viewer."
- Scenes 2 through {num_scenes} tell the episode following the voice and structure above.
- The final scene must land on the quiet ironic punchline, not a subscribe request.
- After the final scene, do NOT add a separate subscribe scene; instead the LAST scene's narration itself
  may end with a brief, dryly-delivered "Subscribe for a new report each week." in the same deadpan tone.

For EVERY scene's "image_prompt" (except scene 1's plain title card), follow this exact style:
"{STYLE_GUIDE}"
...and then append the specific scene description: which anthropomorphic animal character(s), their
period-appropriate clothing/props suited to the institution being satirized, the symmetrical diorama setting,
and the action/expression for that scene.

Keep the protagonist animal's design (clothing, accessories) consistent in every scene's description so it
reads as the same individual throughout.

Output EXACTLY this JSON schema, nothing else:
{{
  "video_meta": {{
    "title": "Why [Animal] Can Never Be [Institution Role] (catchy, under 70 chars)",
    "description": "2-4 sentence description in the Institute's dry voice, plus a one-line premise, plus 3-5 relevant hashtags. Do not use the word human.",
    "tags": ["...", "..."]
  }},
  "thumbnail": {{
    "background_prompt": "Follows the style guide: the protagonist animal centered on a small stage or podium mid-gesture, dignified and sincere. Composition shifted so the left third holds the figure and the right third is calm negative space left open for title text. Richer, punchier contrast than in-episode frames. No text in the image.",
    "left_label": "",
    "right_label": "",
    "left_color": "0x2E86AB",
    "right_color": "0xE07A5F"
  }},
  "scenes": [
    {{"image_prompt": "...", "narration": "..."}}
  ]
}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": system_prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY},
    )
    print(f"Bölüm senaryoya çevriliyor: {topic[:70]}...")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"GEMINI METIN HATA {e.code}: {body}")
        raise

    text_out = result["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text_out.startswith("```"):
        text_out = text_out.split("```")[1]
        if text_out.startswith("json"):
            text_out = text_out[4:]
    return json.loads(text_out)


def _pollinations_generate_image(prompt: str, out_path: str, seed: int = 42):
    """Pollinations.ai (flux, ucretsiz) ile gorsel uretir, out_path'e kaydeder."""
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&seed={seed}&model=flux"

    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"POLLINATIONS HATA {e.code}: {body}")
        raise
    with open(out_path, "wb") as f:
        f.write(data)


def generate_image(prompt: str, index: int) -> str:
    out_path = os.path.join(IMG_DIR, f"scene_{index:03d}.jpg")
    print(f"[{index}] Görsel isteniyor: {prompt[:70]}...")
    _pollinations_generate_image(prompt, out_path, seed=index)
    return out_path


def generate_thumbnail(thumb_cfg: dict) -> str:
    bg_prompt = thumb_cfg.get("background_prompt", "")
    final_thumb = os.path.join(OUTPUT_DIR, "thumbnail.jpg")
    print("Kapak resmi isteniyor...")
    _pollinations_generate_image(bg_prompt, final_thumb, seed=999)
    return final_thumb


def generate_audio(text: str, index: int, voice_name: str = "en-GB-Neural2-D", language_code: str = "en-GB") -> str:
    """Google Cloud Text-to-Speech ile seslendirme uretir."""
    if not GOOGLE_TTS_KEY:
        raise RuntimeError("GOOGLE_TTS_API_KEY tanımlı değil.")

    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_KEY}"
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": language_code, "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.95, "pitch": -1.0},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    print(f"[{index}] Seslendirme üretiliyor ({len(text)} karakter)...")
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    audio_bytes = base64.b64decode(result["audioContent"])
    out_path = os.path.join(AUDIO_DIR, f"scene_{index:03d}.mp3")
    with open(out_path, "wb") as f:
        f.write(audio_bytes)
    return out_path


def get_audio_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def wrap_text(text: str, max_chars: int = 42) -> str:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def make_scene_clip(image_path: str, audio_path: str, index: int, subtitle_text: str = "") -> str:
    duration = get_audio_duration(audio_path)
    fps = 30
    total_frames = int(duration * fps)
    out_path = os.path.join(CLIP_DIR, f"clip_{index:03d}.mp4")

    vf_parts = [
        "scale=1600:900:force_original_aspect_ratio=increase",
        "crop=1600:900",
        f"zoompan=z='min(zoom+0.0007,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1280x720:fps={fps}",
    ]

    if subtitle_text:
        wrapped = wrap_text(subtitle_text)
        safe_text = wrapped.replace("'", "\u2019").replace(":", "\\:").replace(",", "\\,")
        vf_parts.append(
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"text='{safe_text}':fontcolor=white:fontsize=34:"
            "borderw=3:bordercolor=black:x=(w-text_w)/2:y=h-170:"
            "line_spacing=6"
        )

    vf = ",".join(vf_parts)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        "-t", str(duration),
        out_path,
    ]
    print(f"[{index}] ffmpeg ile sahne birleştiriliyor ({duration:.1f}sn)...")
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def concat_clips(clip_paths: list, final_name: str = "final_video.mp4") -> str:
    list_file = os.path.join(OUTPUT_DIR, "concat_list.txt")
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    final_path = os.path.join(OUTPUT_DIR, final_name)
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", final_path]
    print("Tüm sahneler birleştiriliyor...")
    subprocess.run(cmd, check=True, capture_output=True)
    return final_path


def upload_to_youtube(video_path: str, thumb_path: str, meta: dict):
    if not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        print("YouTube secret'ları eksik, yükleme atlanıyor. Video sadece dosya olarak üretildi.")
        return

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None,
        refresh_token=YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": meta.get("title", "Untitled"),
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "categoryId": "24",
        },
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }

    print("YouTube'a yükleniyor (private/taslak olarak)...")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response["id"]
    print(f"Yüklendi! Video ID: {video_id} (private, izlemek için: https://youtu.be/{video_id})")

    if thumb_path and os.path.exists(thumb_path):
        print("Kapak resmi ayarlanıyor...")
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumb_path)).execute()

    return video_id


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python generate_video.py queue/XXX_konu.json")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        config = json.load(f)

    if "scenes" not in config and "topic" in config:
        config = expand_topic_to_scenes(config["topic"], config.get("num_scenes", 30))
        with open(os.path.join(OUTPUT_DIR, "expanded_scenes.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    scenes = config["scenes"]
    meta = config.get("video_meta", {})
    thumb_cfg = config.get("thumbnail", {})

    clip_paths = []
    for i, scene in enumerate(scenes, start=1):
        image_path = generate_image(scene["image_prompt"], i)
        audio_path = generate_audio(scene["narration"], i)
        clip_path = make_scene_clip(image_path, audio_path, i, subtitle_text=scene["narration"])
        clip_paths.append(clip_path)

    final_video = concat_clips(clip_paths)

    thumb_path = None
    if thumb_cfg.get("background_prompt"):
        thumb_path = generate_thumbnail(thumb_cfg)

    print(f"\nBitti! Video hazır: {final_video}")
    if thumb_path:
        print(f"Kapak resmi hazır: {thumb_path}")

    upload_to_youtube(final_video, thumb_path, meta)


if __name__ == "__main__":
    main()
