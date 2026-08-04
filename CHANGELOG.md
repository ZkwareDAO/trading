# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2025-08-04

### Added

- **trading-dev skill** — CTA 量化策略开发全生命周期 Claude Code Skill：脚手架 → 策略编码 → 回测验证 → benchmark 输出，loop-engineering 跨 Phase 大闭环。
- **三种运行模式**：全自动 / 交互 / 单步。
- **loop-engineering**：回测不达标自动回到策略开发修改，循环直到达标。
- **完整模板**：strategy_core / backtest / data_manager / scripts 一键脚手架。
- **Plugin Marketplace 安装**支持。
- **npx skills CLI 安装**支持。
- **手动安装**支持。
- **OpenAI Codex CLI 安装**支持（含项目级安装）。
- **Apache License 2.0**。

### Changed

- License 从 MIT 变更为 Apache 2.0。
- README 移除 symlink 安装方式。
- README 移除「新增 Skill」段落。
- README 新增 Contributing 段落。

[0.1.0]: https://github.com/ZkwareDAO/trading/releases/tag/v0.1.0
