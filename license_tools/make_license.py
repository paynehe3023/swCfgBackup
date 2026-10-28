# -*- coding: utf-8 -*-
"""注册码生成器（仅供应商本地使用）。

重要：
  - private_key.pem 是签发注册码的唯一私钥，绝不能提交到 Git 或随软件分发；
  - 私钥丢失后，已签发的注册码仍然有效，但无法再签发新码；
  - 私钥泄露后，任何人都能生成有效注册码。

命令行用法：
  python license_tools/make_license.py --init-keys
  python license_tools/make_license.py --machine "ABCDE-FGHIJ-KLMNO-PQRST-UVWXY-Z" \
      --customer "某某公司" --out license_tools/out/customer.key
  python license_tools/make_license.py --list

图形注册机入口见 license_tools/generator_gui.py（打包为 swCfgBackupS-注册机.exe）。
"""
import argparse
import base64
import csv
import hashlib
import json
import os
import sys
import textwrap
import uuid
import zlib
from datetime import date, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from license_guard import (  # noqa: E402
    LICENSE_PREFIX, LICENSE_VERSION, PRODUCT, normalize_machine_code,
)

KEY_PATH = BASE / "license_tools" / "private_key.pem"
PUBLIC_KEY_PATH = BASE / "license_tools" / "public_key.txt"
LEDGER_PATH = BASE / "license_tools" / "issued.csv"


class IssueError(Exception):
    """注册码签发失败（可直接显示给供应商）"""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def init_keys(force: bool = False) -> None:
    if KEY_PATH.exists() and not force:
        raise IssueError(
            f"私钥已存在：{KEY_PATH}\n如需重新生成请加 --force（已签发的旧注册码仍可用）")
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_bytes(pem)
    try:
        os.chmod(KEY_PATH, 0o600)
    except Exception:
        pass
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public_b64 = base64.b64encode(public).decode("ascii")
    PUBLIC_KEY_PATH.write_text(public_b64 + "\n", encoding="utf-8")
    print(f"私钥已生成：{KEY_PATH}")
    print("公钥（应写入 license_guard.py 的 PUBLIC_KEY_B64）：")
    print(public_b64)
    print("请立即备份私钥；不要提交到 Git，不要发给用户。")


def load_private_key(path: Path = None) -> Ed25519PrivateKey:
    key_path = Path(path) if path else KEY_PATH
    if not key_path.is_file():
        raise IssueError(
            f"找不到私钥：{key_path}\n请放入备份的私钥，或在注册机里选择私钥文件")
    try:
        return serialization.load_pem_private_key(
            key_path.read_bytes(), password=None)
    except Exception as exc:
        raise IssueError(f"私钥读取失败：{exc}")


def _ledger_rows(ledger_path: Path = None):
    path = Path(ledger_path) if ledger_path else LEDGER_PATH
    if not path.is_file():
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _append_ledger(row: dict, ledger_path: Path = None) -> None:
    path = Path(ledger_path) if ledger_path else LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def generate_license(machine: str, customer: str = "", expires: str = "",
                     private_key_path=None, ledger_path=None,
                     force: bool = False) -> dict:
    """签发注册码；失败抛 IssueError，成功返回结果字典（不打印）。"""
    machine = normalize_machine_code(machine)
    if not machine or not machine.isalnum() or not (16 <= len(machine) <= 64):
        raise IssueError("机器码格式不正确（请从激活窗口复制）")

    expires = (expires or "").strip()
    if expires:
        try:
            datetime.strptime(expires, "%Y-%m-%d")
        except ValueError:
            raise IssueError("到期日期格式应为 YYYY-MM-DD")

    rows = _ledger_rows(ledger_path)
    previous = [r for r in rows
                if normalize_machine_code(r.get("machine", "")) == machine]
    if previous and not force:
        raise IssueError(
            f"该机器码已签发过 {len(previous)} 个注册码；如需重发请勾选/使用 --force")

    private = load_private_key(private_key_path)
    license_id = uuid.uuid4().hex
    payload = {
        "p": PRODUCT,
        "v": LICENSE_VERSION,
        "m": machine,
        "c": (customer or "").strip(),
        "i": date.today().isoformat(),
        "x": expires,
        "id": license_id,
    }
    raw = json.dumps(payload, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(raw, 9)
    signature = private.sign(compressed)
    code = f"{LICENSE_PREFIX}.{_b64e(compressed)}.{_b64e(signature)}"

    _append_ledger({
        "issued_at": date.today().isoformat(),
        "machine": machine,
        "customer": payload["c"],
        "expires": expires,
        "license_id": license_id,
        "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "code": code,
    }, ledger_path)

    return {
        "code": code,
        "payload": payload,
        "machine": machine,
        "expires": expires,
        "license_id": license_id,
    }


def print_license(result: dict) -> None:
    payload = result["payload"]
    code = result["code"]
    print("=" * 72)
    print(f"机器码 : {result['machine']}")
    print(f"客户   : {payload['c'] or '-'}")
    print(f"签发日 : {payload['i']}")
    print(f"到期日 : {result['expires'] or '永久'}")
    print(f"授权ID : {result['license_id']}")
    print("-" * 72)
    print("注册码（整段复制给用户）：")
    print(textwrap.fill(code, 76))
    print("=" * 72)


def issue(args) -> str:
    result = generate_license(
        args.machine,
        customer=args.customer or "",
        expires=args.expires or "",
        private_key_path=args.key or KEY_PATH,
        ledger_path=LEDGER_PATH,
        force=args.force,
    )
    print_license(result)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result["code"] + "\n", encoding="utf-8")
        print(f"已保存到：{out}")
    print(f"已追加签发记录：{LEDGER_PATH}")
    return result["code"]


def list_ledger() -> None:
    rows = _ledger_rows()
    if not rows:
        print("暂无签发记录")
        return
    for r in rows:
        print(f"{r.get('issued_at', '')}  {r.get('machine', '')}  "
              f"{r.get('customer', '') or '-'}  "
              f"到期:{r.get('expires', '') or '永久'}  "
              f"ID:{r.get('license_id', '')[:8]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="网络设备配置备份 注册码生成器")
    parser.add_argument("--init-keys", action="store_true",
                        help="生成 Ed25519 密钥对（私钥不提交）")
    parser.add_argument("--force", action="store_true",
                        help="允许覆盖私钥 / 对同一机器码重发")
    parser.add_argument("--machine", help="用户机器码（激活窗口复制）")
    parser.add_argument("--customer", default="", help="客户名称/备注")
    parser.add_argument("--expires", default="", help="到期日 YYYY-MM-DD（留空=永久）")
    parser.add_argument("--key", help="私钥路径（默认 license_tools/private_key.pem）")
    parser.add_argument("--out", help="把注册码保存到文件")
    parser.add_argument("--list", action="store_true", help="查看已签发记录")
    args = parser.parse_args()

    try:
        if args.init_keys:
            init_keys(args.force)
            return
        if args.list:
            list_ledger()
            return
        if not args.machine:
            parser.error("请提供 --machine，或使用 --init-keys / --list")
        issue(args)
    except IssueError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
