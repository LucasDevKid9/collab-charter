# 🚀 collab-charter v3.3.0 — Release Notes

- **版本**：v3.3.0（宪章 v3.2 对应）
- **发布日期**：2026-10
- **仓库**：https://github.com/LucasDevKid9/collab-charter
- **一句话**：从「高度可信的审计框架」升级为「可被 Agent 依赖的执行层」——评审发现的 P0/P1/P2 全部落地，并已通过真实 MCP 客户端端到端验证。

---

## 🎯 这个版本解决的核心问题

之前的内核是"审计壳"：规则很严、验证很全，但**几个关键环节要么只是打标记、要么只转发外部判断**。v3.3.0 把它们全部补齐，让内核真正可被 Agent 信任地执行。

| 维度 | v3.2 的局限 | v3.3.0 的答案 |
|------|------------|--------------|
| 🧭 仲裁 | 规则顺序硬编码，改宪章可能悄悄跑偏 | 顺序写进宪章 SSOT + 启动断言，**双向锁死零漂移** |
| 🧠 认知 | 镜像/协作只是模板占位，不产出真认知 | `mirror_fn`/`council_fn` 真实 LLM 回调注入，模板兜底 |
| 💾 记忆 | 纯子串匹配，同义改写漏检 | 词元语义召回，`semantic=True` 一键开启 |
| 🛡 安全 | 求解器用 `eval()`，依赖"白名单信任" | 纯 AST 解释器，**零 eval**，纵深防御到底 |
| 🔌 接入 | MCP 手写子集，未在真客户端验证 | 官方 `mcp` SDK 端到端冒烟，Claude Code 可握手 |
| 🧭 路由 | 只转发调用方打标，自己不判断 | `auto_guess` 从文本自动识别任务复杂度 |

---

## 📦 变更明细

### 1. 仲裁层 — 零漂移（0.5）
- `charter.yaml` 的 `0.5_arbitration` 新增 **`eval_order: [R5, R1, R2, R3, R4]`**，成为唯一事实源
- `Arbiter.__init__` 新增启动断言：**改宪章不改代码、或改代码不改宪章，都立即报错**
- 修复 R2（时效）与 R3（来源）的执行顺序漂移，并补了"新用户陈述 vs 旧模型事实"的分歧用例
- 新增测试：SSOT 一致性 / 漂移即报错 / 顺序行为

### 2. 执行层 — 真正可执行（0.3 / 0.7）
- `stage_hooks`：从「仅 EMIT 生效」改为 **8 站统一生效**，任意站点可拦截
- 新增 **`mirror_fn`**：真实模型回调替代认知镜像模板（隐含诉求拆解）
- 新增 **`council_fn`**：真实三角视角（建构/质疑/验证）替代模板占位
- COUNCIL 站记录对任意角色数鲁棒，不再写死 3 角色
- `handle()` 新增 **`auto_deposit_keys`**：白名单流自动沉淀，0.8-C4 回流自检无需手动 `reflow()`

### 3. 路由层 — 自主判断（0.9）
- `plan()` 新增 **`auto_guess`**：复杂度标记改 `bool | None` 语义
  - `None` = 调用方未表态 → 内核从 `user_text` 启发式识别（创造性/多步/本地文件）
  - 显式 `True`/`False` 优先，不与猜测叠加
- 纯规则、确定性、零模型依赖

### 4. 记忆层 — 语义召回（0.6）
- `recall(semantic=True)`：复用 lexicon 确定性词元策略（英文按词、CJK 单字+二元组）
- 同义改写可召回（"把模块重构掉" → 命中"重构模块"），子串命中额外加权
- 子串匹配作 fallback，保持向后兼容

### 5. 锚定层 — 零 eval（12.1）
- `_safe_eval` 从 `eval(compile(...))` 改为 **纯 AST 解释器**：手工遍历白名单节点
- 符号操作数（z3 BoolRef/ArithRef）走 z3 的 And/Or/Not/Compare；原生值走 Python
- 彻底消灭 eval/compile 调用，新增 `test_表达式求值_零eval_零compile` 锁定

### 6. 接口层 — 真客户端可握手（MCP）
- `initialize` 声明 `resources` / `prompts` 能力（真实客户端发现流程必需）
- **协议版本协商**：客户端声明已知版本按客户端回显，未知回退服务端版本
- `resources/list` / `prompts/list` 返回空目录
- 所有 `notifications/*`（含 cancelled/progress）一律正确不回
- 新增 **`test_真实MCP客户端_端到端冒烟`**：官方 `mcp` SDK `ClientSession` 走 stdio，
  完整跑通 initialize → tools/list → tools/call（SDK 缺失时自动跳过）

---

## 🧪 质量验证

| 项目 | 结果 |
|------|------|
| 自动化测试 | **391 项，全绿**（v3.2 为 368） |
| `cli verify` | 三契约 + 路由站点 + 闸门 9/9 + 自检 6 项，**全部 PASS** |
| 端到端冒烟 | mirror_fn 注入 / 语义召回 / C4 自检 / 仲裁 SSOT / auto_guess / 真实 MCP 握手，**全部生效** |
| 依赖 | 零新增硬依赖；`mcp` SDK、`z3-solver` 均为可选 |

---

## 🚀 快速上手

### Python

```python
from collab_charter import Charter, Session

session = Session(Charter.load())

# 白名单自动沉淀 → 回流自检直接通过
out = session.handle("记录一下：先过闸再断言", auto_deposit_keys=("先过闸",))
assert out.selfcheck.passed

# 真实 LLM 回调注入认知镜像 / 三角视角
out = session.handle(
    "帮我重构这个模块",
    mirror_fn=lambda flows: "镜像：你的隐含诉求是低风险重构",
    council_fn=lambda flows: my_llm_council(flows),
)
```

### MCP（推荐给 Agent 平台）

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

零依赖实现 JSON-RPC over stdio，拷到任何沙箱都能跑，**并已通过官方 mcp SDK 真客户端验证**。

---

## 📚 文件变动总览

```
charter/charter.yaml              # 0.5 新增 eval_order（SSOT）
src/collab_charter/arbiter.py     # EVAL_ORDER + 启动断言 + 顺序重排
src/collab_charter/router.py      # hooks 全站化 + mirror/council 注入 + auto_guess
src/collab_charter/session.py     # auto_deposit_keys + None 语义透传
src/collab_charter/memory.py      # semantic=True 词元语义检索
src/collab_charter/anchor/solver.py  # 纯 AST 解释器（零 eval）
interfaces/mcp_server.py          # capabilities + 版本协商 + 通知处理
README.md / CHANGELOG.md          # 文档同步
tests/*                           # 新增 23 项测试（368 → 391）
```

---

## 🙏 致谢

感谢对内核的深度评审——正是这些"作者视角挑不出、架构师视角必须改"的细节，
让这个版本从"很好"走向"可被信任地执行"。
