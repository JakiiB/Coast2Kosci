#!/usr/bin/env python3
"""
Cross-platform verification, Git sync, and GitHub Pages deploy script for Coast2Kosci.
Works identically on KINOVO (Windows) and Antigravity Cloud Remote Agents (Linux).
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_OWNER = "JakiiB"
REPO_NAME = "Coast2Kosci"
FULL_REPO = f"{REPO_OWNER}/{REPO_NAME}"
REMOTE_URL = f"https://github.com/{FULL_REPO}.git"
DEFAULT_GIT_EMAIL = "jake@kineta.com.au"

FORBIDDEN_TRACKED_FILES = {
    "data/c2k_relay_config.json",
    "docs/macrodroid_gpslogger_setup.md",
}

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
    ".pdf",
    ".xlsx",
    ".fit",
    ".pyc",
    ".zip",
}

SECRET_REGEX = re.compile(
    r"(gho_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})"
)


def _collect_runtime_secrets(root: Path) -> list[tuple[str, str]]:
    """Load private values from ignored local files (when present) to ensure they never leak."""
    secrets_list: list[tuple[str, str]] = []
    relay_cfg = _load_json_file(root / "data" / "c2k_relay_config.json")
    if relay_cfg.get("ingest_key"):
        secrets_list.append(("C2K_INGEST_KEY", str(relay_cfg["ingest_key"])))
    for cand in (
        Path("/tmp/cloud_toolkit/.tokens/cloud_keys.json"),
        Path(tempfile.gettempdir()) / "cloud_toolkit" / ".tokens" / "cloud_keys.json",
        root.parent / "_Cloud_Toolkit" / ".tokens" / "cloud_keys.json",
    ):
        ck = _load_json_file(cand)
        for key_name in ("GITHUB_TOKEN", "C2K_INGEST_KEY", "REDBARK_API_KEY", "XERO_CLIENT_SECRET", "CLOUD_WEBAPP_SECRET"):
            val = str(ck.get(key_name) or "").strip()
            if len(val) >= 12:
                secrets_list.append((key_name, val))
    # Deduplicate by (name, val)
    return list(dict.fromkeys(secrets_list))


def _rmtree_readonly(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _safe_rmtree(path: Path) -> None:
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_rmtree_readonly)
    else:
        shutil.rmtree(path, onerror=_rmtree_readonly)


def _load_json_file(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _try_fetch_cloud_keys_via_gdrive() -> Path | None:
    gdrive_bin = shutil.which("gdrive")
    if not gdrive_bin:
        return None

    target_dir = Path("/tmp/cloud_toolkit/.tokens") if os.name != "nt" else Path(tempfile.gettempdir()) / "cloud_toolkit" / ".tokens"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "cloud_keys.json"

    env_variants = [os.environ.copy()]
    if "AGY_ACCOUNT" not in os.environ:
        alt = os.environ.copy()
        alt["AGY_ACCOUNT"] = "jakiib@gmail.com"
        env_variants.append(alt)

    for env in env_variants:
        for query_flags in (
            ["readonly", "search", "--name-exact", "cloud_keys.json", "--json"],
            ["readonly", "search", "--name-contains", "cloud_keys.json", "--json"],
        ):
            res = subprocess.run([gdrive_bin, *query_flags], capture_output=True, text=True, env=env)
            if res.returncode != 0 or not res.stdout.strip():
                continue
            try:
                payload = json.loads(res.stdout)
            except Exception:
                continue
            items = payload if isinstance(payload, list) else payload.get("files") or payload.get("items") or []
            matches = [it for it in items if isinstance(it, dict) and str(it.get("name", "")).strip() == "cloud_keys.json"]
            if not matches:
                continue
            file_id = str(matches[0].get("id", "")).strip()
            if not file_id:
                continue
            dl = subprocess.run(
                [gdrive_bin, "readonly", "download", file_id, "--out", str(target_file)],
                capture_output=True,
                text=True,
                env=env,
            )
            if dl.returncode == 0 and target_file.exists():
                try:
                    os.chmod(target_file, 0o600)
                except Exception:
                    pass
                return target_file
    return None


def resolve_github_auth(root: Path) -> tuple[str, str, str]:
    """Return (token, user_hint, source_label) without logging secret values."""
    env_token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    env_user = (os.environ.get("GITHUB_USER") or "").strip()
    fallback_auth: tuple[str, str, str] | None = None
    if env_token:
        try:
            _, uinfo = github_api_request("GET", "/user", env_token)
            detected = str(uinfo.get("login") or env_user or "").strip()
            if detected.lower() == REPO_OWNER.lower():
                return env_token, detected, "environment variable"
            fallback_auth = (env_token, detected or REPO_OWNER, "environment variable")
        except Exception:
            fallback_auth = (env_token, env_user or REPO_OWNER, "environment variable")

    candidates: list[Path] = []
    if os.environ.get("CLOUD_KEYS_PATH"):
        candidates.append(Path(os.environ["CLOUD_KEYS_PATH"]))
    candidates.extend(
        [
            Path("/tmp/cloud_toolkit/.tokens/cloud_keys.json"),
            Path(tempfile.gettempdir()) / "cloud_toolkit" / ".tokens" / "cloud_keys.json",
            root.parent / "_Cloud_Toolkit" / ".tokens" / "cloud_keys.json",
        ]
    )

    for cand in candidates:
        data = _load_json_file(cand)
        tok = str(data.get("GITHUB_TOKEN") or "").strip()
        if tok:
            usr = str(data.get("GITHUB_USER") or REPO_OWNER).strip()
            return tok, usr, f"cloud_keys.json ({cand.name})"

    downloaded = _try_fetch_cloud_keys_via_gdrive()
    if downloaded:
        data = _load_json_file(downloaded)
        tok = str(data.get("GITHUB_TOKEN") or "").strip()
        if tok:
            usr = str(data.get("GITHUB_USER") or REPO_OWNER).strip()
            return tok, usr, "gdrive download -> cloud_keys.json"

    if fallback_auth is not None:
        return fallback_auth

    gh_candidates = [shutil.which("gh"), str(Path.home() / ".gemini" / "bin" / "gh.exe")]
    for gh_bin in gh_candidates:
        if gh_bin and Path(gh_bin).exists():
            res = subprocess.run([gh_bin, "auth", "token"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip(), REPO_OWNER, "gh CLI keyring"

    raise RuntimeError(
        "No GitHub token found. Provide GITHUB_TOKEN, pull _Cloud_Toolkit/.tokens/cloud_keys.json into /tmp/cloud_toolkit/.tokens/, or ensure gdrive CLI / gh CLI is signed in."
    )


def github_api_request(method: str, path: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    url = path if path.startswith("https://") else f"https://api.github.com{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Coast2Kosci-PublishCloud",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8").strip()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed (HTTP {exc.code}): {body}") from None


def run_verify(root: Path) -> None:
    verify_script = root / "scripts" / "verify_map_app.py"
    if not verify_script.exists():
        raise FileNotFoundError(f"Verification script missing: {verify_script}")
    print("[1/5] Running scripts/verify_map_app.py ...")
    res = subprocess.run([sys.executable, str(verify_script)], cwd=str(root))
    if res.returncode != 0:
        raise RuntimeError("verify_map_app.py failed - aborting publish.")


def run_secret_guard(root: Path) -> int:
    print("[2/5] Running secret & ignore guard ...")
    git_dir = root / ".git"
    rel_paths: list[str] = []
    if git_dir.exists():
        res = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=str(root),
            capture_output=True,
        )
        if res.returncode != 0:
            raise RuntimeError("git ls-files failed during secret scan.")
        rel_paths = [p for p in res.stdout.decode("utf-8", errors="replace").split("\0") if p]
    else:
        skip_dirs = {"_archive", "raw_scrape", "gpx_drop", ".git", ".tokens", "__pycache__"}
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            parts = p.relative_to(root).parts
            if any(part in skip_dirs for part in parts):
                continue
            rel_paths.append(p.relative_to(root).as_posix())

    runtime_secrets = _collect_runtime_secrets(root)
    violations: list[str] = []
    for rel in rel_paths:
        norm = rel.replace("\\", "/")
        if norm in FORBIDDEN_TRACKED_FILES or norm.startswith(".tokens/") or norm.endswith("cloud_keys.json") or norm.endswith(".env"):
            violations.append(f"Forbidden private file is trackable: {norm}")
            continue
        p = root / norm
        if not p.is_file() or p.suffix.lower() in BINARY_EXTENSIONS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        m = SECRET_REGEX.search(text)
        if m:
            violations.append(f"Potential secret/token pattern matched in {norm} (match prefix: {m.group(1)[:6]}...)")
            continue
        for sec_name, sec_val in runtime_secrets:
            if sec_val in text:
                violations.append(f"Private credential {sec_name} appears inside trackable file: {norm}")

    if violations:
        raise RuntimeError("Secret Leak Guard blocked execution:\n  - " + "\n  - ".join(violations))
    print(f"Secret Leak Guard passed across {len(rel_paths)} trackable file(s).")
    return len(rel_paths)


def run_git_local(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip() or res.stdout.strip()}")
    return res


def run_git_network(args: list[str], cwd: Path, token: str) -> subprocess.CompletedProcess:
    basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    extra_header = f"AUTHORIZATION: basic {basic}"
    cmd = [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        f"http.https://github.com/.extraheader={extra_header}",
        *args,
    ]
    res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "").replace(basic, "<REDACTED>").replace(token, "<REDACTED>")
        raise RuntimeError(f"git {' '.join(args)} failed: {msg.strip()}")
    return res


def ensure_git_identity(cwd: Path, username: str) -> None:
    name_res = run_git_local(["config", "user.name"], cwd, check=False)
    if name_res.returncode != 0 or not name_res.stdout.strip():
        run_git_local(["config", "user.name", username], cwd)
    email_res = run_git_local(["config", "user.email"], cwd, check=False)
    if email_res.returncode != 0 or not email_res.stdout.strip():
        run_git_local(["config", "user.email", DEFAULT_GIT_EMAIL], cwd)


def _git_blob_sha1(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def _upload_blob_api(raw: bytes, token: str) -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    _, res = github_api_request(
        "POST",
        f"/repos/{FULL_REPO}/git/blobs",
        token,
        {"content": b64, "encoding": "base64"},
    )
    return str(res["sha"])


def _fetch_remote_tree_shas(branch: str, token: str) -> tuple[str | None, str | None, dict[str, str]]:
    try:
        _, ref_info = github_api_request("GET", f"/repos/{FULL_REPO}/git/ref/heads/{branch}", token)
        commit_sha = str((ref_info.get("object") or {}).get("sha") or "")
        if not commit_sha:
            return None, None, {}
        _, commit_info = github_api_request("GET", f"/repos/{FULL_REPO}/git/commits/{commit_sha}", token)
        tree_sha = str((commit_info.get("tree") or {}).get("sha") or "")
        _, tree_info = github_api_request("GET", f"/repos/{FULL_REPO}/git/trees/{tree_sha}?recursive=1", token)
        sha_map: dict[str, str] = {}
        for entry in tree_info.get("tree") or []:
            if entry.get("type") == "blob" and entry.get("path") and entry.get("sha"):
                sha_map[str(entry["path"])] = str(entry["sha"])
        return commit_sha, tree_sha, sha_map
    except RuntimeError as exc:
        if "HTTP 404" in str(exc) or "HTTP 409" in str(exc):
            return None, None, {}
        raise


def _sync_main_via_api(root: Path, token: str, message: str, force_main: bool) -> None:
    parent_sha, base_tree_sha, remote_shas = _fetch_remote_tree_shas("main", token)
    ls_res = run_git_local(["ls-files", "-z", "-s"], root)
    local_entries: dict[str, str] = {}
    for rec in ls_res.stdout.split("\0"):
        if not rec.strip():
            continue
        meta_part, rel_path = rec.split("\t", 1)
        mode = meta_part.split()[0]
        local_entries[rel_path] = mode if mode in ("100644", "100755") else "100644"

    tree_updates: list[dict] = []
    for rel_path, mode in sorted(local_entries.items()):
        raw = (root / rel_path).read_bytes()
        local_sha = _git_blob_sha1(raw)
        if remote_shas.get(rel_path) == local_sha:
            continue
        blob_sha = _upload_blob_api(raw, token)
        tree_updates.append({"path": rel_path, "mode": mode, "type": "blob", "sha": blob_sha})

    for remote_path in sorted(set(remote_shas.keys()) - set(local_entries.keys())):
        tree_updates.append({"path": remote_path, "mode": "100644", "type": "blob", "sha": None})

    if not tree_updates and parent_sha:
        print(f"Remote {FULL_REPO} (main) already matches workspace tree.")
        return

    tree_payload: dict = {"tree": tree_updates}
    if base_tree_sha:
        tree_payload["base_tree"] = base_tree_sha
    _, new_tree = github_api_request("POST", f"/repos/{FULL_REPO}/git/trees", token, tree_payload)

    commit_payload: dict = {
        "message": message,
        "tree": str(new_tree["sha"]),
        "parents": [parent_sha] if parent_sha else [],
    }
    _, new_commit = github_api_request("POST", f"/repos/{FULL_REPO}/git/commits", token, commit_payload)
    new_commit_sha = str(new_commit["sha"])

    if parent_sha:
        github_api_request(
            "PATCH",
            f"/repos/{FULL_REPO}/git/refs/heads/main",
            token,
            {"sha": new_commit_sha, "force": bool(force_main)},
        )
    else:
        github_api_request(
            "POST",
            f"/repos/{FULL_REPO}/git/refs",
            token,
            {"ref": "refs/heads/main", "sha": new_commit_sha},
        )

    # Align local git branch with remote commit when public fetch is reachable
    fetch_res = run_git_local(["fetch", "origin", "main"], root, check=False)
    if fetch_res.returncode == 0:
        run_git_local(["reset", "--mixed", "origin/main"], root, check=False)


def _deploy_pages_via_api(stage_dir: Path, token: str, message: str) -> None:
    existing_commit_sha, _, remote_shas = _fetch_remote_tree_shas("gh-pages", token)
    tree_entries: list[dict] = []
    for p in sorted(stage_dir.rglob("*")):
        if not p.is_file():
            continue
        rel_posix = p.relative_to(stage_dir).as_posix()
        if rel_posix.startswith(".git/") or rel_posix == ".git":
            continue
        raw = p.read_bytes()
        local_sha = _git_blob_sha1(raw)
        blob_sha = local_sha if remote_shas.get(rel_posix) == local_sha else _upload_blob_api(raw, token)
        tree_entries.append({"path": rel_posix, "mode": "100644", "type": "blob", "sha": blob_sha})

    _, new_tree = github_api_request("POST", f"/repos/{FULL_REPO}/git/trees", token, {"tree": tree_entries})
    _, new_commit = github_api_request(
        "POST",
        f"/repos/{FULL_REPO}/git/commits",
        token,
        {"message": message, "tree": str(new_tree["sha"]), "parents": []},
    )
    new_commit_sha = str(new_commit["sha"])
    if existing_commit_sha:
        github_api_request(
            "PATCH",
            f"/repos/{FULL_REPO}/git/refs/heads/gh-pages",
            token,
            {"sha": new_commit_sha, "force": True},
        )
    else:
        github_api_request(
            "POST",
            f"/repos/{FULL_REPO}/git/refs",
            token,
            {"ref": "refs/heads/gh-pages", "sha": new_commit_sha},
        )


def sync_main_branch(root: Path, token: str, login: str, message: str, force_main: bool) -> None:
    print("[4/5] Syncing full workspace to origin/main ...")
    if not (root / ".git").exists():
        raise RuntimeError(f"{root} is not a git repository. Clone or initialize git first.")

    ensure_git_identity(root, login)

    origin_res = run_git_local(["remote", "get-url", "origin"], root, check=False)
    if origin_res.returncode != 0:
        run_git_local(["remote", "add", "origin", REMOTE_URL], root)
    elif origin_res.stdout.strip() != REMOTE_URL:
        run_git_local(["remote", "set-url", "origin", REMOTE_URL], root)

    run_git_local(["add", "-A"], root)
    # Double-check forbidden files are absent from index
    ls_res = run_git_local(["ls-files", "-z"], root)
    indexed = set(ls_res.stdout.split("\0"))
    leaked = sorted(f for f in FORBIDDEN_TRACKED_FILES if f in indexed)
    if leaked:
        raise RuntimeError(f"Refusing commit: forbidden file(s) staged in index: {leaked}")

    status_res = run_git_local(["status", "--porcelain"], root)
    if status_res.stdout.strip():
        run_git_local(["commit", "-m", message], root)
        print("Committed local workspace changes to main.")
    else:
        print("Working tree clean; no new commit needed on main.")

    push_args = ["push", "-u", "origin", "HEAD:main"]
    if force_main:
        push_args.insert(1, "--force")
    try:
        push_res = run_git_network(push_args, root, token)
        if push_res.stderr.strip():
            print(push_res.stderr.strip())
    except RuntimeError as exc:
        if "403" in str(exc) or "Permission to" in str(exc):
            print("Git smart-HTTP used secondary account; syncing main via GitHub Git Data API ...")
            _sync_main_via_api(root, token, message, force_main)
        else:
            raise
    print(f"Pushed workspace to {FULL_REPO} (main).")

    _, repo_info = github_api_request("GET", f"/repos/{FULL_REPO}", token)
    if repo_info.get("default_branch") != "main":
        github_api_request("PATCH", f"/repos/{FULL_REPO}", token, {"default_branch": "main"})
        print(f"Updated default_branch on {FULL_REPO} to 'main'.")


def deploy_gh_pages(root: Path, token: str, login: str, message: str) -> None:
    print("[5/5] Staging clean static web bundle and deploying to gh-pages ...")
    stage_dir = Path(tempfile.mkdtemp(prefix="c2k_gh_pages_"))
    try:
        shutil.copy2(root / "index.html", stage_dir / "index.html")
        shutil.copytree(
            root / "src",
            stage_dir / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        if (root / "assets").exists():
            shutil.copytree(root / "assets", stage_dir / "assets")
        data_out = stage_dir / "data"
        data_out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / "data" / "c2k_course.json", data_out / "c2k_course.json")
        shutil.copy2(root / "data" / "c2k_course_bundle.js", data_out / "c2k_course_bundle.js")
        (stage_dir / ".nojekyll").write_text("", encoding="utf-8")

        run_git_local(["init", "-b", "gh-pages"], stage_dir)
        run_git_local(["config", "user.name", login], stage_dir)
        run_git_local(["config", "user.email", DEFAULT_GIT_EMAIL], stage_dir)
        run_git_local(["add", "-A"], stage_dir)
        run_git_local(["commit", "-m", message], stage_dir)
        run_git_local(["remote", "add", "origin", REMOTE_URL], stage_dir)

        try:
            push_res = run_git_network(["push", "--force", "origin", "HEAD:gh-pages"], stage_dir, token)
            if push_res.stderr.strip():
                print(push_res.stderr.strip())
        except RuntimeError as exc:
            if "403" in str(exc) or "Permission to" in str(exc):
                print("Git smart-HTTP used secondary account; deploying gh-pages via GitHub Git Data API ...")
                _deploy_pages_via_api(stage_dir, token, message)
            else:
                raise
    finally:
        _safe_rmtree(stage_dir)

    try:
        _, pages_info = github_api_request("GET", f"/repos/{FULL_REPO}/pages", token)
        src = pages_info.get("source") or {}
        if src.get("branch") != "gh-pages" or src.get("path") != "/":
            github_api_request(
                "PUT",
                f"/repos/{FULL_REPO}/pages",
                token,
                {"source": {"branch": "gh-pages", "path": "/"}},
            )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            github_api_request(
                "POST",
                f"/repos/{FULL_REPO}/pages",
                token,
                {"source": {"branch": "gh-pages", "path": "/"}},
            )
        else:
            raise

    pages_url = f"https://{login.lower()}.github.io/{REPO_NAME}/"
    print("==========================================")
    print(f"GITHUB_PAGES_URL: {pages_url}")
    print("==========================================")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Coast2Kosci, sync full workspace to GitHub main, and deploy clean web bundle to gh-pages."
    )
    parser.add_argument(
        "-m",
        "--message",
        default="Update Coast to Kosciuszko 3D Live Broadcast Tracker",
        help="Commit message for main and gh-pages deploys.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run verify_map_app.py, secret scan, and GitHub auth check without committing or pushing.",
    )
    parser.add_argument(
        "--pages-only",
        action="store_true",
        help="Deploy clean static bundle to gh-pages without committing/pushing main.",
    )
    parser.add_argument(
        "--force-main",
        action="store_true",
        help="Force-push HEAD to origin/main (only for initial orphan history alignment).",
    )
    args = parser.parse_args()

    if "\u2013" in args.message or "\u2014" in args.message:
        raise ValueError("Commit message contains forbidden Unicode en/em dash; use ' - ' instead.")

    root = Path(__file__).resolve().parent.parent

    run_verify(root)
    run_secret_guard(root)

    print("[3/5] Resolving and verifying GitHub authentication ...")
    token, user_hint, auth_source = resolve_github_auth(root)
    _, user_info = github_api_request("GET", "/user", token)
    login = str(user_info.get("login") or user_hint or REPO_OWNER).strip()
    print(f"Authenticated as GitHub user: {login} (via {auth_source})")

    if args.dry_run:
        print("DRY_RUN_OK: Verification, secret guard, and GitHub API authentication all passed.")
        return 0

    if not args.pages_only:
        sync_main_branch(root, token, login, args.message, args.force_main)
    else:
        print("[4/5] Skipping origin/main sync (--pages-only enabled).")

    deploy_gh_pages(root, token, login, args.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
