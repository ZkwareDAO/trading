# Trading Dev Skill — Codex CLI 安装指南

## 前提条件

- Git
- Codex CLI

## 安装步骤（macOS / Linux）

```bash
# 1. 克隆仓库
git clone https://github.com/ZkwareDAO/trading ~/.codex/trading

# 2. 创建 skill symlink（Codex 自动发现）
ln -s ~/.codex/trading/codex/trading-dev ~/.codex/skills/trading-dev

# 3. 创建 prompt 触发器
ln -s ~/.codex/trading/commands/trading-dev.md ~/.codex/prompts/trading-dev.md

# 4. 重启 Codex
```

## 安装步骤（Windows PowerShell）

```powershell
# 1. 克隆仓库
git clone https://github.com/ZkwareDAO/trading $env:USERPROFILE\.codex\trading

# 2. 创建 skill 目录联接
New-Item -ItemType Junction -Path "$env:USERPROFILE\.codex\skills\trading-dev" -Target "$env:USERPROFILE\.codex\trading\codex\trading-dev"

# 3. 复制 prompt 文件（Windows 硬链接更可靠）
cmd /c mklink /H "$env:USERPROFILE\.codex\prompts\trading-dev.md" "$env:USERPROFILE\.codex\trading\commands\trading-dev.md"

# 4. 重启 Codex
```

## 项目级安装

将 skill 放在项目目录下，仅对当前项目生效：

```bash
mkdir -p .agents/skills/trading-dev
cp -r codex/trading-dev/* .agents/skills/trading-dev/

mkdir -p .agents/prompts
cp commands/trading-dev.md .agents/prompts/trading-dev.md
```

## 验证

在 Codex 会话中输入 `$trading-dev`，或检查 `~/.codex/skills/trading-dev/SKILL.md` 是否存在。

## 触发方式

| 方式 | 说明 |
|------|------|
| 自动触发 | 任务描述匹配 SKILL.md description 时自动激活 |
| `$trading-dev` | 直接调用 |
| `/prompts:trading-dev` | 手动 prompt 触发 |

## 更新

```bash
cd ~/.codex/trading && git pull
# symlink 自动指向最新版本
```

## 卸载

```bash
rm ~/.codex/skills/trading-dev
rm ~/.codex/prompts/trading-dev.md
rm -rf ~/.codex/trading
```
