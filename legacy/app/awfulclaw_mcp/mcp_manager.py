"""MCP server for managing external MCP server integrations."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("mcp_manager")

_BUILTIN_SERVERS = frozenset(
    {"memory_write", "memory_search", "schedule", "skills", "imap", "mcp_manager"}
)


def _project_root() -> Path:
    # app/awfulclaw_mcp/mcp_manager.py → awfulclaw_mcp → app → project_root
    return Path(__file__).parent.parent.parent


def _mcp_servers_dir() -> Path:
    return _project_root() / "mcp_servers"


def _config_path() -> Path:
    return _project_root() / "config" / "mcp_servers.json"


def _load_config() -> dict[str, Any]:
    return json.loads(_config_path().read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _save_config(data: dict[str, Any]) -> None:
    _config_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL."""
    match = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", url)
    if match:
        return match.group(1), match.group(2)
    return None


def _fetch_github_raw(owner: str, repo: str, filename: str) -> str | None:
    """Fetch a raw file from GitHub, trying main then master branch."""
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filename}"
        try:
            r = httpx.get(url, timeout=10, follow_redirects=True)
            if r.status_code == 200:
                return r.text
        except httpx.HTTPError:
            pass
    return None


def _detect_and_configure(
    name: str, owner: str, repo: str, github_url: str
) -> dict[str, Any] | str:
    """
    Fetch package.json / pyproject.toml from the repo to determine how to run
    the MCP server. Returns a config entry dict or an error string.
    """
    clone_dir = _mcp_servers_dir() / name

    # --- npm ---
    pkg_json_text = _fetch_github_raw(owner, repo, "package.json")
    if pkg_json_text:
        try:
            pkg: dict[str, Any] = json.loads(pkg_json_text)
        except json.JSONDecodeError:
            return "Failed to parse package.json"

        bin_field = pkg.get("bin")
        if isinstance(bin_field, str):
            entry_file = bin_field
        elif isinstance(bin_field, dict) and bin_field:
            first_val = next(iter(bin_field.values()))
            entry_file = first_val if isinstance(first_val, str) else "index.js"
        else:
            main_field = pkg.get("main")
            entry_file = main_field if isinstance(main_field, str) else "index.js"

        if entry_file.startswith("./"):
            entry_file = entry_file[2:]

        return {
            "name": name,
            "command": "node",
            "args": [str(clone_dir / entry_file)],
            "source": {
                "github_url": github_url,
                "install_type": "npm_clone",
                "entry": entry_file,
            },
        }

    # --- Python ---
    pyproject_text = _fetch_github_raw(owner, repo, "pyproject.toml")
    if pyproject_text:
        try:
            pyproject: dict[str, Any] = tomllib.loads(pyproject_text)
        except tomllib.TOMLDecodeError:
            return "Failed to parse pyproject.toml"

        project_section: dict[str, Any] = pyproject.get("project", {})
        pkg_name_raw = project_section.get("name", name)
        pkg_name = pkg_name_raw if isinstance(pkg_name_raw, str) else name
        scripts: dict[str, Any] = project_section.get("scripts", {})

        if scripts:
            script_name = next(iter(scripts))
            args: list[str] = ["--project", str(clone_dir), "run", script_name]
        else:
            module_name = pkg_name.replace("-", "_")
            args = ["--project", str(clone_dir), "run", "python", "-m", module_name]

        return {
            "name": name,
            "command": "uv",
            "args": args,
            "source": {
                "github_url": github_url,
                "install_type": "python_clone",
                "package": pkg_name,
            },
        }

    return (
        f"Could not detect server type for {github_url} "
        "— no package.json or pyproject.toml found"
    )


def ensure_installed(entry: dict[str, Any]) -> None:
    """Clone and install a GitHub-sourced MCP server if the clone dir is missing.

    Called by the registry during config load for any entry that has a 'source' field.
    """
    source = entry.get("source")
    if not isinstance(source, dict):
        return

    name: str = entry["name"]
    github_url = source.get("github_url", "")
    install_type = source.get("install_type", "")
    clone_dir = _mcp_servers_dir() / name

    if clone_dir.exists():
        return

    if not github_url:
        logger.error("MCP server %r has source but no github_url — cannot install", name)
        return

    logger.info("MCP server %r missing — cloning from %s", name, github_url)
    _mcp_servers_dir().mkdir(parents=True, exist_ok=True)

    clone_result = subprocess.run(
        ["git", "clone", "--depth=1", github_url, str(clone_dir)],
        capture_output=True,
        text=True,
    )
    if clone_result.returncode != 0:
        logger.error("git clone failed for %r: %s", name, clone_result.stderr.strip())
        return

    if install_type == "npm_clone":
        install_result = subprocess.run(
            ["npm", "install", "--production"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
        )
        if install_result.returncode != 0:
            logger.error("npm install failed for %r: %s", name, install_result.stderr.strip())
        else:
            logger.info("npm install completed for %r", name)

    elif install_type == "python_clone":
        install_result = subprocess.run(
            ["uv", "sync"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
        )
        if install_result.returncode != 0:
            logger.error("uv sync failed for %r: %s", name, install_result.stderr.strip())
        else:
            logger.info("uv sync completed for %r", name)

    else:
        logger.warning("Unknown install_type %r for %r — skipping dep install", install_type, name)


def _check_server_status(entry: dict[str, Any]) -> str:
    """Return 'loaded', 'skipped: <reason>', or 'unknown'."""
    required: list[str] = entry.get("env_required", [])
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        return f"skipped — missing env vars: {', '.join(missing)}"
    return "loaded"


@mcp.tool()
def mcp_server_status() -> str:
    """Show the status of all registered MCP servers.

    Reports whether each server is loaded, skipped due to missing env vars,
    or has a known configuration problem.
    """
    data = _load_config()
    servers: list[dict[str, Any]] = data.get("servers", [])
    if not servers:
        return "No MCP servers registered."
    lines: list[str] = []
    for s in servers:
        status = _check_server_status(s)
        lines.append(f"- **{s['name']}**: {status}")
    return "\n".join(lines)


@mcp.tool()
def mcp_server_diagnose(name: str) -> str:
    """Attempt to start an MCP server and capture any startup errors.

    Spawns the server process for up to 3 seconds and reports whether it
    started cleanly or crashed, including any stderr output.
    """
    data = _load_config()
    entry = next((s for s in data.get("servers", []) if s["name"] == name), None)
    if entry is None:
        return f"Server '{name}' not found in config."

    status = _check_server_status(entry)
    if status != "loaded":
        return f"Server '{name}' cannot be started: {status}"

    cmd: list[str] = [entry["command"]] + [str(a) for a in entry.get("args", [])]
    raw_env: dict[str, str] = entry.get("env", {})
    env = {**os.environ, **{k: v.replace("${" + k + "}", os.environ.get(k, ""))
                             for k, v in raw_env.items()}}

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        time.sleep(3)
        proc.poll()
        if proc.returncode is None:
            proc.terminate()
            proc.wait(timeout=5)
            return f"Server '{name}' started and ran for 3s without errors — looks healthy."
        else:
            _, stderr = proc.communicate()
            return (
                f"Server '{name}' exited with code {proc.returncode}.\n"
                f"stderr:\n{stderr.strip() or '(empty)'}"
            )
    except Exception as exc:
        return f"Failed to start '{name}': {exc}"


@mcp.tool()
def mcp_server_restart() -> str:
    """Restart the awfulclaw agent service.

    This restarts the entire agent process, which reloads all MCP servers
    and picks up any new environment variables. Use after adding credentials
    or fixing configuration issues.
    """
    flag = _project_root() / "memory" / ".restart_requested"
    flag.touch()
    restart_script = _project_root() / "scripts" / "restart-service.sh"
    subprocess.Popen(["bash", str(restart_script)])
    return "Restarting the agent service. You'll receive a confirmation when it's back up."


@mcp.tool()
def mcp_server_list() -> str:
    """List all registered MCP servers from config/mcp_servers.json."""
    data = _load_config()
    servers: list[dict[str, Any]] = data.get("servers", [])
    if not servers:
        return "No MCP servers registered."
    lines: list[str] = []
    for s in servers:
        source: dict[str, Any] = s.get("source", {})
        origin = f" [from {source['github_url']}]" if source.get("github_url") else ""
        args_str = " ".join(str(a) for a in s.get("args", []))
        lines.append(f"- {s['name']}: {s['command']} {args_str}{origin}")
    return "\n".join(lines)


@mcp.tool()
def mcp_server_add(
    name: str,
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    env_required: list[str] | None = None,
) -> str:
    """Manually register an MCP server in config/mcp_servers.json.

    Use mcp_server_add_from_github for GitHub-hosted servers.
    Takes effect on the next idle tick — no restart needed.
    """
    if name in _BUILTIN_SERVERS:
        return f"Error: '{name}' is a built-in server and cannot be overwritten."

    data = _load_config()
    servers: list[dict[str, Any]] = data.get("servers", [])
    entry: dict[str, Any] = {"name": name, "command": command, "args": args}
    if env:
        entry["env"] = env
    if env_required:
        entry["env_required"] = env_required

    idx = next((i for i, s in enumerate(servers) if s["name"] == name), None)
    if idx is not None:
        servers[idx] = entry
        verb = "updated"
    else:
        servers.append(entry)
        verb = "added"

    data["servers"] = servers
    _save_config(data)
    return f"MCP server '{name}' {verb}. Takes effect on next idle tick."


@mcp.tool()
def mcp_server_add_from_github(
    name: str,
    github_url: str,
    env: dict[str, str] | None = None,
    env_required: list[str] | None = None,
) -> str:
    """Add an MCP server from a GitHub repository URL.

    Fetches package.json or pyproject.toml to auto-detect the server type,
    clones the repo to mcp_servers/<name>/, installs dependencies, and
    registers it in config/mcp_servers.json.
    Takes effect on the next idle tick — no restart needed.
    """
    if name in _BUILTIN_SERVERS:
        return f"Error: '{name}' is a built-in server and cannot be overwritten."

    parsed = _parse_github_url(github_url)
    if not parsed:
        return f"Error: could not parse GitHub URL '{github_url}'"
    owner, repo = parsed

    detection = _detect_and_configure(name, owner, repo, github_url)
    if isinstance(detection, str):
        return f"Error: {detection}"

    entry = detection
    if env:
        entry["env"] = env
    if env_required:
        entry["env_required"] = env_required

    ensure_installed(entry)

    data = _load_config()
    servers: list[dict[str, Any]] = data.get("servers", [])
    idx = next((i for i, s in enumerate(servers) if s["name"] == name), None)
    if idx is not None:
        servers[idx] = entry
        verb = "updated"
    else:
        servers.append(entry)
        verb = "added"
    data["servers"] = servers
    _save_config(data)

    clone_dir = _mcp_servers_dir() / name
    status = "installed" if clone_dir.exists() else "installation failed — check logs"
    return f"MCP server '{name}' {verb} and {status}. Takes effect on next idle tick."


@mcp.tool()
def mcp_server_remove(name: str) -> str:
    """Remove an MCP server from config/mcp_servers.json.

    Does not delete cloned files from mcp_servers/.
    Takes effect on the next idle tick — no restart needed.
    """
    if name in _BUILTIN_SERVERS:
        return f"Error: '{name}' is a built-in server and cannot be removed."

    data = _load_config()
    servers: list[dict[str, Any]] = data.get("servers", [])
    before = len(servers)
    servers[:] = [s for s in servers if s["name"] != name]
    if len(servers) == before:
        return f"MCP server '{name}' not found."
    data["servers"] = servers
    _save_config(data)
    return f"MCP server '{name}' removed. Takes effect on next idle tick."


if __name__ == "__main__":
    mcp.run()
