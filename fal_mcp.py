"""Muselight connector: lets agent apps (Claude Desktop, Claude Code, Cursor, OpenClaw, ChatGPT…)
control Muselight through their own subscription, using the Model Context Protocol (MCP).

Muselight must be running. Agent apps start this file themselves:
  command: <python>   args: ["<this file>"]

For apps that only reach servers over the internet (ChatGPT): run `python fal_mcp.py --http`, put a
tunnel in front of the printed local address, and give the app the printed secret path.
Set MUSELIGHT_URL if Muselight isn't on http://127.0.0.1:8765.
"""
import json, os, secrets, sys, urllib.error, urllib.request
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agent import SYSTEM, data_dir

HERE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def studio_url():
    """Where the running Muselight is: MUSELIGHT_URL, else the port it wrote on start."""
    url = (os.environ.get("MUSELIGHT_URL") or os.environ.get("KINETRA_URL") or os.environ.get("RELAY_STUDIO_URL")
           or os.environ.get("FAL_STUDIO_URL"))  # old names still honoured
    if url:
        return url.rstrip("/")
    try:
        return f"http://127.0.0.1:{int((data_dir(HERE) / 'port.txt').read_text())}"
    except (OSError, ValueError):
        return "http://127.0.0.1:8765"


def call(name, **args):
    STUDIO = studio_url()
    req = urllib.request.Request(f"{STUDIO}/api/agent/tool", data=json.dumps({"name": name, "args": args}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=960) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        raise ToolError(json.loads(e.read() or b"{}").get("error") or f"Muselight error {e.code}")  # ToolError reaches the agent as written
    except urllib.error.URLError:
        raise ToolError(f"Muselight isn't running at {STUDIO}. Ask the user to open Muselight, then try again.")


server = MCPServer("Muselight", instructions=SYSTEM.replace("The app may ask the user to approve a run; if they decline, don't retry it unasked.",
                                                            "Your app may ask the user to approve each run."))


@server.tool(description="Search the models the user can run by words in their name, id or type. One result per model, newest first.")
def search_models(query: str, limit: int = 10) -> str:
    return json.dumps(call("search_models", query=query, limit=limit))


@server.tool(description="List a model's input settings: names, types, allowed values, defaults and which are required. Call before generate.")
def get_model_inputs(model: str) -> str:
    return json.dumps(call("get_model_inputs", model=model))


@server.tool(description="Start generations. This spends the user's credits with the provider it runs on. Runs `count` times with the same inputs "
                         "(leave seed out for variety). Files go in as @path (e.g. @uploads/hero.png) or URLs. Returns run ids.")
def generate(model: str, inputs: dict, count: int = 1, label: str = "") -> str:
    return json.dumps(call("generate", model=model, inputs=inputs, count=count, label=label or f"agent · {model}"))


@server.tool(description="List the user's saved Muselight workflows.")
def list_workflows() -> str:
    return json.dumps(call("list_workflows"))


@server.tool(description="Run a saved workflow. This spends credits. Each row fills the workflow's {{name}} placeholders and is one run.")
def run_workflow(name: str, rows: list[dict] | None = None) -> str:
    return json.dumps(call("run_workflow", name=name, rows=rows or [{}]))


@server.tool(description="Recent runs with status, model, prompt, output files (@paths) and errors. Pass run_ids for specific runs.")
def get_results(limit: int = 10, run_ids: list[str] | None = None) -> str:
    return json.dumps(call("get_results", limit=limit, run_ids=run_ids or []))


@server.tool(description="Wait until runs finish (up to timeout_seconds), then return their results. If some are still running, call it again.")
def wait_for_runs(run_ids: list[str], timeout_seconds: int = 240) -> str:
    return json.dumps(call("wait_for_runs", run_ids=run_ids, timeout_seconds=timeout_seconds))


@server.tool(description="Look at an output or uploaded image to judge it. Pass its @path.")
def view_image(path: str) -> Image:
    img = call("view_image", path=path)
    return Image(data=__import__("base64").b64decode(img["data"]), format=img["media_type"].split("/")[-1])


@server.tool(description="List the user's uploaded reference files ('uploads') or recent outputs ('outputs') as @paths.")
def list_files(folder: str = "outputs", limit: int = 30) -> str:
    return json.dumps(call("list_files", folder=folder, limit=limit))


def main(http=False):
    if http:
        from mcp.server.transport_security import TransportSecuritySettings
        token_file = data_dir(HERE) / "connector_token.txt"
        if not token_file.exists():
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(secrets.token_urlsafe(24))
        path = f"/{token_file.read_text().strip()}/mcp"  # the secret path is the password: keep it private
        print(f"Muselight connector on http://127.0.0.1:8770{path}\n"
              f"Put a tunnel in front of http://127.0.0.1:8770 (e.g. `cloudflared tunnel --url http://127.0.0.1:8770`)\n"
              f"and give your app: https://<tunnel-address>{path}", flush=True)
        # tunnels send their own Host header; the secret path is what keeps strangers out
        server.run("streamable-http", host="127.0.0.1", port=8770, streamable_http_path=path,
                   transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    else:
        server.run()


if __name__ == "__main__":
    main(http="--http" in sys.argv)
