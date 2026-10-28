# -*- coding: utf-8 -*-
"""商业版入口：先校验注册码，激活成功后启动主界面。"""
from license_guard import run_activation


def main():
    if not run_activation():
        return
    from backup_gui import main as run_gui
    run_gui()


if __name__ == "__main__":
    main()
