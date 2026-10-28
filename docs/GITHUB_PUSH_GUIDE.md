# GitHub 推送标准流程

> 通用文档，适用于 Python / 桌面工具类项目；后续其他项目可直接复制本文件并按占位符替换。
>
> 本项目实际值：
> - 仓库：`https://github.com/paynehe3023/swCfgBackup.git`
> - 分支：`main`
> - 版本：`v1.0.0`
> - 作者：`payne`

---

## 0. 原则

1. **永不提交凭据**：密码、Token、私钥、含明文密码的 Excel、`.env` 一律不进入仓库。
2. **不提交构建产物**：`dist/`、`build*/`、`.venv/`、`__pycache__/`、`*.exe`、`*.spec`。
3. **不提交运行数据**：备份目录、日志、`.bak`、`.diff`、设备清单。
4. **推送前先看状态**：`git status` 和 `git status --ignored`，确认不会带入不该提交的文件。
5. **不 force push 公共分支**：除非确认远程历史只有占位内容，且已与协作者沟通。
6. **中文内容没问题**：README、提交信息、Release 说明、产品名都支持中文；代码路径和 Release 附件名建议用 ASCII。

---

## 1. 推送前检查清单

逐项确认后再提交：

- [ ] `.gitignore` 已覆盖虚拟环境、构建产物、备份、日志、清单文件、密钥。
- [ ] 搜索敏感信息：
  ```bash
  git status
  git status --ignored
  git grep -n -i -E "(password|passwd|secret|token|api[_-]?key)" -- . ':!*.md'
  ```
- [ ] 确认没有 `pw.xlsx`、`*.bak`、`backup/`、`dist/` 被暂存：
  ```bash
  git ls-files | grep -Ei "(pw\.xlsx|\.bak$|^backup/|^dist/|\.env)"
  ```
- [ ] README 完整：功能、环境、安装、用法、输出、构建、FAQ、许可证。
- [ ] `LICENSE`、`CHANGELOG.md` 存在。
- [ ] 版本号一致：`version.py`、`version_info.txt`、即将创建的标签（如 `v1.0.0`）。
- [ ] 行尾与编码：`.gitattributes` 已设置 `text=auto`，二进制文件标记为 `binary`。
- [ ] 构建产物已在本地验证：exe 可启动，关键功能可用。

---

## 2. 首次推送：远程是空仓库

```bash
cd /path/to/project

git init -b main
git add .
git status                      # 再次确认暂存内容
git commit -m "feat: initial commit"

git remote add origin <REPO_URL>
git push -u origin main
```

如果远程已有一次占位提交（例如只有 README），直接用下面的“远程已有内容”流程，避免覆盖或强推。

---

## 3. 首次推送：远程已有内容（推荐，无需 force）

适用于：远程仓库创建时勾选了 README，而本地项目尚未是 Git 仓库。

```bash
cd /path/to/project

git init -b main
git remote add origin <REPO_URL>
git fetch origin

# 把本地 HEAD 和索引对齐到远程 main，但保留工作区文件不动
git reset --mixed origin/main

git add -A
git status                      # 确认：README 修改 + 项目文件新增
git commit -m "feat: initial import of <PROJECT_NAME>"

git push -u origin main
```

`git reset --mixed` 只移动 HEAD 和索引，不会覆盖工作区；随后提交会接在远程历史之后，因此是普通快进推送，**不需要 force**。

---

## 4. 日常提交流程

```bash
git status
git diff                        # 查看未暂存改动
git add <files>                 # 尽量精确添加，少用 git add -A
git diff --cached               # 查看即将提交的内容
git commit -m "fix: ..."
git push
```

多人协作或远程有更新时：

```bash
git fetch origin
git rebase origin/main          # 或 git merge origin/main
```

解决冲突后 `git add`、`git rebase --continue`，再推送。

---

## 5. 标签与 Release

打标签：

```bash
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

在 GitHub → Releases → Draft a new release：

1. 选择刚推送的标签（如 `v1.0.0`）。
2. 填写标题和发布说明（可粘贴 `CHANGELOG.md` 对应段落）。
3. 上传附件：
   - **建议 ASCII 文件名**：`swCfgBackup-v1.0.0-win64.zip` 或 `swCfgBackup-v1.0.0-win64.exe`。
   - 如果程序内“检查更新”要能下载，附件必须是 `.exe` 或 `.zip`。
   - 中文附件名 GitHub 支持，但 URL 会被编码，部分下载工具或脚本处理不便。
4. 发布。

版本升级检查清单：

- [ ] `version.py` 的 `APP_VERSION`
- [ ] `version_info.txt` 的 `filevers` / `prodvers` / `FileVersion` / `ProductVersion`
- [ ] `CHANGELOG.md` 新增条目
- [ ] 提交后打标签 `vX.Y.Z` 并推送
- [ ] GitHub Release 上传新附件

---

## 6. 认证

### HTTPS + Git Credential Manager（推荐 Windows）

```bash
git config --global credential.helper manager
git push -u origin main
```

首次推送会弹出浏览器/窗口登录；凭据由系统凭据管理器保存。**不要把 Token 写进 URL 或配置文件**。

检查：

```bash
git config --global credential.helper
git remote -v
```

### SSH

```bash
ssh-keygen -t ed25519 -C "you@example.com"
# 将 ~/.ssh/id_ed25519.pub 添加到 GitHub → Settings → SSH keys
ssh -T git@github.com
git remote set-url origin git@github.com:<owner>/<repo>.git
```

### Personal Access Token（仅在无法使用 GCM 时）

- 使用 `repo` 权限的 fine-grained token；
- 通过凭据管理器输入，不要写进命令历史或脚本；
- Token 泄漏后立即撤销并重新生成。

---

## 7. 常见问题

**`rejected ... non-fast-forward`**

远程有你没有的提交：

```bash
git fetch origin
git rebase origin/main
git push
```

不要在公共分支上直接 `--force`；如必须强制，使用 `--force-with-lease` 并先沟通。

**误提交了密码 / 密钥**

1. 立即撤销/轮换该凭据（改密码、吊销 Token）。
2. 从仓库移除文件并提交。
3. 如已推送，使用 `git filter-repo` 清理历史，然后与协作者协调强制推送。
4. 记住：仅仅删除文件不会从历史中移除。

**大文件推送失败**

- 单个文件建议 < 50 MB，仓库 < 1 GB；
- 大二进制用 Git LFS 或放到 Release 附件；
- 已提交的大文件需要重写历史（`git filter-repo`）。

**中文文件名显示为转义**

```bash
git config --global core.quotepath false
```

**换行符警告 / 全文件变更**

- 确保 `.gitattributes` 存在；
- Windows 批处理用 CRLF，源码/文档用 LF；
- 不要在仓库中混用 CRLF/LF。

**403 / 权限不足**

- 确认 Token 具备 `repo` 或 fine-grained 的 Contents 读写权限；
- 确认远程地址属于你有权限的仓库；
- 组织仓库可能需要 SSO 授权。

---

## 8. 一页速查

```bash
# 首次（远程已有占位 README）
git init -b main
git remote add origin <REPO_URL>
git fetch origin
git reset --mixed origin/main
git add -A
git status
git commit -m "feat: initial import"
git push -u origin main

# 日常
git status
git add <files>
git diff --cached
git commit -m "type: message"
git push

# 版本
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

---

## 9. 本项目执行记录

- 仓库：`https://github.com/paynehe3023/swCfgBackup.git`
- 分支：`main`
- 版本标签：`v1.0.0`
- 远程初始内容：仅一个占位 `README.md`
- 采用流程：第 3 节（`fetch` + `reset --mixed` + 普通提交 + 快进推送）
- 不提交：`dist/`、`.venv/`、`pw.xlsx`、备份目录、日志、`.bak`
