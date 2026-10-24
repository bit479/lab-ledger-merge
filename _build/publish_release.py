# -*- coding: utf-8 -*-
"""发 Release 并上传 exe。

用法：
    python _build/publish_release.py --tag v1.0

⚠ 不用 `gh release create`：它创建后要 PATCH 一次 releases/<id>，
   这条连接在本机会被 `wsarecv ... forcibly closed` 掐断，gh 会把已建的 release
   回滚删除，最终报 "release not found"。这里只做 POST 创建 + 上传资产，不碰 PATCH。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "bit479/lab-ledger-merge"
DIST = os.path.join(BASE, "dist")
EXE_NAME = "化验数据并入台账.exe"


def gh_token() -> str:
    out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit("✗ 拿不到 gh token，先 gh auth login")
    return out.stdout.strip()


def api(method: str, url: str, token: str, payload: dict | None = None,
        raw: bytes | None = None, content_type: str = "application/json"):
    data = raw if raw is not None else (json.dumps(payload).encode() if payload else None)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", content_type)
    req.add_header("User-Agent", "lab-ledger-merge-release")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", "replace")}


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="v1.0")
    p.add_argument("--title", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--draft", action="store_true")
    # 资产名必须 ASCII：GitHub 对中文文件名会回落成 default.exe
    p.add_argument("--asset-name", default="LabLedgerMerge.exe")
    args = p.parse_args()

    exe = os.path.join(DIST, EXE_NAME)
    if not os.path.exists(exe):
        print(f"✗ 找不到 exe：{exe}\n  先跑 python _build/build_exe.py")
        return 2

    token = gh_token()
    title = args.title or f"{args.tag} —— 化验数据并入样品台账"
    notes = args.notes or (
        f"首个版本。\n\n"
        f"- 资产 `{args.asset_name}`（{os.path.getsize(exe) / 1048576:.1f} MB），"
        f"下载后改名为 `化验数据并入台账.exe` 即可双击运行\n"
        f"- MD5 `{md5(exe)}`\n"
    )

    # 已有同 tag 的 release 就复用，不重复创建（重复 POST 会 422）
    status, body = api("GET", f"https://api.github.com/repos/{REPO}/releases/tags/{args.tag}",
                       token)
    if status == 200:
        release_id = body["id"]
        upload_url = body["upload_url"].split("{")[0]
        print(f"复用已有 release {args.tag}（id={release_id}）")
    else:
        print(f"创建 release {args.tag} …")
        status, body = api("POST", f"https://api.github.com/repos/{REPO}/releases", token, {
            "tag_name": args.tag,
            "name": title,
            "body": notes,
            "draft": args.draft,
            "prerelease": False,
        })
        if status not in (200, 201):
            print(f"✗ 创建失败 HTTP {status}: {body}")
            return 3
        release_id = body["id"]
        upload_url = body["upload_url"].split("{")[0]
        print(f"  release id={release_id}")

    print(f"上传 {args.asset_name} …")
    with open(exe, "rb") as fh:
        data = fh.read()
    status, body = api(
        "POST",
        f"{upload_url}?name={urllib.parse.quote(args.asset_name)}",
        token, raw=data, content_type="application/octet-stream",
    )
    if status not in (200, 201):
        print(f"✗ 上传失败 HTTP {status}: {body}")
        return 4

    size = body.get("size", 0) / 1048576
    print(f"  ✓ 已上传 {size:.1f} MB，资产 id={body.get('id')}")
    print(f"\nRelease: https://github.com/{REPO}/releases/tag/{args.tag}")
    print(f"MD5: {md5(exe)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
