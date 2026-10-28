# -*- coding: utf-8 -*-
"""
网络设备信息采集核心模块
支持：华为 VRP、H3C Comware
接入方式：SSH2 (Paramiko)

【安全声明 - 只读模式】
本模块严格遵守只读原则：
1. 命令白名单机制：所有发送到设备的命令必须在 READONLY_COMMANDS 白名单中
2. 禁止任何配置命令：不发送 system-view / undo / no / delete / reset 等写操作
3. SSH 使用 invoke_shell 交互模式，不使用 exec_command 执行任意命令
4. 不写入任何设备配置，不修改任何设备状态
"""

import sys
import json
import time
import re
import socket
import logging
import paramiko
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, fields, MISSING as DATACLASS_MISSING
from typing import Optional

from utils import fix_console_encoding
fix_console_encoding()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(stream=sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  【只读命令白名单】只有列表中的命令前缀才允许发送到设备               #
#  任何不在白名单中的命令都会被拦截并记录日志，绝不发送                 #
# ------------------------------------------------------------------ #
READONLY_COMMANDS = {
    # 通用查询
    "display ",
    "screen-length",         # 仅用于关闭分页，不修改配置
    # 华为备份专用
    "display current-configuration",
    "display saved-configuration",
    "display startup",
    # H3C 别名（display 已覆盖，此处备用）
    "more ",
}

# 明确禁止的危险命令前缀（双重保险）
FORBIDDEN_PREFIXES = (
    "system-view", "sysname", "interface ", "ip address",
    "undo ", "no ", "delete ", "reset ", "reboot",
    "save", "tftp", "ftp", "sftp", "scp",
    "acl ", "nat ", "ospf", "bgp ", "isis",
    "snmp-agent community write",
)


def _check_readonly(cmd: str) -> bool:
    """
    校验命令是否属于只读白名单。
    返回 True = 允许发送；False = 拦截。
    """
    cmd_lower = cmd.strip().lower()
    # 先检查是否触碰禁止前缀
    for forbidden in FORBIDDEN_PREFIXES:
        if cmd_lower.startswith(forbidden):
            logger.error(f"[安全拦截] 命令被禁止(写操作): {cmd!r}")
            return False
    # 再检查是否在白名单中
    for allowed in READONLY_COMMANDS:
        if cmd_lower.startswith(allowed.lower()):
            return True
    logger.warning(f"[安全拦截] 命令不在白名单中: {cmd!r}")
    return False


@dataclass
class Interface:
    name: str
    ip: str = ""
    mask: str = ""
    status: str = ""
    protocol: str = ""
    description: str = ""
    speed: str = ""
    duplex: str = ""
    mac: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "Interface":
        kwargs = {}
        for f in fields(cls):
            if f.name in d:
                kwargs[f.name] = d[f.name]
            elif f.default is not DATACLASS_MISSING:
                kwargs[f.name] = f.default
            elif f.default_factory is not DATACLASS_MISSING:
                kwargs[f.name] = f.default_factory()
        return cls(**kwargs)


@dataclass
class DeviceInfo:
    ip: str
    sysname: str = ""           # 设备名，来自 display sysname（语义精确）
    vendor: str = ""             # huawei / h3c
    model: str = ""
    uptime: str = ""
    serial: str = ""
    cpu_usage: str = ""
    mem_usage: str = ""
    interfaces: list = field(default_factory=list)
    neighbors: list = field(default_factory=list)   # LLDP/CDP 邻居
    routes: list = field(default_factory=list)      # 路由摘要
    vlans: list = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            **{f.name: getattr(self, f.name) for f in fields(self)},
            "interfaces": [i.to_dict() if hasattr(i, "to_dict") else i for i in self.interfaces],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceInfo":
        """
        从字典重建 DeviceInfo。
        兼容旧缓存：如果旧缓存有 'hostname' 字段但没有 'sysname'，
        自动迁移 hostname → sysname，保证旧缓存平滑升级。
        """
        # 缓存兼容：如果旧缓存有 hostname 但没有 sysname，取 hostname
        if "hostname" in d and "sysname" not in d:
            d["sysname"] = d["hostname"]
        # 清理华为设备 sysname 中可能残留的尖括号（如 <wuliu_2loudong1> → wuliu_2loudong1）
        if d.get("sysname"):
            d["sysname"] = str(d["sysname"]).strip("<>")
        kwargs = {}
        for f in fields(cls):
            if f.name in d:
                kwargs[f.name] = d[f.name]
            elif f.default is not DATACLASS_MISSING:
                kwargs[f.name] = f.default
            elif f.default_factory is not DATACLASS_MISSING:
                kwargs[f.name] = f.default_factory()
        if "interfaces" in d:
            kwargs["interfaces"] = [
                Interface.from_dict(i) if isinstance(i, dict) else i
                for i in d["interfaces"]
            ]
        return cls(**kwargs)


class SSHCollector:
    """SSH 采集器（华为 / H3C 通用）"""

    TIMEOUT = 15
    RECV_WAIT = 2
    MAX_RETRY = 2          # 最大重试次数
    RETRY_DELAY = 3        # 重试间隔秒数

    # 分页提示符（华为/H3C 常见两种写法）
    _MORE_RE = re.compile(rb"(?:-{2,}\s*More\s*-{2,}|--More--)", re.I)

    def __init__(self, ip: str, username: str, password: str,
                 port: int = 22, vendor: str = "auto",
                 cache_dir: str = "", cache_ttl: int = 0):
        """
        cache_dir: 本地缓存目录，设为空则不使用缓存。
        cache_ttl:  缓存有效期（小时），<=0 则无限期（永不过期）。
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.vendor = vendor   # auto / huawei / h3c
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl   # 小时
        self._client: Optional[paramiko.SSHClient] = None
        self._shell = None
        self.connect_error: str = ""   # 供外部读取最终错误原因

    # ------------------------------------------------------------------ #
    #  缓存读写                                                             #
    # ------------------------------------------------------------------ #
    def _cache_path(self) -> Path:
        """缓存文件路径：{cache_dir}/{ip}.json"""
        return Path(self.cache_dir) / f"{self.ip}.json"

    def _load_cache(self) -> Optional[DeviceInfo]:
        """
        读取本地缓存，若缓存不存在或已过期则返回 None。
        """
        if not self.cache_dir:
            return None
        p = self._cache_path()
        if not p.exists():
            return None
        try:
            with open(str(p), "r", encoding="utf-8") as f:
                data = json.load(f)
            # 检查 TTL
            if self.cache_ttl > 0:
                cached_at = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
                age_hours = (datetime.now() - cached_at).total_seconds() / 3600
                if age_hours > self.cache_ttl:
                    logger.info(f"[{self.ip}] 缓存已过期({age_hours:.1f}h > {self.cache_ttl}h)，重新采集")
                    return None
            info = DeviceInfo.from_dict(data)
            info.error = ""   # 缓存命中时视为成功
            logger.info(f"[{self.ip}] 使用本地缓存（{p.name}），跳过 SSH 连接")
            return info
        except Exception as e:
            logger.warning(f"[{self.ip}] 读取缓存失败: {e}，重新采集")
            return None

    def _save_cache(self, info: DeviceInfo):
        """
        将采集结果写入本地缓存文件（含时间戳）。
        """
        if not self.cache_dir:
            return
        try:
            p = self._cache_path()
            Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
            data = info.to_dict()
            data["_cached_at"] = datetime.now().isoformat()
            data["_sysname"] = info.sysname   # 方便人工查看缓存文件
            with open(str(p), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[{self.ip}] 缓存已保存: {p.name}")
        except Exception as e:
            logger.warning(f"[{self.ip}] 保存缓存失败: {e}")

    # ------------------------------------------------------------------ #
    #  连接 / 断开（含分类异常处理 + 重试）                                 #
    # ------------------------------------------------------------------ #
    def connect(self) -> bool:
        """
        尝试建立 SSH 连接，最多重试 MAX_RETRY 次。
        对超时、认证失败等场景分类提示，不崩溃。
        返回 True = 连接成功；False = 最终失败。
        """
        for attempt in range(1, self.MAX_RETRY + 2):   # 1次正常 + MAX_RETRY次重试
            try:
                self._client = paramiko.SSHClient()
                self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self._client.connect(
                    self.ip, port=self.port,
                    username=self.username, password=self.password,
                    timeout=self.TIMEOUT,
                    look_for_keys=False, allow_agent=False,
                    # 兼容老款华为/H3C交换机只支持 group1-sha1/group14-sha1 的情况
                    # paramiko 3.x 默认列表里有这些算法，空列表 = 全部启用
                    disabled_algorithms={
                        "kex":         [],
                        "keys":        [],
                        "pubkeys":     [],
                        "ciphers":     [],
                        "macs":        [],
                        "compression": [],
                    }
                )
                self._shell = self._client.invoke_shell(width=200, height=200)
                time.sleep(0.5)
                # 读取并丢弃登录 banner / 初始提示符，避免吞掉后续命令
                self._read_until_idle(idle=1, max_wait=10)
                self.disable_paging()
                self.connect_error = ""
                return True

            except paramiko.AuthenticationException:
                # 认证失败无需重试，直接返回
                self.connect_error = "SSH认证失败（用户名或密码错误）"
                logger.error(f"[{self.ip}] {self.connect_error}")
                return False

            except (socket.timeout, TimeoutError):
                self.connect_error = f"SSH连接超时（{self.TIMEOUT}s）"
                logger.warning(f"[{self.ip}] {self.connect_error}，第{attempt}次")

            except socket.error as e:
                err_msg = str(e)
                transient = (
                    isinstance(e, (ConnectionResetError, ConnectionAbortedError,
                                   BrokenPipeError))
                    or "Connection reset" in err_msg
                    or "10054" in err_msg
                )
                if transient:
                    # 设备/链路瞬时重置：和超时一样进入重试
                    self.connect_error = f"连接被重置: {err_msg}"
                    logger.warning(f"[{self.ip}] {self.connect_error}，第{attempt}次")
                elif "Connection refused" in err_msg:
                    self.connect_error = "SSH端口拒绝连接（端口未开放或服务未启动）"
                    logger.error(f"[{self.ip}] {self.connect_error}")
                    return False
                elif "No route to host" in err_msg or "Network unreachable" in err_msg:
                    self.connect_error = "目标IP不可达（路由不通）"
                    logger.error(f"[{self.ip}] {self.connect_error}")
                    return False
                else:
                    self.connect_error = f"网络错误: {err_msg}"
                    logger.error(f"[{self.ip}] {self.connect_error}")
                    return False   # 未知网络错误，不重试

            except paramiko.SSHException as e:
                err_msg = str(e)
                if "no acceptable host key" in err_msg:
                    self.connect_error = (
                        "SSH协议错误: 客户端与设备的主机密钥算法不兼容"
                        "（设备可能只支持 ssh-rsa，请确认 paramiko 为 3.x）"
                    )
                    logger.error(f"[{self.ip}] {self.connect_error}")
                    return False   # 算法不兼容，重试无意义
                self.connect_error = f"SSH协议错误: {err_msg}"
                logger.warning(f"[{self.ip}] {self.connect_error}，第{attempt}次")

            except Exception as e:
                self.connect_error = f"未知错误: {e}"
                logger.error(f"[{self.ip}] {self.connect_error}")
                return False

            # 重试前关闭旧连接
            try:
                if self._client:
                    self._client.close()
            except Exception:
                pass
            self._client = None
            self._shell = None

            if attempt <= self.MAX_RETRY:
                logger.info(f"[{self.ip}] {self.RETRY_DELAY}s 后重试... ({attempt}/{self.MAX_RETRY})")
                time.sleep(self.RETRY_DELAY)

        logger.error(f"[{self.ip}] 连接最终失败，已重试 {self.MAX_RETRY} 次: {self.connect_error}")
        return False

    def disconnect(self):
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  发送命令                                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _decode_bytes(raw: bytes) -> str:
        """
        智能解码设备返回的字节流。
        华为/H3C 设备 description 等字段通常使用 GBK 编码，
        先尝试 UTF-8，失败则回退 GBK，彻底消除乱码。
        """
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            pass
        # 最后兜底：UTF-8 替换模式（不会再出现 GBK 乱码，只可能有极少数特殊符号丢失）
        return raw.decode("utf-8", errors="replace")

    def _read_until_idle(self, idle: float = 5, max_wait: float = 90,
                         stop_on_prompt: bool = True) -> str:
        """
        读取设备输出，直到看到设备提示符（<HOST> / [HOST]），
        或连续 idle 秒没有新数据（兜底），或到达 max_wait 上限。

        旧实现是固定等待 + 0.3 秒空档即结束，设备输出末尾稍一停顿
        就会把 return / 提示符截掉，产生看似成功的不完整备份。
        遇到分页提示符（---- More ----）时自动发送空格翻页（只读操作）。
        """
        buf = b""
        start = last_data = time.time()
        while time.time() - start < max_wait:
            if self._shell.recv_ready():
                buf += self._shell.recv(65535)
                last_data = time.time()
                continue
            # 分页提示符：发送空格继续，并把提示符从结果中移除
            tail = buf[-300:]
            m = self._MORE_RE.search(tail)
            if m:
                buf = buf[:-300] + tail[:m.start()] + tail[m.end():]
                self._shell.send(" ")
                last_data = time.time()
                time.sleep(0.2)
                continue
            if buf and stop_on_prompt and self._tail_is_prompt(buf):
                break
            if buf and (time.time() - last_data) >= idle:
                break
            time.sleep(0.1)
        return self._decode_bytes(buf)

    @staticmethod
    def _tail_is_prompt(buf: bytes) -> bool:
        """判断缓冲区最后一个非空行是否像设备提示符 <HOST> / [HOST]"""
        if not buf:
            return False
        text = buf[-512:].decode("utf-8", errors="replace")
        text = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text)
        lines = [l.strip() for l in text.replace("\r", "").splitlines() if l.strip()]
        if not lines:
            return False
        return bool(re.match(r"^[<\[][^\s<>\[\]]{1,64}[>\]]$", lines[-1]))

    def send(self, cmd: str, wait: float = None, idle: float = 5,
             max_wait: float = 90) -> str:
        """
        向设备发送命令（强制只读校验），读取到提示符/输出空闲为止。
        wait 参数仅为兼容旧调用保留，不再作为固定等待时间。
        """
        if not self._shell:
            return ""
        # ★ 只读安全门 ★
        if not _check_readonly(cmd):
            return f"[BLOCKED] 命令被安全策略拦截: {cmd}"
        self._shell.send(cmd + "\n")
        return self._read_until_idle(idle=idle, max_wait=max_wait)

    def drain(self, idle: float = 2, max_wait: float = 15) -> str:
        """不发送命令，只把设备尚未输出完的内容读完（用于重试前清理）"""
        if not self._shell:
            return ""
        return self._read_until_idle(idle=idle, max_wait=max_wait)

    def disable_paging(self):
        """关闭分页，防止 --More-- 卡住"""
        if self.vendor in ("huawei", "auto", "unknown", ""):
            self.send("screen-length 0 temporary", idle=2, max_wait=15)
        if self.vendor in ("h3c", "auto", "unknown", ""):
            self.send("screen-length disable", idle=2, max_wait=15)

    # ------------------------------------------------------------------ #
    #  识别厂商                                                             #
    # ------------------------------------------------------------------ #
    def detect_vendor(self) -> str:
        out = self.send("display version", wait=2)
        if re.search(r"Huawei|VRP", out, re.I):
            self.vendor = "huawei"
        elif re.search(r"H3C|Comware", out, re.I):
            self.vendor = "h3c"
        else:
            self.vendor = "unknown"
        return self.vendor

    # ------------------------------------------------------------------ #
    #  华为 VRP 解析                                                        #
    # ------------------------------------------------------------------ #
    def _parse_huawei_version(self, out: str, info: DeviceInfo):
        m = re.search(r"Huawei\s+(\S+)\s+.*?Version\s+([\d.()A-Za-z]+)", out, re.I)
        if m:
            info.model = m.group(1)
        # 仅在 sysname 未获取时才从 display version 提取
        if not info.sysname:
            m2 = re.search(r"HUAWEI\s+(\S.*?)\s+uptime\s+is\s+(.+)", out, re.I)
            if m2:
                info.sysname = m2.group(1).strip()
                info.uptime = m2.group(2).strip()
            else:
                # 尝试其他常见格式
                m2b = re.search(r"^(HUAWEI\s+\S+)", out, re.I | re.M)
                if m2b:
                    info.sysname = m2b.group(1).replace("HUAWEI", "").strip()
        m3 = re.search(r"[Ss]erial[- ][Nn]umber\s*[:\s]+(\S+)", out)
        if m3:
            info.serial = m3.group(1)

    def _parse_huawei_interfaces(self, out: str) -> list:
        interfaces = []
        # 每个接口以 "接口名称 current state" 开头
        blocks = re.split(r"\n(?=\S+\s+current state)", out)
        for block in blocks:
            iface = Interface(name="")
            m = re.match(r"(\S+)\s+current state\s*:\s*(\S+)", block)
            if not m:
                continue
            iface.name = m.group(1)
            iface.status = m.group(2)           # UP / DOWN / Administratively DOWN
            m2 = re.search(r"Line protocol current state\s*:\s*(\S+)", block)
            if m2:
                iface.protocol = m2.group(1)
            m3 = re.search(r"Description[:\s]+(.+)", block)
            if m3:
                iface.description = m3.group(1).strip()
            m4 = re.search(r"Internet Address is\s+([\d.]+)/([\d]+)", block)
            if m4:
                iface.ip = m4.group(1)
                iface.mask = m4.group(2)
            m5 = re.search(r"Hardware address is\s+([\da-fA-F-]+)", block)
            if m5:
                iface.mac = m5.group(1)
            m6 = re.search(r"(\d+)[Mm]b/s", block)
            if m6:
                iface.speed = m6.group(1) + "Mb/s"
            interfaces.append(iface)
        return interfaces

    def _parse_huawei_neighbors(self, out: str) -> list:
        """
        解析华为 VRP 的 LLDP 邻居输出。
        华为实际输出格式示例：
          ---------------LLDP neighbor-information of port 1[GigabitEthernet0/0/1]---------------
          Neighbor index          : 1
          Chassis type            : MAC address
          Chassis ID              : 00e0-fc12-3456
          Port ID type            : Interface name
          Port ID                 : GigabitEthernet0/0/2
          Port description        : GE0/0/2
          System name             : CORE-SW01
          System description      : Huawei VRP...
          ...
        """
        neighbors = []
        # 先把所有分隔符中的本端接口名提取出来
        port_names = re.findall(
            r"-{5,}LLDP neighbor-information of port\s+\d+\[([^\]]+)\]-{5,}", out
        )
        blocks = re.split(r"-{5,}LLDP neighbor-information of port[^\n]*-{5,}", out)
        # blocks[0] 是分隔符之前的无关文本，从 index 1 开始对应 port_names[0]
        for idx, block in enumerate(blocks[1:], 0):
            if not block.strip():
                continue
            nb = {}
            # 本端接口来自分隔符中的端口名
            if idx < len(port_names):
                nb["local_port"] = port_names[idx].strip()
            for line in block.splitlines():
                line = line.strip()
                if re.match(r"System name\s*:", line, re.I):
                    nb["neighbor"] = line.split(":", 1)[1].strip()
                elif re.match(r"Port ID\s*:", line, re.I):
                    nb["remote_port"] = line.split(":", 1)[1].strip()
                elif re.match(r"Port description\s*:", line, re.I) and "remote_port" not in nb:
                    nb["remote_port"] = line.split(":", 1)[1].strip()
            if nb.get("neighbor"):
                neighbors.append(nb)

        # 若块切分失败（某些旧固件格式），降级为逐条匹配
        if not neighbors:
            neighbors = self._parse_lldp_fallback(out)

        return neighbors

    def _parse_h3c_neighbors(self, out: str) -> list:
        """
        解析 H3C Comware 的 LLDP 邻居输出。
        H3C 实际输出格式示例（display lldp neighbor-information）：
          LLDP neighbor-information of port 1[GigabitEthernet1/0/1]:
           Neighbor index          : 1
           Update time             : 0 days, 0 hours, 5 minutes, 23 seconds
           Chassis ID type         : MAC address
           Chassis ID              : 000c-29ab-cdef
           Port ID type            : Interface name
           Port ID                 : GigabitEthernet1/0/2
           Port description        : GE1/0/2
           System name             : ACCESS-SW02
           ...
        """
        neighbors = []
        # 切分每个接口的邻居块
        port_sections = re.split(
            r"LLDP neighbor-information of port\s+\d+\[([^\]]+)\]", out
        )
        # port_sections 格式: [前缀, 接口名1, 块1, 接口名2, 块2, ...]
        i = 1
        while i + 1 < len(port_sections):
            local_port = port_sections[i].strip()
            block = port_sections[i + 1]
            nb = {"local_port": local_port}
            for line in block.splitlines():
                line = line.strip()
                if re.match(r"System name\s*:", line, re.I):
                    nb["neighbor"] = line.split(":", 1)[1].strip()
                elif re.match(r"Port ID\s*:", line, re.I):
                    nb["remote_port"] = line.split(":", 1)[1].strip()
            if nb.get("neighbor"):
                neighbors.append(nb)
            i += 2

        if not neighbors:
            neighbors = self._parse_lldp_fallback(out)

        return neighbors

    def _parse_lldp_fallback(self, out: str) -> list:
        """
        通用 LLDP 兜底解析：
        逐行提取 System name / Port ID / Interface 字段，
        每次遇到新的 System name 则创建一条新记录。
        适用于两种厂商格式均无法匹配时的最后保障。
        """
        neighbors = []
        current = {}
        for line in out.splitlines():
            line = line.strip()
            if re.match(r"System name\s*:", line, re.I):
                if current.get("neighbor"):
                    neighbors.append(current)
                current = {"neighbor": line.split(":", 1)[1].strip()}
            elif re.match(r"Port ID\s*:", line, re.I) and current:
                current["remote_port"] = line.split(":", 1)[1].strip()
            elif re.match(r"(Local )?[Pp]ort\s*:", line) and current and "local_port" not in current:
                current["local_port"] = line.split(":", 1)[1].strip()
            elif re.match(r"Interface\s*:", line, re.I) and current and "local_port" not in current:
                current["local_port"] = line.split(":", 1)[1].strip()
        if current.get("neighbor"):
            neighbors.append(current)
        return neighbors

    def _parse_h3c_version(self, out: str, info: DeviceInfo):
        m = re.search(r"H3C\s+(\S+)\s+.*?Version\s+([\d.()A-Za-z]+)", out, re.I)
        if m:
            info.model = m.group(1)
        # 仅在 sysname 未获取时才从 display version 提取
        if not info.sysname:
            m2 = re.search(r"(?:^|\n)([A-Za-z][A-Za-z0-9_-]{2,})\s+uptime is\s+(.+)", out, re.I | re.M)
            if m2:
                info.sysname = m2.group(1).strip()
                info.uptime = m2.group(2).strip()
        m2b = re.search(r"uptime is\s+(.+)", out, re.I)
        if m2b:
            info.uptime = m2b.group(1).strip()
        m3 = re.search(r"[Ss]erial[- ][Nn]umber\s*[:\s]+(\S+)", out)
        if m3:
            info.serial = m3.group(1)

    def _parse_h3c_interfaces(self, out: str) -> list:
        interfaces = []
        blocks = re.split(r"\n(?=\S+\s+current state)", out)
        for block in blocks:
            iface = Interface(name="")
            m = re.match(r"(\S+)\s+current state\s*:\s*(\S+)", block)
            if not m:
                continue
            iface.name = m.group(1)
            iface.status = m.group(2)
            m2 = re.search(r"Line protocol current state\s*:\s*(\S+)", block)
            if m2:
                iface.protocol = m2.group(1)
            m3 = re.search(r"Description[:\s]+(.+)", block)
            if m3:
                iface.description = m3.group(1).strip()
            m4 = re.search(r"Internet Address\s+is\s+([\d.]+)/([\d]+)", block)
            if m4:
                iface.ip = m4.group(1)
                iface.mask = m4.group(2)
            m5 = re.search(r"Hardware address is\s+([\da-fA-F-]+)", block)
            if m5:
                iface.mac = m5.group(1)
            interfaces.append(iface)
        return interfaces

    # ------------------------------------------------------------------ #
    #  主采集入口                                                           #
    # ------------------------------------------------------------------ #
    def collect(self) -> DeviceInfo:
        info = DeviceInfo(ip=self.ip)

        # ★ 缓存命中检查 ★
        cached = self._load_cache()
        if cached is not None:
            return cached

        if not self.connect():
            info.error = self.connect_error or "SSH连接失败"
            return info

        try:
            if self.vendor == "auto":
                self.detect_vendor()
            info.vendor = self.vendor

            # ---------- 设备名（sysname）----------
            # 最优先：直接取 display sysname，这是设备配置的规范名称
            # 兼容多种输出格式：Sysname is XXX / Sysname: XXX / sysname XXX
            for cmd, pats in [
                ("display sysname", [
                    r"[Ss]ysname\s+is\s+(\S+)",        # Sysname is WULIU_HEXIN
                    r"[Ss]ysname:\s*(\S+)",              # Sysname: WULIU_HEXIN
                    r"^[Ss]ysname\s+(\S+)",              # sysname WULIU_HEXIN (line start)
                    r"^(\S+)$",                           # Just the name on its own line
                ]),
                ("display current-configuration | include ^sysname", [
                    r"sysname\s+(\S+)",                  # sysname WULIU_HEXIN
                ]),
            ]:
                out0 = self.send(cmd, wait=1)
                for pat in pats:
                    m0 = re.search(pat, out0, re.I | re.M)
                    if m0:
                        raw_name = m0.group(1).strip()
                        # 华为设备 display sysname 输出格式为 <设备名>，去除尖括号
                        info.sysname = raw_name.strip("<>")
                        logger.debug(f"[{self.ip}] 设备名通过 '{cmd}' 获取: {info.sysname}")
                        break
                if info.sysname:
                    break

            # ---------- 版本信息（display version 解析）----------
            ver_out = self.send("display version", wait=2)
            if self.vendor == "huawei":
                self._parse_huawei_version(ver_out, info)
            else:
                self._parse_h3c_version(ver_out, info)

            # 若仍未获取设备名，尝试其他途径
            if not info.sysname:
                for cmd, pat in [
                    ("display snmp-agent sys-info", r"[Ss]ystem\s+[Nn]ame\s*[:=]?\s*(\S+)"),
                ]:
                    out2 = self.send(cmd, wait=1)
                    m2 = re.search(pat, out2, re.I)
                    if m2:
                        info.sysname = m2.group(1).strip()
                        logger.debug(f"[{self.ip}] 设备名通过 '{cmd}' 获取: {info.sysname}")
                        break
                # 最后一搏：接口描述中含设备名特征的取第一个
                if not info.sysname:
                    for iface in info.interfaces:
                        if iface.description:
                            m3 = re.search(r"^\[?([A-Za-z][A-Za-z0-9_-]{2,})", iface.description.strip())
                            if m3:
                                info.sysname = m3.group(1)
                                logger.debug(f"[{self.ip}] 设备名通过接口描述获取: {info.sysname}")
                                break

            # ---------- 接口详情 ----------
            intf_out = self.send("display interface", wait=3)
            if self.vendor == "huawei":
                info.interfaces = self._parse_huawei_interfaces(intf_out)
            else:
                info.interfaces = self._parse_h3c_interfaces(intf_out)

            # ---------- IP 接口摘要 ----------
            ip_out = self.send("display ip interface brief", wait=2)
            self._merge_ip_brief(ip_out, info.interfaces)

            # ---------- LLDP 邻居 ----------
            # 华为: display lldp neighbor brief  → 摘要，含本端接口
            # H3C:  display lldp neighbor-information → 详情
            # 先尝试详情命令（detail/neighbor-information），再尝试 brief，取数据更多的
            if self.vendor == "huawei":
                lldp_out = self.send("display lldp neighbor", wait=3)
                # 华为还有 brief 格式，若 detail 为空则尝试 brief
                if len(lldp_out.strip()) < 50:
                    lldp_out = self.send("display lldp neighbor brief", wait=2)
                info.neighbors = self._parse_huawei_neighbors(lldp_out)
            else:
                # H3C Comware
                lldp_out = self.send("display lldp neighbor-information", wait=3)
                if len(lldp_out.strip()) < 50:
                    lldp_out = self.send("display lldp neighbor", wait=2)
                info.neighbors = self._parse_h3c_neighbors(lldp_out)
            logger.info(f"[{self.ip}] LLDP 邻居数: {len(info.neighbors)}")

            # ---------- CPU & 内存 ----------
            cpu_out = self.send("display cpu-usage" if self.vendor == "huawei"
                                else "display cpu-usage", wait=1)
            m = re.search(r"(\d+)%", cpu_out)
            if m:
                info.cpu_usage = m.group(1) + "%"

            mem_out = self.send("display memory-usage" if self.vendor == "huawei"
                                else "display memory", wait=1)
            m2 = re.search(r"Memory Using Percentage\s*:\s*(\d+)%", mem_out)
            if m2:
                info.mem_usage = m2.group(1) + "%"

            # ---------- VLAN ----------
            vlan_out = self.send("display vlan brief" if self.vendor == "huawei"
                                 else "display vlan brief", wait=2)
            info.vlans = self._parse_vlans(vlan_out)

            # ---------- 路由摘要 ----------
            route_out = self.send("display ip routing-table statistics", wait=2)
            info.routes = self._parse_route_stats(route_out)

        except Exception as e:
            info.error = str(e)
            logger.error(f"[{self.ip}] 采集异常: {e}")
        finally:
            self.disconnect()

        # ★ 采集成功后写入缓存 ★
        if not info.error:
            self._save_cache(info)

        return info

    def _merge_ip_brief(self, out: str, interfaces: list):
        """将 ip interface brief 的IP信息补充到接口列表"""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and re.match(r"[\d.]+", parts[1]):
                for iface in interfaces:
                    if iface.name == parts[0] and not iface.ip:
                        iface.ip = parts[1]
                        break

    def _parse_vlans(self, out: str) -> list:
        vlans = []
        for line in out.splitlines():
            m = re.match(r"\s*(\d+)\s+(\S+)\s*(.*)", line)
            if m and m.group(1).isdigit():
                vlans.append({
                    "vlan_id": m.group(1),
                    "name": m.group(2),
                    "ports": m.group(3).strip()
                })
        return vlans

    def _parse_route_stats(self, out: str) -> list:
        stats = []
        for line in out.splitlines():
            m = re.match(r"\s*(\S+)\s+(\d+)\s+(\d+)", line)
            if m:
                stats.append({
                    "protocol": m.group(1),
                    "total": m.group(2),
                    "active": m.group(3)
                })
        return stats
