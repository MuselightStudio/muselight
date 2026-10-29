# Muselight

A free, open-source Windows studio for over a thousand AI image, video and audio models (Kling, Veo, Seedance, FLUX,
Wan, GPT Image, ElevenLabs and many more), run on **your own provider accounts**. Every run goes to the cheapest provider
you've connected, and you see the price before it starts. No markup, no subscription, no account.

**[Download Muselight.exe](https://github.com/MuselightStudio/muselight/raw/main/download/Muselight.exe)** ·
[muselight.studio](https://muselight.studio) · [Buy me a coffee](https://buymeacoffee.com/muselight)

Windows may say it "protected your PC" the first time, because the app isn't code-signed: click **More info**, then
**Run anyway**.

## What it does

- **Create, Batch and Compare:** any model with all its settings, many versions from a list, or one idea on several models.
- **Prompt builder:** real cameras, lenses, film stocks, lighting and camera moves in plain words, one-click looks, and a
  live checklist of what a prompt is missing.
- **Storyboard, Timeline and Workflows:** plan a film scene by scene, cut it together, or chain models in a node editor.
- **Library:** characters, products, places and brand kits you mention with `@name` to keep them consistent.
- **✦ Assistant:** picks models, writes prompts and runs them (works with a free OpenRouter key).
- **One-click tools** on any result: upscale, remove background, relight, new angles, animate, add music, subtitles, dub…
- **Your own GPUs:** ComfyUI workflows on your PC, or RunPod GPUs you control.

## Providers

fal.ai, WaveSpeedAI, Atlas Cloud, Runware, Replicate, Kie.ai, PiAPI, Segmind, DeepInfra, Together, SiliconFlow,
Hugging Face, Google, OpenAI, xAI, Black Forest Labs, BytePlus, Alibaba DashScope, Kling, MiniMax, Luma, Runway,
Ideogram, Recraft, Stability, RunPod and ComfyUI. Keys are stored in Windows Credential Manager on your PC; requests go
straight from your PC to the provider.

## Run from source

Python 3.11 or newer on Windows:

```
python -m pip install pyinstaller anthropic "mcp[cli]" keyring pillow
python studio.py
```

`build_exe.bat` runs the self-test (`python studio.py --selftest`) and builds `Muselight.exe`.

`website/` is muselight.studio. `muselight_cloud/` is an old, retired credits server, kept for reference.

## Licence

MIT: see [LICENSE](LICENSE).
