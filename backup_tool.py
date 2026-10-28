# -*- coding: utf-8 -*-
"""
交换机配置备份工具 — 独立发布版
用法：
  备份配置（使用设备清单）：
    python backup_tool.py --inventory pw.xlsx
    python backup_tool.py --inventory pw.xlsx --backup-dir D:\\配置备份\\

  生成 Excel 模板（首次使用）：
    python backup_tool.py --create-template

支持的设备：华为 VRP、H3C Comware
"""

import argparse
import os
import sys
from datetime import datetime

from utils import check_dependencies
check_dependencies()

from collector import SSHCollector
from backup    import run_backup
from inventory import load_from_excel, create_excel_template


def main():
    parser = argparse.ArgumentParser(
        description="交换机配置备份工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python backup_tool.py --inventory pw.xlsx              # 备份所有设备配置
  python backup_tool.py --inventory pw.xlsx --backup-dir D:\\backup  # 指定备份目录
  python backup_tool.py --create-template                # 生成Excel模板
        """
    )

    # 设备来源
    parser.add_argument("--inventory", "-i", metavar="FILE.xlsx",
                        help="Excel 设备清单路径（必填，除非使用 --create-template）")

    # Excel 选项
    parser.add_argument("--sheet",    metavar="SHEET",   help="指定 Excel Sheet 名")
    parser.add_argument("--username", metavar="USER",    help="默认用户名（覆盖 Excel 空值）")
    parser.add_argument("--password", metavar="PASS",    help="默认密码（覆盖 Excel 空值）")

    # 备份选项
    parser.add_argument("--backup-dir", metavar="DIR", default="backup",
                        help="备份文件存储目录（默认 backup/）")
    parser.add_argument("--keep-count", "--keep-min", dest="keep_count",
                        type=int, default=1,
                        help="每设备保留的备份份数（默认 1；--keep-min 为兼容别名）")
    parser.add_argument("--no-retry-failed", action="store_true",
                        help="禁用失败设备自动补采")
    parser.add_argument("--retry-delay", type=int, default=30,
                        help="失败补采前等待秒数（默认 30）")
    parser.add_argument("--retry-auth", action="store_true",
                        help="认证失败也补采一次（注意锁号风险）")
    parser.add_argument("--no-write-back", action="store_true",
                        help="不回填主机名到 Excel 清单")
    parser.add_argument("--concurrency", "-j", type=int, default=3,
                        help="并发线程数（默认 3）")

    # 工具命令
    parser.add_argument("--create-template", action="store_true",
                        help="生成 Excel 设备清单模板文件")

    args = parser.parse_args()

    # ---------- 生成模板 ----------
    if args.create_template:
        tpl_path = "devices_template.xlsx"
        create_excel_template(tpl_path)
        print(f"\n  请用 Excel 打开 {tpl_path}，填写设备信息后运行：")
        print(f"  python backup_tool.py --inventory {tpl_path}\n")
        return

    # ---------- 参数校验 ----------
    if not args.inventory:
        print("[错误] 请指定设备清单：--inventory pw.xlsx")
        print("       首次使用请先生成模板：python backup_tool.py --create-template")
        sys.exit(1)

    if not os.path.exists(args.inventory):
        print(f"[错误] Excel 文件不存在: {args.inventory}")
        sys.exit(1)

    # ---------- 加载设备清单 ----------
    print(f"\n  [配置来源] Excel 文件: {args.inventory}")
    devices = load_from_excel(
        args.inventory,
        sheet_name=args.sheet or None,
        default_username=args.username or "admin",
        default_password=args.password or "",
    )

    if not devices:
        print("[错误] 未读取到任何设备，请检查 Excel 文件")
        sys.exit(1)

    # ---------- 执行备份 ----------
    results = run_backup(
        devices=devices,
        backup_dir=args.backup_dir,
        concurrency=args.concurrency,
        keep_count=args.keep_count,
        retry_failed=not args.no_retry_failed,
        retry_delay=args.retry_delay,
        retry_auth=args.retry_auth,
        inventory_path=args.inventory,
        sheet_name=args.sheet or None,
        write_back=not args.no_write_back,
        cache_dir="",
        cache_ttl=0,
    )

    # 有失败设备时返回非 0，便于任务计划程序/监控判断
    failed = [r for r in results
              if not str(r.get("status", "")).startswith("success")]
    if failed:
        ips = ", ".join(r.get("ip", "?") for r in failed[:10])
        if len(failed) > 10:
            ips += " ..."
        print(f"  [退出码 1] 失败 {len(failed)} 台: {ips}")
        sys.exit(1)


if __name__ == "__main__":
    main()
