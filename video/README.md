# Narrated explainer video

`media/hss_explainer.mp4` is built from three files:

| File | What it does |
|---|---|
| `narration.py` | The spoken script, one entry per segment. Numbers match `results/summary.json`. |
| `tts.py` | Synthesizes each segment with Gemini text-to-speech (`gemini-2.5-flash-preview-tts`, voice `Charon`) into `build/audio/`. Clips are cached by text, so only changed segments are re-synthesized. |
| `explainer.py` | The manim scene `HSSExplainer`. It plays each clip with `add_sound` and times the animations to the pauses between sentences. The quench part plays back the simulation in `web/quench_data.js`. |

## Build

```bash
pip install manim            # needs cairo and pango development headers
sudo apt install fonts-cmu   # Computer Modern Unicode, used for all text (no LaTeX needed)

export GEMINI_API_KEY=...     # never commit the key
python video/tts.py
cd video && manim -r 1920,1080 --fps 30 --media_dir build/media explainer.py HSSExplainer
ffmpeg -i build/media/videos/explainer/1080p30/HSSExplainer.mp4 \
  -c:v libx264 -crf 24 -preset slow -c:a aac -b:a 128k -movflags +faststart ../media/hss_explainer.mp4
```

`manim -ql ...` renders a quick 480p preview in a few minutes; the 1080p render takes much longer.
Change the voice or model with `TTS_VOICE` and `TTS_MODEL`.
