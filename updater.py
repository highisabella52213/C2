"""Secure, release-driven GitHub fork updater for Railway deployments.

The updater never overwrites a fork. It asks GitHub to merge upstream, stops on
conflicts, then asks Railway to deploy the resulting commit from the already
connected fork. Secrets are encrypted at rest and never returned by the API.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

CURRENT_VERSION = "17.0.0"
GITHUB_API = "https://api.github.com"
RAILWAY_GRAPHQL = "https://backboard.railway.com/graphql/v2"
CHECK_SECONDS = 5 * 60
MAX_RESPONSE_BYTES = 1024 * 1024
# Set this once in the publisher repository before creating the first release.
PUBLISHER_REPOSITORY = "OWNER/REPOSITORY"

class UpdateError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status

_data_dir = Path(os.environ.get("DATA_DIR", "/data"))
_state_file = _data_dir / "lumen_update.json"
_fernet: Fernet | None = None
_state: dict[str, Any] = {}
_lock = asyncio.Lock()
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def configure(data_dir: Path | str, master_secret: str) -> None:
    global _data_dir, _state_file, _fernet
    _data_dir = Path(data_dir)
    _state_file = _data_dir / "lumen_update.json"
    key = base64.urlsafe_b64encode(hashlib.sha256(str(master_secret).encode()).digest())
    _fernet = Fernet(key)


def _repository(value: str, *, field: str) -> str:
    value = str(value or "").strip().strip("/")
    if value.startswith("https://github.com/"):
        value = value[len("https://github.com/"):]
    if value.endswith(".git"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise UpdateError(field + " must use owner/repository format")
    return value


def _branch(value: str) -> str:
    value = str(value or "main").strip()
    if not value or len(value) > 200 or value.startswith(('-', '.')) or ".." in value or re.search(r"[\s~^:?*\\\[]", value):
        raise UpdateError("Invalid Git branch")
    return value


def _encrypt(value: str) -> str:
    if _fernet is None:
        raise RuntimeError("updater not configured")
    return _fernet.encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    if not value or _fernet is None:
        return ""
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def _token(name: str, env_name: str) -> str:
    env = str(os.environ.get(env_name, "")).strip()
    return env or _decrypt(str(_state.get(name, "")))


def _public_setup() -> dict:
    upstream = str(_state.get("upstream_repo") or os.environ.get("LUMEN_UPSTREAM_REPO") or PUBLISHER_REPOSITORY)
    if upstream == PUBLISHER_REPOSITORY and upstream.startswith("OWNER/"):
        upstream = ""
    return {
        "configured": bool(_token("railway_token", "LUMEN_RAILWAY_TOKEN") and _token("github_token", "LUMEN_GITHUB_TOKEN") and upstream and (_state.get("fork_repo") or os.environ.get("LUMEN_FORK_REPO"))),
        "railway_token_set": bool(_token("railway_token", "LUMEN_RAILWAY_TOKEN")),
        "github_token_set": bool(_token("github_token", "LUMEN_GITHUB_TOKEN")),
        "upstream_repo": upstream,
        "fork_repo": str(_state.get("fork_repo") or os.environ.get("LUMEN_FORK_REPO", "")),
        "branch": str(_state.get("branch") or os.environ.get("RAILWAY_GIT_BRANCH") or "main"),
        "service_id_detected": bool(os.environ.get("RAILWAY_SERVICE_ID")),
        "environment_id_detected": bool(os.environ.get("RAILWAY_ENVIRONMENT_ID")),
        "encrypted_storage": True,
    }


async def load() -> dict:
    global _state
    if _fernet is None:
        raise RuntimeError("updater not configured")
    try:
        if _state_file.exists():
            raw = await asyncio.to_thread(_state_file.read_text, encoding="utf-8")
            parsed = json.loads(raw)
            _state = parsed if isinstance(parsed, dict) else {}
    except Exception:
        _state = {}
    return _public_setup()


async def _save() -> None:
    _data_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(_state, ensure_ascii=False, indent=2)
    tmp = _state_file.with_suffix(".tmp")
    await asyncio.to_thread(tmp.write_text, body, encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    await asyncio.to_thread(tmp.replace, _state_file)


def setup_status() -> dict:
    return _public_setup()


def _request_json(url: str, *, method: str = "GET", headers: dict | None = None, payload: dict | None = None, timeout: float = 12.0) -> dict:
    merged = {"Accept": "application/json", "User-Agent": "Lumen-Relay-Updater/17"}
    if headers:
        merged.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        merged["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise UpdateError("Remote response is too large", 502)
            return json.loads(raw.decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(MAX_RESPONSE_BYTES).decode()).get("message")
        except Exception:
            detail = None
        raise UpdateError(str(detail or ("Remote API returned HTTP " + str(exc.code))), 409 if exc.code == 409 else 502) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise UpdateError("Could not reach update service: " + str(exc)[:160], 502) from None


async def _call(url: str, **kwargs) -> dict:
    return await asyncio.to_thread(_request_json, url, **kwargs)


def _github_headers(token: str = "") -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _railway_headers(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


async def _railway(query: str, variables: dict, token: str) -> dict:
    result = await _call(RAILWAY_GRAPHQL, method="POST", headers=_railway_headers(token), payload={"query": query, "variables": variables})
    errors = result.get("errors")
    if errors:
        message = str(errors[0].get("message") if isinstance(errors, list) and errors and isinstance(errors[0], dict) else errors)
        raise UpdateError("Railway rejected the request: " + message[:180], 502)
    return result.get("data") or {}


async def save_setup(data: dict) -> dict:
    global _state, _cache
    upstream_raw = str(data.get("upstream_repo") or _public_setup().get("upstream_repo") or "").strip()
    upstream = _repository(upstream_raw, field="Upstream repository") if upstream_raw else ""
    fork = _repository(data.get("fork_repo") or _public_setup().get("fork_repo"), field="Fork repository")
    branch = _branch(data.get("branch") or _public_setup().get("branch"))
    github_token = str(data.get("github_token") or "").strip() or _token("github_token", "LUMEN_GITHUB_TOKEN")
    railway_token = str(data.get("railway_token") or "").strip() or _token("railway_token", "LUMEN_RAILWAY_TOKEN")
    if len(github_token) < 20:
        raise UpdateError("A GitHub fine-grained token is required")
    if len(railway_token) < 20:
        raise UpdateError("A Railway account token is required")
    service_id = os.environ.get("RAILWAY_SERVICE_ID", "")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")
    if not service_id or not environment_id:
        raise UpdateError("Railway service/environment IDs were not detected", 400)

    repo_info = await _call(GITHUB_API + "/repos/" + fork, headers=_github_headers(github_token))
    full_name = str(repo_info.get("full_name") or "")
    parent = str((repo_info.get("parent") or {}).get("full_name") or "")
    if full_name.lower() != fork.lower():
        raise UpdateError("GitHub token cannot access the selected fork")
    if not upstream:
        upstream = _repository(parent if repo_info.get("fork") and parent else full_name, field="Upstream repository")
    if fork.lower() != upstream.lower() and (not repo_info.get("fork") or parent.lower() != upstream.lower()):
        raise UpdateError("Selected GitHub repository is not a fork of the upstream repository")
    await _railway("query { me { id email } }", {}, railway_token)

    async with _lock:
        _state = {
            "upstream_repo": upstream,
            "fork_repo": fork,
            "branch": branch,
            "github_token": _encrypt(github_token),
            "railway_token": _encrypt(railway_token),
            "configured_at": int(time.time()),
        }
        await _save()
        _cache = {"at": 0.0, "value": None}
    return _public_setup()


async def clear_setup() -> dict:
    global _state, _cache
    async with _lock:
        _state = {}
        _cache = {"at": 0.0, "value": None}
        try:
            await asyncio.to_thread(_state_file.unlink, missing_ok=True)
        except Exception:
            pass
    return _public_setup()


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", str(value or ""))
    if not match:
        raise UpdateError("Latest release tag does not contain a valid version", 502)
    return tuple(int(x or 0) for x in match.groups())


async def check_latest(force: bool = False) -> dict:
    global _cache
    setup = _public_setup()
    upstream = setup.get("upstream_repo")
    base = {"current_version": CURRENT_VERSION, "configured": setup["configured"], "setup_required": not setup["configured"], "available": False}
    if not upstream:
        return {**base, "reason": "upstream_repository_required"}
    now = time.monotonic()
    if not force and _cache.get("value") is not None and now - float(_cache.get("at") or 0) < CHECK_SECONDS:
        return dict(_cache["value"])
    github_token = _token("github_token", "LUMEN_GITHUB_TOKEN")
    release = await _call(GITHUB_API + "/repos/" + upstream + "/releases/latest", headers=_github_headers(github_token))
    tag = str(release.get("tag_name") or release.get("name") or "")
    latest = ".".join(str(x) for x in _version_tuple(tag))
    value = {
        **base,
        "latest_version": latest,
        "tag": tag,
        "available": _version_tuple(latest) > _version_tuple(CURRENT_VERSION),
        "release_url": str(release.get("html_url") or ""),
        "published_at": str(release.get("published_at") or ""),
    }
    _cache = {"at": now, "value": value}
    return dict(value)


async def apply_latest() -> dict:
    setup = _public_setup()
    if not setup["configured"]:
        raise UpdateError("Complete update setup first")
    github_token = _token("github_token", "LUMEN_GITHUB_TOKEN")
    railway_token = _token("railway_token", "LUMEN_RAILWAY_TOKEN")
    upstream = _repository(setup["upstream_repo"], field="Upstream repository")
    fork = _repository(setup["fork_repo"], field="Fork repository")
    branch = _branch(setup["branch"])
    service_id = os.environ.get("RAILWAY_SERVICE_ID", "")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")
    if not service_id or not environment_id:
        raise UpdateError("Railway service/environment IDs are unavailable")

    async with _lock:
        latest = await check_latest(force=True)
        if not latest.get("available"):
            return {"started": False, "already_current": True, **latest}
        repo_info = await _call(GITHUB_API + "/repos/" + fork, headers=_github_headers(github_token))
        parent = str((repo_info.get("parent") or {}).get("full_name") or "")
        if fork.lower() != upstream.lower() and (not repo_info.get("fork") or parent.lower() != upstream.lower()):
            raise UpdateError("Fork/upstream relationship changed; update stopped")
        await _call(GITHUB_API + "/repos/" + fork + "/merge-upstream", method="POST", headers=_github_headers(github_token), payload={"branch": branch})
        commit = await _call(GITHUB_API + "/repos/" + fork + "/commits/" + urllib.parse.quote(branch, safe=""), headers=_github_headers(github_token))
        sha = str(commit.get("sha") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise UpdateError("GitHub did not return a valid branch commit", 502)
        mutation = "mutation serviceInstanceDeployV2($serviceId: String!, $environmentId: String!, $commitSha: String!) { serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId, commitSha: $commitSha) }"
        variables = {"serviceId": service_id, "environmentId": environment_id, "commitSha": sha}
        last_error = None
        for attempt in range(3):
            try:
                deployment = await _railway(mutation, variables, railway_token)
                return {"started": True, "version": latest.get("latest_version"), "commit": sha[:12], "deployment": deployment.get("serviceInstanceDeployV2")}
            except UpdateError as exc:
                last_error = exc
                if attempt < 2 and "commit" in str(exc).lower():
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise
        raise last_error or UpdateError("Railway deployment failed", 502)
