# -*- coding: utf-8 -*-
"""本地测试用：取消本机注册，方便反复测试激活流程。

会被注册机 exe 内置的“取消本机注册”按钮复用，也可单独运行。

只会：
  1. 删除本机 %APPDATA%\\swCfgBackup\\license.dat；
  2. 可选地从本地签发记录中删除本机机器码对应的记录。

不会吊销已经发给客户的注册码，也不会修改私钥或软件本身。

用法：
  python license_tools/reset_local_license.py
  python license_tools/reset_local_license.py --keep-ledger   # 只删注册码文件
  python license_tools/reset_local_license.py --dry-run       # 只看会删什么
  python license_tools/reset_local_license.py --ledger D:\\path\\issued.csv
"""
import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from license_guard import (  # noqa: E402
    LICENSE_PATH, machine_code, normalize_machine_code,
)

DEFAULT_LEDGERS = [
    BASE / "license_tools" / "issued.csv",   # 命令行注册机
    BASE / "dist" / "issued.csv",            # 图形注册机（dist 目录）
]


def clean_ledger(path: Path, machine: str, dry_run: bool) -> int:
    if not path.is_file():
        return 0
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            rows = list(reader)
    except Exception:
        return 0
    if not fields:
        return 0
    keep = [r for r in rows
            if normalize_machine_code(r.get("machine", "")) != machine]
    removed = len(rows) - len(keep)
    if removed and not dry_run:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(keep)
        os.replace(tmp, path)
    return removed


def reset_local(keep_ledger: bool = False, dry_run: bool = False,
                extra_ledgers: Optional[Iterable] = None,
                license_path: Optional[Path] = None,
                ledgers: Optional[Iterable] = None) -> Dict:
    """执行取消注册，返回结果字典（不打印）。"""
    license_file = Path(license_path) if license_path else LICENSE_PATH
    mc = machine_code()
    result = {
        "machine": mc,
        "license_path": str(license_file),
        "deleted": [],
        "failed": [],
        "ledger_removed": {},
        "dry_run": dry_run,
        "skipped_ledger": keep_ledger,
    }

    for path in (license_file, license_file.with_suffix(".tmp")):
        if not path.exists():
            continue
        if dry_run:
            result["deleted"].append(str(path))
            continue
        try:
            path.unlink()
            result["deleted"].append(str(path))
        except Exception as exc:
            result["failed"].append((str(path), str(exc)))

    if not keep_ledger:
        paths: List[Path] = list(DEFAULT_LEDGERS if ledgers is None else ledgers)
        if extra_ledgers:
            paths += [Path(p) for p in extra_ledgers]
        seen = set()
        for ledger in paths:
            try:
                key = str(Path(ledger).resolve()).lower()
            except Exception:
                key = str(ledger).lower()
            if key in seen:
                continue
            seen.add(key)
            removed = clean_ledger(
                Path(ledger), normalize_machine_code(mc), dry_run)
            if removed:
                result["ledger_removed"][str(ledger)] = removed

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="取消本机注册（本地测试）")
    parser.add_argument("--keep-ledger", action="store_true",
                        help="只删除注册码文件，不清除签发记录")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示会删除什么，不实际删除")
    parser.add_argument("--ledger", action="append", default=[],
                        help="额外的签发记录 CSV 路径（可多次）")
    args = parser.parse_args()

    result = reset_local(
        keep_ledger=args.keep_ledger,
        dry_run=args.dry_run,
        extra_ledgers=args.ledger,
    )

    print(f"本机机器码: {result['machine']}")
    print(f"注册码文件: {result['license_path']}")
    if result["deleted"]:
        for path in result["deleted"]:
            print(f"  {'将删除' if args.dry_run else '删除'}: {path}")
    else:
        print("  本机没有注册码文件")
    for path, err in result["failed"]:
        print(f"  删除失败: {path} ({err})")
    if args.keep_ledger:
        print("已跳过签发记录清理（--keep-ledger）")
    else:
        for path, count in result["ledger_removed"].items():
            print(f"  {'将清理' if args.dry_run else '清理'} {count} 条本机签发记录: {path}")
    print()
    if args.dry_run:
        print("dry-run 完成，未修改任何文件。")
    else:
        print("本机注册已取消。")
        print("下一步：运行 swCfgBackupS.exe 获取机器码，"
              "再用注册机生成新的注册码并激活。")


if __name__ == "__main__":
    main()
