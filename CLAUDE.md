# Muselight: project notes

Muselight is a **free desktop app** (Windows) for making images, video and audio with 1,000+ AI models, run on the user's
own provider accounts (fal.ai and about 25 others, plus their own GPUs through ComfyUI and RunPod). It's the owner's
passion project, not a business: there is no Muselight Credits, no markup and no subscription. A support note in the app
asks for donations (`DONATE_URL` in `studio_ui.html`: buymeacoffee.com/muselight).

The owner, Felix, isn't a developer: write to him in plain English, keep it short, and give exact click paths.

## Where things are

| Part | Where | Notes |
|---|---|---|
| App server | `studio.py` | local HTTP server on 127.0.0.1:8765; `python studio.py --selftest` |
| App interface | `studio_ui.html` | one file: styles, markup and script |
| Providers and prices | `providers/` | one module per provider; `compare.py` matches the same model across providers |
| ✦ Assistant | `agent.py` | uses the user's own assistant key (OpenRouter free, Anthropic, OpenAI…) |
| Connector for other AI apps | `fal_mcp.py`, `AGENT_GUIDE.md` | |
| Build | `build_exe.bat` → `Muselight.exe` | runs the self-test first; copies the exe to `download/` (what the website's Download button serves) |
| Website | `website/` | muselight.studio: one free-app page. Release with `tools/build_site.py`, then upload the zip in Cloudflare Pages (project `muselight-site`) and check the live site |

The code is public on GitHub (MuselightStudio/muselight, MIT licence): never commit keys, tokens or personal details.
`muselight_cloud/` is the retired Credits server from when Muselight was going to be a business (stopped on Fly.io).

## Working on the app

- Test with the `fal-studio-dev` launch config (serves the app on port 8765), in the real flow a user would take, and run
  the self-test before building. Ask before closing a running Muselight to rebuild.
- Real generations cost the owner's own provider credit: prefer cheap models (`fal-ai/flux/schnell`) and ask before
  anything over about $1.
- House style: Muselight's own dark green design tokens and themes in `studio_ui.html`; one consistent style for repeated
  elements; nothing out of alignment; plain words for non-experts.
- Never type passwords, API keys or card numbers anywhere (the owner pastes them); never recreate real people's
  likenesses or copyrighted characters.
