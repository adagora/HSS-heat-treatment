"""Synthesize the narration with Gemini text-to-speech.

    GEMINI_API_KEY=... python video/tts.py

Writes video/build/audio/<segment>.wav (24 kHz mono) and
video/build/audio/manifest.json with each clip's duration and the start
fraction of every sentence (used by the scene for timing).  Clips are cached
by a hash of their text and voice, so re-running only synthesizes changes.
"""

import base64
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from narration import SEGMENTS  # noqa: E402

MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-preview-tts")
VOICE = os.environ.get("TTS_VOICE", "Charon")
STYLE = ("Read this aloud in a calm, warm and curious tone, at a relaxed pace, "
         "like the narrator of a mathematics explainer video:")
OUT = Path(__file__).resolve().parent / "build" / "audio"
RATE = 24000


def synthesize(text):
    body = {
        "contents": [{"parts": [{"text": f"{STYLE} {text}"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    for attempt in range(6):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=180))
            part = resp["candidates"][0]["content"]["parts"][0]["inlineData"]
            data = base64.b64decode(part["data"])
            if data[:4] == b"RIFF":  # some models return a complete WAV file
                with wave.open(io.BytesIO(data)) as w:
                    data = w.readframes(w.getnframes())
            return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 5:
                wait = 20 * (attempt + 1)
                print(f"  HTTP {e.code}, retrying in {wait}s")
                time.sleep(wait)
                continue
            raise SystemExit(f"TTS failed: HTTP {e.code} {e.read()[:300]!r}")
        except (KeyError, IndexError) as e:
            if attempt < 5:
                time.sleep(5)
                continue
            raise SystemExit(f"TTS returned no audio: {e}")


def trim_silence(pcm, threshold=300, keep=0.08):
    """Strip leading/trailing silence, keeping `keep` seconds of padding."""
    import array

    s = array.array("h", pcm)
    loud = [i for i in range(0, len(s), 240) if max(abs(v) for v in s[i:i + 240]) > threshold]
    if not loud:
        return pcm
    pad = int(keep * RATE)
    a = max(0, loud[0] - pad)
    b = min(len(s), loud[-1] + 240 + pad)
    return s[a:b].tobytes()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mpath = OUT / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    for key, sentences in SEGMENTS:
        text = " ".join(sentences)
        digest = hashlib.sha1(f"{MODEL}|{VOICE}|{STYLE}|{text}".encode()).hexdigest()[:12]
        wav = OUT / f"{key}.wav"
        if manifest.get(key, {}).get("hash") == digest and wav.exists():
            print(f"{key:11s} cached ({manifest[key]['duration']:.1f}s)")
            continue
        print(f"{key:11s} synthesizing ...")
        pcm = trim_silence(synthesize(text))
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        dur = len(pcm) / (2 * RATE)
        # where each sentence starts, estimated from its share of the words
        words = [len(s.split()) for s in sentences]
        starts, acc = [], 0
        for n in words:
            starts.append(acc / sum(words))
            acc += n
        manifest[key] = {"hash": digest, "duration": dur, "starts": starts, "words_per_s": sum(words) / dur}
        mpath.write_text(json.dumps(manifest, indent=2))
        print(f"{key:11s} {dur:5.1f}s, {sum(words) / dur:.2f} words/s")
    total = sum(v["duration"] for k, v in manifest.items() if k in dict(SEGMENTS))
    print(f"total narration {total:.0f}s")


if __name__ == "__main__":
    main()
