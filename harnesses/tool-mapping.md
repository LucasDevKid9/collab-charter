# 跨平台工具映射表

> 技能正文（`skills/*/SKILL.md`）刻意只描述**动作**，不指名具体工具：
> 「调用一次路由决策」「查一条条款」「跑一次提示词诊断」。各平台把动作
> 翻译成自己的真实工具名。这样一份技能正文能在所有平台上跑，不需要分叉。

本表就是那份翻译。移植到新平台时，只需新增一列，不必改任何技能正文。

## 动作 → 工具对照

| 动作（技能正文中的说法） | 本仓库 MCP 工具 | Claude Code / Codex / Cursor | 无 MCP 时的降级 |
|---|---|---|---|
| 查一条宪章条款 | `charter_clause` | 同名 MCP 工具 | `python3 -m collab_charter.cli clause 0.5-R4` |
| 通览某一章规则 | `charter_clauses` | 同名 MCP 工具 | `python3 -m collab_charter.cli clauses --chapter chapter_5_analysis` |
| 会话开始自检 | `charter_receipt` | 同名 MCP 工具 | `python3 -m collab_charter.cli receipt` |
| 决定处理深度 | `charter_route` | 同名 MCP 工具 | `python3 -m collab_charter.cli route "<文本>"` |
| 跑完整管线 | `charter_handle` | 同名 MCP 工具 | `python3 -m collab_charter.cli handle "<文本>"` |
| 裁决两条冲突陈述 | `charter_arbitrate` | 同名 MCP 工具 | 读 `0.5-R1..R5` 后按序比对 |
| 判断能否外发 | `charter_gate` | 同名 MCP 工具 | 读 `charter.yaml` 的 `enforcement.gate_matrix` |
| 诊断图像提示词 | `fcslint_analyze` | 同名 MCP 工具 | `PYTHONPATH=tools python3 -m fcslint "<提示词>"` |
| 沉淀一条结论 | `memory_deposit` | 同名 MCP 工具 | 写入记忆文件（见 0.6-O1） |
| 激活历史记忆 | `memory_recall` | 同名 MCP 工具 | 读记忆文件（见 0.6-O2） |

## MCP 接入片段

各平台在配置里指向同一个 stdio server，无需改动仓库代码：

```json
{
  "mcpServers": {
    "collab-charter": {
      "command": "python3",
      "args": ["/绝对路径/collab-charter/interfaces/mcp_server.py"]
    }
  }
}
```

Claude Code 的插件清单（`harnesses/claude-plugin/plugin.json`）已内置该字段，
安装插件即自动接入。

## 平台能力差异与降级

宪章第一章 1-C2 要求：AI 若无法满足某条，首次响应时必须显式列出该条及降级方案，
之后不重复声明，**不允许静默忽略**（7-R4）。下表是各平台的常见缺口：

| 能力 | 缺失时的条款 | 降级方案 |
|---|---|---|
| MCP 工具调用 | 0.3 / 0.7 | 用 CLI 或直接把 `charter.yaml` 的相关小节粘进上下文 |
| 跨会话记忆 | 0.6-O1 / O2 | 把 `memory.json` 交给用户自行保存；新会话开始时请用户粘贴 |
| 本地文件读写 | 6-R1 / R2 | 请用户粘贴目标内容；显式说明「我读不到你的本地文件」 |
| 联网核实 | 5-R2 / 8-R2 | 标注「待验证」，并给出建议核实的关键词与预期来源 |
| 子代理并行 | 7-R3 | 用同一上下文内串行执行建构/质疑/验证三角，并说明已降级 |

## 移植到新平台（三步）

1. **清单**：在 `harnesses/<平台>/` 下新增 `plugin.json`，字段照抄语义最接近的现有平台。
2. **引导**：确认该平台是否支持 SessionStart 类钩子。支持则复用 `harnesses/hooks/session-start`；
   不支持则把 `skills/using-charter/SKILL.md` 放进平台的**项目指令文件**
   （`AGENTS.md` / `GEMINI.md` / 自定义指令栏）。
3. **映射**：在本表新增一列，填该平台的真实工具名；缺能力时写清降级方案。

三步都不需要改动 `skills/` 与 `src/` 下的任何文件——这是本设计的核心不变量。
