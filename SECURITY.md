# 安全策略

本文件说明 collab-charter 的安全边界、报告方式，以及维护者账号的认证要求。
它只陈述**可核实的事实**；无法核实的承诺不写在这里。

## 报告漏洞

请通过 GitHub 的**私密漏洞报告**提交，不要在公开 issue 里贴利用细节：

- 打开 <https://github.com/LucasDevKid9/collab-charter/security/advisories/new>
- 若该入口不可用，请开一个**不含细节**的 issue，说明"需要私密渠道"，维护者会回复建立联系

请在报告中包含：受影响版本（`collab_charter.__version__`）、复现步骤、影响范围。
我们会在 7 天内确认收到，30 天内给出处理结论（修复 / 不予处理 / 需要更多信息）。

## 支持范围

| 版本 | 支持状态 |
|---|---|
| 3.3.x | 接受安全报告 |
| ≤ 3.2 | 不再单独修，请升级 |

## 本项目自身的安全设计

- **零凭据**：仓库内不含任何密钥、令牌、证书。测试与示例全部使用合成数据。
- **令牌形态自检**：`src/collab_charter/sanitize.py` 内置凭据模式检测（GitHub PAT、常见云厂商密钥等），
  用于在记忆写入与工具入参处拦截意外泄漏。
- **依赖面小**：运行时仅依赖 PyYAML（解析宪章与知识库）；MCP 服务器只用标准库。
  `z3-solver` 为**可选**依赖，缺失时符号锚定功能明确报错而非静默降级。
- **沙箱化谓词**：`anchor/solver.py` 用 AST 白名单解析约束表达式，拒绝任意代码执行；
  逃逸构造有参数化测试覆盖。
- **不外发**：MCP 服务器走 stdio，不发网络请求、不收集遥测。

## 维护者账号

GitHub 自 2023 年起对「在 GitHub.com 上贡献代码」的账号强制要求双因素认证（2FA）。
本仓库维护者账号在该计划内，强制截止时间为 **2026-11-29 00:00 UTC**（北京时间 08:00）。

由此产生的两条公开事实：

1. 推送使用**细粒度 PAT**，权限限定到本仓库，不具跨仓库或账号级权限；
2. 令牌不进入仓库、不进入提交历史、不出现在构建产物中。

## 供应链

- 发布流程不依赖第三方 CI 服务；
- 所有提交由同一账号签名推送，提交历史线性（无 force-push 改写历史）；
- 依赖变更需在 `pyproject.toml` / `requirements.txt` 中显式可见。

---

## Security Policy (English)

Report vulnerabilities privately via
[GitHub Security Advisories](https://github.com/LucasDevKid9/collab-charter/security/advisories/new) —
never in a public issue. Include version, reproduction steps, and impact. We acknowledge within
7 days and conclude within 30.

The repository contains **no credentials**. `src/collab_charter/sanitize.py` detects token-shaped
strings (GitHub PATs, common cloud keys) at memory-write and tool-input boundaries. Runtime
dependencies are limited to PyYAML (charter and knowledge-base parsing); the MCP server uses the
standard library only. `z3-solver` is an optional extra that fails loudly when absent rather than
degrading silently. The MCP server speaks stdio, makes no network calls, and collects no telemetry.

Maintainer pushes use a repository-scoped fine-grained PAT. Tokens never enter the repository,
the commit history, or build artifacts.
