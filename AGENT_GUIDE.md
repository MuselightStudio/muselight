# Muselight: guide for AI agents

This guide is for an AI agent (Claude, ChatGPT, Grok, OpenClaw, Codex, Claude Code and others) that has been asked to use **Muselight** for its user. Muselight is a free desktop app that runs over a thousand image, video and audio models on the user's own provider accounts: fal.ai and about 25 other providers (marketplaces like Runware, WaveSpeedAI, Kie.ai and Replicate; model makers like Google, OpenAI, Black Forest Labs, Kling and Runway; and their own GPUs through ComfyUI and RunPod), each enabled by the user's own key in **Connections**. Each run is paid from that provider's own balance.

**Model ids:** fal models have plain ids (`fal-ai/flux/dev`). Other providers' ids carry a prefix: `wavespeed:`, `atlas:`, `replicate:`, `runware:`, `kie:`, `piapi:`, `segmind:`, `deepinfra:`, `together:`, `siliconflow:`, `huggingface:`, `google:`, `openai:`, `xai:`, `bfl:`, `byteplus:`, `dashscope:`, `kling:`, `minimax:`, `luma:`, `runway:`, `ideogram:`, `recraft:`, `stability:`, `runpod:`, `comfyui:`. Examples: `runware:bfl-flux-1-schnell`, `wavespeed:google/nano-banana-2.1/edit`, `runpod:wan-2-5`, `replicate:black-forest-labs/flux-schnell`. Their category reads e.g. "Runware · text-to-image", and many descriptions start with the price ("From $0.03 per run"). Search a provider's name to see only its models. Any Replicate model works by typing `replicate:owner/name`, even if it isn't listed.

**Cheapest provider (the Cheapest switch in the header, on by default):** each run goes to the cheapest provider the user has connected that offers the same model, with the settings translated into that provider's names. Matching is strict (same family, version, tier and mode); if the cheaper provider fails, the run goes back to the one chosen. Under the model box the Create tab shows the estimated price, where it will run, and any unconnected provider listing it cheaper ("💡 Might be cheaper"); result cards show "Via <provider> ≈ $x · saved ≈ $y". Prices come, best first, from the provider's own quote for these exact settings (WaveSpeed, Atlas Cloud, Ideogram; Runware from its rate card), from what the user's past runs there actually cost ("measured": Runware, Segmind, DeepInfra, RunPod, and fal when the optional fal admin key is saved), or from list prices. Runs ask up to 4 connected providers for quotes before choosing. To see every provider's price for a run, send `POST /api/prices` with `{"model": id, "inputs": {...}, "exact": true}` (exact asks every connected provider that can quote; nothing runs). Result cards show "Charged $x" when the provider reported the real cost.

**One row per model:** the model picker groups the same model across providers into one row (e.g. "Seedance 2.5 Image to Video · 5 providers · best $0.134/sec on Atlas Cloud · yours … on fal"). Picking it selects the cheapest provider the user is connected to. Under the model box a price table lists every provider with its unit price, this run's estimate, and "best price", "best connected" and "runs here" tags. Before a run, if a provider the user hasn't connected lists the model cheaper, a pop-up asks whether to connect it or continue (it has a "Never show this again" box; a link under the price table turns it back on).

**The user's own GPUs (GPUs button):** `comfyui:<name>` models are the user's own ComfyUI workflows, run free on their PC (or any ComfyUI server). With a RunPod key, the GPUs window can deploy a ComfyUI image endpoint (its models appear as `runpod:<endpoint id>/<workflow>`, billed only while working), a private assistant model (vLLM) for the ✦ Assistant (one of the ready picks, or "Your own model…" from Hugging Face, Hugging Bay, ModelScope or any Hugging Face mirror; pasting a link picks the source. Check shows its size, the GPU it needs and its tool-call format, and for Hugging Bay its licence and safety scan: a flagged model is refused. Hugging Bay and ModelScope models are downloaded by the worker on each cold start and checked against their SHA-256. Gated Hugging Face models use the user's Hugging Face token), and ComfyUI pods (billed hourly while running). Deploying, deleting or starting GPUs costs the user money: only do it when they ask, and tell them the hourly price shown.

Muselight has to be running first. The user starts it by double-clicking **Muselight.exe** (or **Muselight.bat** when running from source). It opens a window titled **Muselight**, normally served at `http://127.0.0.1:8765`. The exact port is written to `studio_data/port.txt` next to the program.

## Pick the best way in

| How you can act | Use | Reliability |
|---|---|---|
| You support MCP tools (Claude Desktop, Claude Code, Cursor, OpenClaw, ChatGPT with Developer mode…) | **The Muselight connector**, `fal_mcp.py` | Best |
| You can run terminal commands (Codex, Claude Code, OpenClaw exec…) | **The local API** below | Very good |
| You can only see and click the screen | **The screen guide** below | Works, but slower |

The user sets up the connector from the app: **✦ Assistant → Connect an app** shows the exact settings for their computer. With the packaged app, the connector is `Muselight.exe --mcp`.

This guide is built into Muselight. A copy is saved as `studio_data/AGENT_GUIDE.md` next to the program each time it starts, and **✦ Assistant → Connect an app → Copy agent guide** copies it for pasting into an agent's chat.

## Rules for every route

- **Every generation spends the user's credits with that provider.** Only run what was asked. Confirm before any large batch (more than about 10 runs) unless the user already told you the number.
- **Read a model's settings before using it.** Setting names and allowed values differ between models. With the connector, call `get_model_inputs`. Through the API, use `/api/schema`.
- **Local files** are written as `@path`, relative to the `studio_data` folder. For example `@uploads/hero.png` or `@outputs/2026-10-20/123456_ab12cd_s0_0.jpg`. Web URLs also work.
- **Library tab:** saved elements (characters, products, locations, styles), each with reference files and a description. `@Name` in a prompt (spaces become dashes, e.g. `@Red-Sneaker`) sends all its files plus its description the first time; a style with no files inserts its description. The **Project brief** box, when ticked, is added to the end of every prompt. API: `GET /api/library`, `POST /api/library {"items": [...]}`.
- **Storyboard tab:** a story → scenes (the ✦ Assistant can write them via `POST /api/write {"prompt", "system"}`) → a keyframe per scene (with Continuity on, each builds on the previous one) → Animate each with a video model → Send videos to Timeline.
- **Timeline tab:** clips in order plus an optional soundtrack; Export joins them on fal (`fal-ai/ffmpeg-api/merge-videos`, then `merge-audio-video`).
- **Audio tab:** Voice (ElevenLabs v3), Music, Sound effects and Lip sync, each with a model picker and settings.
- **Marketing tab:** product photos, name, brief, audience and headline, plus styles (product shot, lifestyle, UGC, ad, poster, marketplace, unboxing, on a model) × formats (1:1, 4:5, 9:16, 16:9) × versions. One click starts every image, optionally each turned into a short video.
- **🎬 Direct** (under every prompt box) adds cinematography in plain words: camera moves, shot, lens, lighting, genre, era / film look, colour grade, tempo, mood.
- **✦ Tools** in the image viewer: upscale, remove background, animate, edit an area with a brush mask (FLUX Fill), expand, relight, new camera angle, virtual try-on, extend video, motion transfer, lip sync, add to timeline, use as a storyboard keyframe.
- **Draft / Final:** ⚡ Draft (next to Run, Create tab) runs the same setup at the lowest resolution, quality and length, with one output, faster modes, no generated sound and a fixed seed. Its card then has **⬆ Final**, which runs the full settings with that seed.
- **↻ Recreate** (on result cards and in ✦ Tools): rebuilds a result's composition, camera, lighting and style with a Library character or product swapped in (Nano Banana 2 Edit for images, Kling O3 video edit for videos).
- **🔥 Hook score** (✦ Tools): the ✦ Assistant scores an image, or a video's first 3 seconds, for hook, clarity, emotion, composition and platform fit, with fixes. It needs an assistant model that can see images. API: `POST /api/score {"images": [@paths], "kind": "image"|"video", "context"}`.
- **Spend / Budget** (the Spend pill in the top bar): spend this month (the charge where the provider reports it, else the estimate), a monthly budget (runs stop when it's used up unless confirmed; the API then needs `"over_budget_ok": true` in `/api/run`), and an "ask before any run over $X" limit.
- **Marketing product import:** paste a shop link. `POST /api/product {"url"}` returns the name, the description and up to 5 photos saved to uploads (Shopify, schema.org Product data, or share tags; some shops block it).
- **Library extras:** a **Brand kit** element (logo file, colours, fonts, tone, always/never rules) is sent by `@Name`, and Marketing can apply it to every image. Characters have a **Voice** (used by Audio → Voice) and **🧬 Train identity**: a FLUX LoRA trained on their photos (about $2), used by "Use trained identity" and Photo set. **Prompt rules** (real skin and hair, real camera look, natural UGC acting) are added only when the prompt uses those words.
- **🎬 Direct** writes a single "Cinematography: …" paragraph under the prompt from full descriptions: genre, era, grade, lighting, angle, shot size, camera, lens, focal length, depth of field, camera moves in order, tempo, mood.
- **Face masks (Seedance):** Seedance and BytePlus turn away reference photos showing real faces. Before such a run the app offers to cover each face with a white cross (Florence-2 finds them; you can also draw the boxes), then tells the model the cross is a privacy mask. It's also in ✦ Tools → Mask faces. API: `POST /api/facemask {"path": "@uploads/x.png", "boxes"?: [{x,y,w,h}]}` returns a masked copy.
- **Ad producer** (Marketing): a short chat that asks about the product, audience, goal, hook and format, then writes a brief. "Apply the brief" fills in the campaign with its concepts and video script. API: `POST /api/producer {"messages": [{role, content}], "product"}`. Marketing also has a **Hook** picker.
- **Timeline trims and ✂ Check my cut:** each clip has from/to seconds; trimmed clips are cut on fal (`fal-ai/workflow-utilities/trim-video`) before joining. Check my cut listens to each clip and flags silent starts and ends (with one-click Apply), dead air, clips over 6s, and mismatched sizes.
- **@mentions in prompts:** write `@name` in a prompt to refer to an uploaded file by its name (`@hero` for `uploads/hero.png`). In the app, typing `@` in a prompt box opens a picker with thumbnails; each mention is highlighted and a strip under the box shows its file and position ("→ Image 2"). At run time the app adds the file to the model's image/video/audio input if it's missing, and rewrites the mention in the form that model expects ("Image 2", "@Image2" for Kling and Grok, "[@reference_image_2]" for Vidu), numbered by the file's real position. Result cards show the prompt as sent ("Sent as: …").
- **Outputs** are saved in `studio_data/outputs/<date>/`. Check results before telling the user a run worked.

## 1. The connector (MCP)

The connector provides these tools:

| Tool | What it does |
|---|---|
| `search_models(query, limit)` | Searches every model (fal, plus any other provider the user has a key for) by name, id or type |
| `get_model_inputs(model)` | Lists a model's settings: types, allowed values, defaults and which are required |
| `generate(model, inputs, count, label)` | Starts `count` runs of one model. **Spends credits.** Returns run ids |
| `list_workflows()` / `run_workflow(name, rows)` | Lists or runs the user's saved workflows. **Running spends credits** |
| `wait_for_runs(run_ids, timeout_seconds)` | Waits for runs to finish, then returns their status, files and errors |
| `get_results(limit, run_ids)` | Lists recent runs |
| `view_image(path)` | Returns an output or upload as an image you can look at |
| `list_files(folder)` | Lists `uploads` (reference files) or `outputs` |

A typical flow: `search_models` → `get_model_inputs` → `generate` → `wait_for_runs` → `view_image` → report to the user with the file paths.

## 2. The local API (terminal agents)

The API is at `http://127.0.0.1:8765`. Every POST must send `Content-Type: application/json`. Requests from other websites are refused.

In Windows PowerShell, use `curl.exe` rather than `curl`, and put JSON in a file to avoid quoting problems. For example: `curl.exe -s -X POST -H "Content-Type: application/json" --data "@body.json" http://127.0.0.1:8765/api/agent/tool`.

**Simplest:** call the connector's tools directly. Send the same names and arguments as in the table above:

```
POST /api/agent/tool
{"name": "search_models", "args": {"query": "upscale", "limit": 5}}
→ {"result": [...]}
```

**Full control:**

| Request | Purpose |
|---|---|
| `GET /api/models` | Every model from every connected provider: `id`, `name`, `cat` (category), `desc` |
| `GET /api/schema?model=<id>` | A model's input schema (JSON Schema `properties`, `required`, defaults) |
| `POST /api/run` | Starts runs (see below). Returns `{"ids": [...]}` |
| `GET /api/state` | All runs (`jobs`, newest first), settings and saved workflows |
| `GET /api/job?id=<id>` | One run in full, including fal's raw response |
| `POST /api/cancel` `{"id": "<id>"}` or `{"all": true}` | Cancels runs |
| `POST /api/upload` `{"name": "photo.png", "data": "<base64>"}` | Saves a file and returns `{"value": "@uploads/…"}` |
| `GET /files/<path>` | Downloads an output or upload, e.g. `/files/outputs/2026-10-20/x.jpg` |
| `GET /api/workflow?name=<name>` / `POST /api/workflow` | Reads or saves a workflow |

`POST /api/run` body:

```json
{
  "name": "label shown in Results",
  "steps": [{"model": "krea/v3/edit", "inputs": {"prompt": "{{line}}", "image_urls": ["@uploads/hero.png"]}}],
  "rows": [{"line": "selfie at a cafe"}, {"line": "mirror selfie"}],
  "repeat": 1
}
```

How the body works:
- **Rows:** each row is one run. `{{name}}` in any input is replaced by that row's value.
- **Repeat:** multiplies the number of runs.
- **Multiple steps:** steps run in order. A later step can use `{{prev}}` for the previous step's first output URL, or `{{prev_all}}` for all of them.
- **Run status:** poll `GET /api/state` or `GET /api/job?id=…` until `status` is `done`, `error` or `cancelled`. Output files are in the run's `files` list, relative to `studio_data`.

## 3. Screen guide (agents that click)

The window has a top bar (brand, status, Spend, Cheapest switch, At once, Files, GPUs, Keys, Help, ✦ Assistant), a row of tabs under it, and one full-width tab at a time. Each tab that makes things (Create, Batch, Compare, Storyboard, Timeline, Audio, Marketing, Workflows, Automations) shows its own latest results large beside its settings ("Latest"), only for runs started from that tab; everything is in the **Results** tab (right end of the tab row, with a count badge). Runs start from the floating composer bar at the bottom (Copies, list mode, ⚡ Draft, ▶ Run, ＋ Add to workflow).

**Header (top)**
- **Status:** "Connected to fal, Runware…" listing each provider with a key (or "Connect a provider to start"), then **Making** and **Waiting** counts.
- **At once:** a number box for how many runs go to fal at the same time.
- **Buttons:** **Files** opens the output folder. **GPUs** manages ComfyUI workflows and RunPod GPUs. **Keys** manages provider keys (about 30, with a search box) and assistant keys. **? Help** opens the welcome guide. **✦ Assistant** opens the chat panel.

**Tabs:** **Create**, **Batch**, **Compare**, **Storyboard**, **Timeline**, **Audio**, **Marketing**, **Library**, **Workflows**, **Automations**, **Results**.

**Create tab**
1. Click the box under **AI model** ("Search models…"). Type a few words, use ↑ ↓ to choose, then press Enter. The model's settings appear below.
2. Fill in the settings. Image settings have a drop area plus **Upload…** and **Add URL / @path / {{var}}…** buttons. Number settings named seed have a 🎲 button.
3. Open **Advanced** for **Edit as JSON** (see or set every input at once, then **Apply JSON to form**) and **Reset settings**.
4. **Composer (the floating bar at the bottom):** **Copies** sets how many times to run it. The **No list / A list (one per line) / Spreadsheet (CSV)** dropdown makes one version per line or row. With a list, each line fills `{{line}}` in any setting. Click **▶ Run** to start.

**Batch tab:** pick a model the same way. Each setting has a **Single | Batch** switch. In Batch mode, write values separated by a line containing only `---`. Run 1 uses the first value, run 2 the second, and so on. Then click **▶ Run batch**.

**Compare tab:** click **＋ Add a model** for each model. Fill in one shared set of inputs; each model gets them in its own format. A model marked "needs …" is missing a required input. Click **▶ Run all models**.

**Workflows tab:** **Open the visual editor** opens a full-screen canvas. Below it, the **Saved workflows** dropdown has **Open** and **Delete**, and **Save the current workflow as** has a name box with **Save** and **New**. In the canvas:
- **Adding nodes:** search a model and click **Add model node**. The **+ Input node…** menu adds prompt, batch, image, video or parameter nodes.
- **Batch images / Batch videos nodes:** give each run its own files. Click **＋ Add images** (each file starts as its own run), then group them: **1 per run**, **All in 1 run**, **Split into N runs**, **Match N prompts** (spreads them evenly over the wired batch prompts), click **✂** between two files to split a run there, or **⤒ Join run N** to merge a run into the one above. Drag files to reorder. Each run box shows the batch prompt it will pair with. Wire it into a model's image setting; run 1's files go with prompt 1, and so on.
- **Connecting nodes:** drag from a node's **image ●**, **all ●** or **value ●** onto another node, either onto a setting's round port or anywhere on the node.
- **Buttons:** **Run**, **Save**, **Fit view** and **Close**.

**Automations tab:** fill in Name, the folder to watch and a saved workflow, then click **Add automation**. Every image dropped into that folder runs the workflow.

**Results tab**
- **Top row:** a search box, a summary like "10 runs · 14 outputs", **Cancel all** and **Clear finished**.
- **Filters:** status, model, output type, time, and **★ Starred**. **Group** and **Sort** dropdowns. View switch: **Cards | Gallery | List**. **Crop / Fit whole image** and a size slider.
- **Each card:** the outputs, a status label (DONE, RUNNING…), model name, prompt and time, plus **Load** (puts the run's settings back in the form), **Rerun**, **Details** and **★**.
- **Image viewer:** click an image to open it full size. It has **Use as input**, **Open folder**, **Copy link** and **Close (Esc)**. ← → move between images.

**Screen tips**
- Wait for "Loading schema…" to disappear before filling settings.
- A run is finished when its card label says DONE. FAILED cards show the error in red.
- Pop-ups like "This will start N runs… Continue?" appear for big batches. Confirm them only if the user agreed.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Muselight isn't running" / connection refused | Ask the user to open **Muselight** |
| "Connect a provider to start" in the header | The user pastes any provider's key in **Keys** (or the welcome screen), then it works straight away |
| `403 forbidden` from the API | Send `Content-Type: application/json`, and call `127.0.0.1` or `localhost` |
| A model rejects an input | Re-read `get_model_inputs`. Use only listed setting names and allowed values |
| Connector not showing in Claude Desktop | Fully quit Claude Desktop (system tray → Quit) and reopen it |
