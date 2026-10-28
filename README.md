# 网络设备配置备份（swCfgBackup）

<p align="center">
  <img src="image/icon.png" width="140" alt="swCfgBackup icon">
</p>

一个面向 **华为 VRP / H3C Comware** 网络设备的配置备份工具，提供 Windows 图形界面和命令行两种使用方式。

只读采集、批量并发、差异对比、完整性校验、主机名回填、失败补采、单台临时备份。

- 版本：v1.0.1
- 作者：payne
- 仓库：<https://github.com/paynehe3023/swCfgBackup>

---

## 功能

- **SSH 只读备份**：登录设备执行 `display current-configuration`，只读取配置，不修改设备。
- **自动识别厂商**：华为 VRP / H3C Comware 自动判断，无需手工指定。
- **完整性校验**：配置必须以 `return` + 设备提示符结尾；截断会自动重试一次，仍不完整则判失败且不落盘，避免污染基线。
- **差异对比**：每次备份与上一份对比，生成 `.diff`；自动忽略设备回显、时间戳、提示符等噪声行。
- **按份数保留**：每台设备保留最近 N 份（默认 1 份），更早的 `.txt/.diff` 自动删除。
- **失败补采**：第一轮结束后等待 30 秒，对失败设备再试一次；默认跳过认证失败以避免锁号。
- **主机名回填**：从设备配置提取 `sysname`，只回填 Excel 清单中的空单元格，不覆盖手工维护的值。
- **单台备份**：在 GUI 输入 IP / 端口 / 账号 / 密码，单独备份一台不在清单里的设备。
- **自动日志**：每次批量或单台备份自动在备份目录生成 `backup_log_*.txt`。
- **关于与更新**：关于窗口展示版本/作者，可从 GitHub 检查并下载最新版本（不显示仓库地址）。
- **商业授权（注册版）**：Ed25519 离线注册码，绑定本机机器码，升级新版本继续沿用原注册码。
- **并发执行**：多线程同时备份多台设备，默认并发 3。

## 环境要求

- Windows 10/11（GUI）；命令行也支持 Linux/macOS
- Python 3.10+（源码运行）
- `paramiko>=3.4.0,<4.0.0`（**必须 3.x**；4.x/5.x 对老设备的 SHA-1 算法兼容性不同）
- `openpyxl>=3.1.2`

## 快速开始

### 方式一：使用打包好的 exe

运行 `dist/swCfgBackupS.exe`（注册版，首次运行需要激活；exe 内置运行依赖，无需 Python 环境）。

### 方式二：源码运行

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/pythonw.exe backup_gui.py      # GUI
.venv/Scripts/python.exe backup_tool.py -i pw.xlsx   # 命令行
```

## 设备清单格式

支持 `.xlsx`，默认读取第一个 Sheet。列名支持中英文，顺序随意，未识别的列会被忽略。

| IP地址 | 用户名 | 密码 | 主机名 | 端口 |
|--------|--------|------|--------|------|
| 10.175.10.1 | admin | Admin@123 | | 22 |
| 10.175.10.2 | admin | Admin@456 | | 22 |

- **IP地址、用户名、密码**：必填
- **主机名**：可选；留空时首次备份成功后自动回填
- **端口**：可选，默认 22
- 厂商默认自动识别；如需固定厂商，可自行增加“厂商”列（`huawei` / `h3c` / `auto`）
- 生成标准模板：

```bash
.venv/Scripts/python.exe backup_tool.py --create-template
```

## GUI 使用

1. 左侧选择 Excel 清单，设置备份目录、每设备保留份数、并发数。
2. 点击「加载清单」，在「设备清单」页查看设备。
3. 在「设备清单」页单击已选中的行或双击单元格，可修改 IP / 主机名 / 端口：
   - 修改立即写回 Excel；写失败会标记为未保存，可点「保存清单修改」重试；
   - 备份进行中不允许修改。
4. 点击「开始备份」，在「概览 / 备份结果 / 运行日志」页查看进度与结果。
5. 失败设备会在 30 秒后自动补采一次；日志自动保存到备份目录。
6. 需要临时备份一台设备时，切到「单台备份」页填写信息执行。
7. 右上角「关于」可检查并下载 GitHub 最新版本。

## 单台备份

- 输入 IP、端口（默认 22）、用户名、密码，点击「开始单台备份」。
- 只读执行，不修改设备，也不会写入 Excel 清单。
- 文件仍保存到 `备份目录/<IP>/`，命名规则与批量一致。
- 单台备份与批量备份不能同时运行。

## 命令行

```bash
python backup_tool.py --help
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--inventory, -i` | Excel 设备清单 | 必填 |
| `--sheet` | 指定 Sheet 名 | 第一个 Sheet |
| `--username` | 默认用户名（Excel 为空时使用） | `admin` |
| `--password` | 默认密码（Excel 为空时使用） | — |
| `--backup-dir` | 备份目录 | `backup` |
| `--keep-count` | 每设备保留份数（`--keep-min` 为兼容别名） | `1` |
| `--concurrency, -j` | 并发线程数 | `3` |
| `--retry-delay` | 失败补采等待秒数 | `30` |
| `--no-retry-failed` | 禁用失败补采 | — |
| `--retry-auth` | 认证失败也补采一次（注意锁号风险） | — |
| `--no-write-back` | 不回填主机名到 Excel | — |
| `--create-template` | 生成 Excel 模板 | — |

示例：

```bash
# 基本备份
python backup_tool.py -i pw.xlsx

# 指定目录、每设备保留 10 份、并发 5
python backup_tool.py -i pw.xlsx --backup-dir D:\配置备份 --keep-count 10 -j 5

# 生成模板
python backup_tool.py --create-template
```

## 输出文件

```
backup/
├── 10.175.10.253/                                        # 每台设备一个子目录（按 IP）
│   ├── KLT-XinQu-FW_10.175.10.253_20261028_083159.txt    # 配置
│   └── KLT-XinQu-FW_10.175.10.253_20261028_083159.diff   # 差异（有变更时）
├── backup_report_20261028_083159.xlsx                    # 汇总报告
└── backup_log_20261028_083159.txt                        # 运行日志
```

- 文件名：`{sysname}_{IP}_{YYYYMMDD}_{HHMMSS}.txt`
  - `sysname` 从设备配置提取；Windows 非法字符替换为 `_`；提取不到时为 `unknown`
  - 同一秒重复备份追加 `_1`、`_2`
- `.diff`：与配置同名，记录与上一份的差异；上一份按文件修改时间选取
- 报告：包含 IP、主机名、时间、状态、大小、变更、文件名、错误信息
- 每台设备只保留最近 N 份（默认 1 份），`_truncated` 等以 `_` 开头的目录不参与清理

## 主机名回填

- 备份成功后从配置的 `sysname` 提取主机名；
- 只写 Excel 中**主机名列为空**的单元格；
- 没有“主机名”列时自动追加；
- 写入前保留同目录 `.bak`，先写临时文件再原子替换；
- Excel 被占用时提示关闭文件，不影响备份结果；
- 命令行可用 `--no-write-back` 关闭。

## 版本与授权

对外发布的是**注册版 `swCfgBackupS.exe`**；首次运行需要输入注册码，激活后正常使用。

### 使用步骤（注册版）

1. 运行 `swCfgBackupS.exe`；
2. 首次启动会显示**本机机器码**（26 位，按 5 位分组）；
3. **把机器码发给作者 payne，联系领取注册码**（请通过购买/分发渠道联系作者）；
4. 把收到的注册码粘贴到激活窗口，点击「激活」；
5. 以后从 GitHub 下载新版本，直接替换 exe 即可，原注册码继续有效，无需重新领取。

### 作者签发注册码

1. 在作者本地打开注册机 `swCfgBackupS-注册机.exe`（或使用命令行）；
2. 输入用户的机器码、客户名称、可选到期日，生成注册码；
3. 把注册码发给用户。

命令行方式：

```bash
python license_tools/make_license.py \
    --machine "<机器码>" --customer "客户名称" \
    --out license_tools/out/customer.key
```

图形注册机与私钥只在作者本地保存，不随软件发布。注册码保存在 `%APPDATA%\swCfgBackup\license.dat`。

### 授权规则

- 注册码使用 **Ed25519 签名**，程序只内置公钥，无法自行生成有效注册码；
- 注册码绑定机器码，复制到其他电脑无效；
- 一台电脑对应一个注册码；生成器默认拒绝为同一机器码重复签发（`--force` 可重发）；
- 注册码**与软件版本无关**：从 GitHub 下载新版本后，原注册码继续有效，无需重新激活；
- 支持可选到期日；留空表示永久；
- 重装 Windows 会改变机器码，需要重新签发；一般硬件更换不影响（主要依据 MachineGuid）。

### 私钥安全

- `license_tools/private_key.pem` 是签发注册码的唯一凭据，已加入 `.gitignore`；
- **绝不提交、绝不随软件分发**；请立即备份到安全位置；
- 私钥丢失后无法再签发新注册码（已签发的仍有效）；私钥泄露则任何人都能伪造注册码；
- 注册码生成器可以提交，私钥不能；
- 后续版本**不要更换公钥或修改机器码算法**，否则已有注册码会失效。

### 保护强度说明

这是客户端离线校验：

- 能防止普通用户把注册码复制到其他电脑，也能防止随意生成注册码；
- 如果源码仓库公开，开发者仍可通过修改源码绕过校验；
- 如需更强保护，建议源码仓库私有、只发布 exe，或使用 PyArmor / Nuitka 等加固，或改为在线激活/服务端校验。

## 更新与发布

「关于」→「检查更新」优先读取 `releases.atom`，只有发现新版本时才调用 GitHub API 获取附件；API 限流时仍可通过「打开发布页」手动下载。

- 支持查看发布说明；
- 有 `.exe` / `.zip` 附件时可下载到本地（默认保存到“下载”目录，可自选路径）；
- 下载的是文件，不会自动替换正在运行的 exe；关闭程序后手动替换即可；
- 注册码保存在 AppData，替换 exe 不影响授权。

创建 Release 时：

- 标签使用 `v1.0.1` 这类格式，与 `version.py` 中的 `APP_VERSION` 对应；
- **只上传注册版 `dist/swCfgBackupS.exe`**；免费版和注册机不要上传；
- 附件名使用 ASCII，避免 URL 编码和部分下载工具的问题；
- 产品名、窗口标题、版本资源中的中文不受影响。

## 构建 exe

```bash
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe tools/make_icon.py     # 由 image/configBak.png 生成 icon.ico / icon.png
.venv/Scripts/python.exe build_gui.py           # 默认构建免费版、注册版、注册机
```

输出：

- `dist/swCfgBackup.exe`：免费版，仅本地调试使用，**不要上传**
- `dist/swCfgBackupS.exe`：注册版，**GitHub 只上传这个**
- `dist/swCfgBackupS-注册机.exe`：注册机，**仅作者本地使用，不要上传**

单独构建：

```bash
python build_gui.py --edition free
python build_gui.py --edition commercial
python build_gui.py --edition generator
```

- `image/icon.ico` 包含 16/20/24/32/40/48/64/96/128/256 多尺寸；
- 打包时写入版本资源，Windows 文件属性显示：
  - 免费版：`swCfgBackup.exe`，产品名“网络设备配置备份”
  - 注册版：`swCfgBackupS.exe`，产品名“网络设备配置备份（注册版）”
  - 注册机：`swCfgBackupS-注册机.exe`，产品名“swCfgBackupS 注册机”
  - 作者：payne；版本：1.0.1
- 如果 `image/icon.ico` 缺失，打包脚本会降级为默认图标并继续。

## 项目结构

```
swBackup/
├── backup_gui.py              # GUI 入口（免费版）
├── backup_gui_commercial.py   # 注册版入口：先激活再启动 GUI
├── backup_tool.py             # 命令行入口
├── backup.py                  # 备份调度、完整性校验、差异、保留、报告、主机名回填
├── collector.py               # SSH 连接、只读白名单、终端交互
├── inventory.py               # Excel 清单读取、模板、写回
├── license_guard.py           # 注册码校验、机器码、激活窗口
├── utils.py                   # 控制台编码、依赖检查
├── version.py                 # 版本/作者/仓库地址/版本比较
├── version_info.txt           # 免费版版本资源
├── version_info_commercial.txt# 注册版版本资源
├── version_info_tool.txt      # 注册机版本资源
├── build.py / build_gui.py
├── tools/make_icon.py         # PNG → 多尺寸透明 ICO
├── license_tools/
│   ├── make_license.py        # 注册码签发核心（命令行）
│   ├── generator_gui.py       # 图形注册机入口（打包为 swCfgBackupS-注册机.exe）
│   ├── private_key.pem        # 私钥（已忽略，绝不提交）
│   └── public_key.txt         # 公钥备份
├── image/                     # 源图与生成好的图标
├── docs/GITHUB_PUSH_GUIDE.md
├── requirements.txt
├── requirements-dev.txt
├── CHANGELOG.md
└── LICENSE
```

## 安全说明

1. **命令白名单**：只允许 `display ...`、`screen-length ...`、`more ...` 等只读命令；`system-view`、`undo`、`save`、`reset`、`reboot` 等被禁止。
2. **不写设备**：工具不会修改设备配置，也不会保存配置到设备。
3. **凭据**：用户名/密码保存在 Excel 清单中，**不要把清单提交到代码仓库**；仓库的 `.gitignore` 已排除 `pw.xlsx`。
4. **主机指纹**：SSH 使用 `AutoAddPolicy`，不校验主机指纹；请只在可信管理网络中使用。
5. **备份内容**：配置文件可能包含 SNMP、账号等敏感信息，请限制备份目录访问权限，不要随意外发。
6. **更新下载**：从 GitHub 下载的 exe/zip 未做签名校验，下载后请自行确认来源。
7. **注册码私钥**：`license_tools/private_key.pem` 只保存在供应商本地，已加入 `.gitignore`；泄露后任何人都能伪造注册码。
8. **客户端校验**：注册码为离线校验，源码公开时开发者仍可修改源码绕过；商业分发建议源码私有或使用加固方案。

## 常见问题

**`SSH协议错误: No existing session`**

设备在建立会话前后主动关闭了连接。常见原因：VTY 并发会话占满、空闲超时、设备重启/繁忙、网络设备切断长连接。工具会自动重试 2 次；仍失败可降低并发或稍后用「单台备份」重试。

**`配置不完整（疑似截断）`**

拉取到的配置没有以 `return` + 提示符结尾。工具会清理残留输出并重试一次；仍不完整则判失败且不保存。常见原因：分页未关闭、输出中途断连、权限不足、设备过慢。可登录设备手动执行 `display current-configuration` 对比。

**`Incompatible ssh peer (no acceptable host key)`**

客户端 paramiko 版本过高，老设备只支持 `ssh-rsa`。请使用 `paramiko>=3.4.0,<4.0.0` 重新打包。

**认证失败**

确认账号密码；如果第一轮失败、第二轮成功，通常是设备会话繁忙。勾选「认证失败也补采一次」可让认证失败参与补采（有锁号风险）。

**设备不是 22 端口**

在清单「端口」列填写实际端口，或在「设备清单」页直接双击修改；单台备份页也可单独指定端口。

**Excel 回填失败**

清单正被 Excel 占用。关闭 Excel 后点「保存清单修改」，或下次备份时自动重试。

**关于里提示没有 Release**

创建新的 Release 时，在 Releases 页面选择标签（如 `v1.0.1`）并上传注册版 exe/zip。

**注册版提示“注册码不适用于本机（机器码不一致）”**

注册码绑定的是另一台电脑的机器码。请把当前激活窗口显示的机器码发给供应商重新签发；不要复制其他电脑的注册码。

**重装系统或换电脑后无法激活**

重装 Windows 会改变 MachineGuid，机器码随之变化，需要重新签发注册码。一般更换硬件不影响。

**从 GitHub 下载新版本后需要重新激活吗？**

不需要。注册码保存在 `%APPDATA%\swCfgBackup\license.dat`，与软件版本无关；替换 exe 后继续使用原注册码。

**注册码丢失 / 想迁移到新电脑**

注册码文件可以备份；迁移到新电脑需要按新机器码重新签发。供应商可通过 `license_tools/make_license.py --force` 重发。

**激活窗口的机器码是什么**

由 Windows MachineGuid 派生的 SHA-256 摘要，仅用于绑定授权；不包含用户名、密码等隐私信息。

## 中文内容与 GitHub

- README、提交信息、Release 说明、产品名使用中文没有问题。
- 仓库内的代码文件名建议保持 ASCII；本项目源码文件名均为 ASCII。
- exe 文件名可以保留中文；但 **Release 附件建议使用 ASCII 名称**，便于下载工具和 URL 处理。
- 如需在 Git 输出中正常显示中文路径，可设置：`git config --global core.quotepath false`。
- 推送流程见 [docs/GITHUB_PUSH_GUIDE.md](docs/GITHUB_PUSH_GUIDE.md)。

## 变更记录

见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE) © 2026 payne
