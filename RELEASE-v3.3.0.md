# 🚀 collab-charter v3.3.0 — 从「审计框架」升级为「可被 Agent 依赖的执行层」

> 这个版本把上一轮深度评审发现的 **P0 / P1 / P2 问题全部落地**，
> 内核不再只是"高度可信的审计壳"，而是真正能接住真实 Agent 的执行层。

---

## ✨ 一句话看懂这版

| 之前 | 现在 |
|------|------|
| 仲裁规则顺序是"写死的"，改宪章可能悄悄跑偏 | **顺序写进宪章 + 启动断言锁死**，改哪边都立刻报错 |
| 认知镜像 / 角色协作只是模板占位 | **可注入真实 LLM 回调**，无回调自动回退模板 |
| 记忆检索靠子串硬匹配，同义改写会漏 | **语义召回**，说"把模块重构掉"也能找到"重构模块" |
| 求解器用 `eval()`，需要"信任白名单" | **纯 AST 解释器，零 eval**，纵深防御到底 |
| MCP 协议是手写子集，没在真客户端验过 | **官方 mcp SDK 端到端冒烟通过**，Claude Code 能直接握手 |
| 路由决策只转发调用方的判断 | **内核自己会猜任务复杂度**，没人打标也能走对流程 |

---

## 🔧 具体改了什么

### 🧭 仲裁层 — 零漂移
- `0.5_arbitration` 新增 **`eval_order`**（R5→R1→R2→R3→R4），宪章是唯一事实源
- `Arbiter.__init__` 启动断言：**改宪章不改代码 / 改代码不改宪章 → 立即报错**
- 修复 R2（时效）与 R3（来源）的顺序漂移，补了分歧用例测试

### 🧠 执行层 — 真正可执行
- `stage_hooks` 从「仅 EMIT 生效」→ **全 8 站统一生效**
- 新增 **`mirror_fn` / `council_fn`**：真实 LLM 回调替代模板，零依赖兜底
- **`plan()` 自动复杂度判定**：`bool | None` 语义，没人打标时内核从文本自己判断

### 💾 记忆层 — 召回更聪明
- `recall(semantic=True)`：复用 lexicon 确定性词元策略做**词元重叠语义检索**
- 同义改写可召回，子串命中额外加权，纯规则、可复现、零新依赖

### 🛡 锚定层 — 更安全
- `_safe_eval` 从 `eval(compile(...))` → **纯 AST 解释器**（手工遍历白名单节点）
- 符号操作数走 z3 的 And/Or/Not/Compare，原生值走 Python，彻底消灭 eval

### 🔌 接口层 — 真客户端可握手
- `initialize` 声明 `resources` / `prompts` 能力
- **协议版本协商**：按客户端声明回显，未知回退服务端版本
- `notifications/*`（含 cancelled/progress）一律正确不回
- **真实 `mcp` SDK `ClientSession` 端到端冒烟**（stdio 全流程）

---

## ✅ 质量验证

- 🧪 **测试：368 → 391 项，全绿**
- 🧭 `cli verify`：三契约 + 路由站点 + 闸门 9/9 + 自检 6 项，全部 PASS
- 🔍 端到端冒烟：mirror_fn 注入 / 语义召回 / C4 自检 / 仲裁 SSOT / auto_guess / 真实 MCP 握手，全生效

---

## 📚 快速上手（Python）

```python
from collab_charter import Charter, Session

session = Session(Charter.load())

# 白名单自动沉淀 → 回流自检直接通过
out = session.handle("记录一下：先过闸再断言", auto_deposit_keys=("先过闸",))

# 真实 LLM 回调注入认知镜像
out = session.handle(
    "帮我重构这个模块",
    mirror_fn=lambda flows: "镜像：你的隐含诉求是低风险重构",
)
```

MCP 接入（推荐给 Agent 平台）：

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

---

## 🙏 致谢

感谢对内核的深度评审 —— 正是这些"站在作者角度挑不出、站在架构师角度必须改"的细节，
让这个版本从"很好"走向"可被信任地执行"。
