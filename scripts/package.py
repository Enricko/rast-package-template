#!/usr/bin/env python3
"""Generate, validate and smoke-test a RAST package release.

  manifest       write rast-package.json for a release tag from built archives
  validate       check rast-package.json with RAST's rules (and local archives)
  smoke          extract an archive like RAST does and run the manifest checks
  check-release  after publishing: cross-check the GitHub release exactly as
                 RAST's "Install from GitHub" does before it shows a preview

Standard library only. Rules: scripts/rastpkg.py (port of RAST's validator).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rastpkg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = "rast-package.json"
UA = "rast-package-template/1"
TAG = re.compile(r"^v(?P<version>[0-9][0-9A-Za-z.+-]*)-(?P<revision>[1-9][0-9]*)$")


def load_package() -> dict:
    return json.loads((ROOT / "package.json").read_text())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_tag(tag: str) -> tuple[str, int]:
    m = TAG.match(tag)
    if not m:
        raise SystemExit(f"release tag {tag!r} must look like v<version>-<revision>, e.g. v5.4.9-1")
    return m.group("version"), int(m.group("revision"))


def run_url() -> str | None:
    if os.environ.get("GITHUB_RUN_ID"):
        return f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    return None


def cmd_manifest(args):
    pkg = load_package()
    version, revision = parse_tag(args.tag)
    if version != pkg["source"]["version"]:
        raise SystemExit(f"tag version {version} does not match package.json source.version {pkg['source']['version']}")
    m = json.loads(json.dumps(pkg["manifest"]).replace("{version}", version))
    m["version"] = version
    m["revision"] = revision
    attest = dict(a.split("=", 1) for a in args.attestation)
    artifacts = []
    for target in sorted(pkg["targets"]):
        name = f"{m['id']}-{version}-{target}.tar.gz"
        path = Path(args.dist) / name
        if not path.exists():
            if args.allow_missing:
                continue
            raise SystemExit(f"missing archive {path}")
        prov = {
            "kind": "built",
            "source": pkg["source"]["url"],
            "sourceSha256": pkg["source"]["sha256"],
            "verification": "Source SHA-256 checked before building; binaries built and executed on a native runner in GitHub Actions",
        }
        if run_url():
            prov["buildUrl"] = run_url()
        if attest.get(target):
            prov["attestationUrl"] = attest[target]
        artifacts.append({
            "target": target,
            "url": f"https://github.com/{args.repo}/releases/download/{args.tag}/{name}",
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "format": "tar.gz",
            "stripComponents": 1,
            "provenance": prov,
        })
    m["artifacts"] = artifacts
    rastpkg.validate_manifest(m)
    Path(args.out).write_text(json.dumps(m, indent=2) + "\n")
    print(f"wrote {args.out}: {m['id']} {version} revision {revision}, targets {[a['target'] for a in artifacts]}")


def cmd_validate(args):
    raw = Path(args.manifest).read_bytes()
    if len(raw) > rastpkg.MAX_MANIFEST_BYTES:
        raise SystemExit("manifest is larger than 64 KiB")
    m = json.loads(raw)
    try:
        rastpkg.validate_manifest(m)
    except rastpkg.Invalid as e:
        raise SystemExit(f"invalid manifest: {e}")
    if args.dist:
        for a in m["artifacts"]:
            path = Path(args.dist) / a["url"].rsplit("/", 1)[-1]
            if sha256_file(path) != a["sha256"] or path.stat().st_size != a["size"]:
                raise SystemExit(f"{path.name} does not match the manifest")
    print(f"{args.manifest}: valid ({m['id']} {m['version']} rev {m['revision']})")


def safe_extract(archive: Path, dest: Path, strip: int) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            parts = [p for p in member.name.split("/") if p not in ("", ".")]
            if member.name.startswith("/") or ".." in parts:
                raise SystemExit(f"unsafe path in archive: {member.name}")
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise SystemExit(f"unsupported entry type: {member.name}")
            if len(parts) <= strip:
                continue
            member.name = "/".join(parts[strip:])
            tar.extract(member, dest, filter="tar")


def cmd_smoke(args):
    pkg = load_package()
    version = pkg["source"]["version"]
    m = json.loads(json.dumps(pkg["manifest"]).replace("{version}", version))
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "root"
        home = Path(d) / "home"
        root.mkdir()
        home.mkdir()
        safe_extract(Path(args.archive), root, 1)
        exes = {e["name"]: e["path"] for e in m["runtime"]["executables"]}
        for name, rel in exes.items():
            p = root / rel
            if not (p.is_file() and os.access(p, os.X_OK)):
                raise SystemExit(f"executable {name} ({rel}) is missing")
        env = {"PATH": f"{root}/bin:/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home), "LANG": "C.UTF-8"}
        for check in m["runtime"]["checks"]:
            out = subprocess.run([str(root / exes[check["executable"]]), *check.get("args", [])], env=env, cwd=home,
                                 capture_output=True, text=True, timeout=60)
            text = (out.stdout + out.stderr).strip()
            if out.returncode != 0 or check["expect"] not in text:
                raise SystemExit(f"check {check['executable']} failed: exit {out.returncode}, output {text[:200]!r}")
            print(f"ok: {check['executable']} {' '.join(check.get('args', []))} -> {text.splitlines()[0]}")


def github(path: str):
    req = urllib.request.Request(f"https://api.github.com{path}", headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def cmd_check_release(args):
    rel = github(f"/repos/{args.repo}/releases/tags/{args.tag}")
    if rel.get("draft"):
        raise SystemExit("release is a draft")
    assets = {a["name"]: a for a in rel["assets"]}
    man = assets.get(MANIFEST_FILE)
    if not man:
        raise SystemExit(f"release {args.tag} has no {MANIFEST_FILE} asset")
    with urllib.request.urlopen(urllib.request.Request(man["browser_download_url"], headers={"User-Agent": UA}), timeout=60) as r:
        raw = r.read()
    digest = (man.get("digest") or "").removeprefix("sha256:")
    if digest and digest != hashlib.sha256(raw).hexdigest():
        raise SystemExit("manifest asset digest mismatch")
    m = rastpkg.validate_manifest(json.loads(raw))
    by_url = {a["browser_download_url"]: a for a in rel["assets"]}
    for art in m["artifacts"]:
        asset = by_url.get(art["url"])
        if not asset:
            raise SystemExit(f"{art['target']}: {art['url']} is not an asset of this release")
        if asset["size"] != art["size"]:
            raise SystemExit(f"{art['target']}: size {asset['size']} != manifest {art['size']}")
        d = (asset.get("digest") or "").removeprefix("sha256:")
        if not d:
            print(f"warning: GitHub reports no digest for {asset['name']}")
        elif d != art["sha256"]:
            raise SystemExit(f"{art['target']}: GitHub digest {d} != manifest {art['sha256']}")
        print(f"ok: {art['target']} {asset['name']} sha256 {art['sha256'][:12]}… matches the release asset")
    print(f"{args.repo}@{args.tag}: {m['id']} {m['version']} is importable")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("manifest")
    p.add_argument("--tag", required=True)
    p.add_argument("--repo", required=True, help="owner/name")
    p.add_argument("--dist", default="dist")
    p.add_argument("--attestation", action="append", default=[], help="target=url")
    p.add_argument("--allow-missing", action="store_true", help="skip targets without an archive")
    p.add_argument("--out", default=MANIFEST_FILE)
    p.set_defaults(fn=cmd_manifest)
    p = sub.add_parser("validate")
    p.add_argument("manifest", nargs="?", default=MANIFEST_FILE)
    p.add_argument("--dist")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("smoke")
    p.add_argument("archive")
    p.set_defaults(fn=cmd_smoke)
    p = sub.add_parser("check-release")
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    p.set_defaults(fn=cmd_check_release)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
