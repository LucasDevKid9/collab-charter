# collab-charter · 协作宪章执行内核

> 把《用户协作宪章》从一份**提示词文档**，变成 Agent **可加载、可调用、可验证**的执行层。

**90 条条款 · 8 站管线 · 14 个 MCP 工具 · 368 项测试 · 条款↔实现双向追溯 · 330 条知识库**

---

## 这是什么

一份写在 Markdown 里的协作规范，模型只能"尽力遵守"。本项目把它**编译成能跑的东西**：

| 宪章原文 | 在本项目中 |
|---|---|
| 0.3 路由管线（八站） | `Router` 类——站点集合由断言锁死在宪章上，改一边不改另一边直接报错 |
| 0.4 五级优先级 / 0.5 五条冲突规则 | `Arbiter` 类——每次裁决返回**依据条款 id**，可回溯 |
| 第十章 安全闸门 | `charter.yaml:enforcement.gate_matrix`（3×3 全组合）+ `SafetyGate` 查表执行 |
| 0.6 记忆流（沉淀/再激活/衰减） | `MemoryStore`——带半衰期的置信度衰减、纠正留痕、JSON 落盘 |
| 0.8 回流前自检（六项） | `SelfCheckRunner`——每项返回可断言的 `passed` 与失败详情 |
| 第十一章 知识库与语义场 | `knowledge/*.yaml`（330 条）+ `lexicon` 四件套：确定性向量征量空间、分布权重、潜空间语义场网络分析 |
| 第十二章 符号锚定 | `anchor` 包（cognitive-anchor v2.0 并入）：z3 全枚举、AST 白名单、多轮漂移检测 |
| —— | 外加：把图像提示词规范 `<模块化特征簇标记语法>` 也做成了可执行的诊断器 |

**一句话**：宪章不再是一段"请遵守"的文字，而是一个能被 `curl`、能被 MCP 调用、
能被测试断言、能在改坏时立刻报错的系统。

## 快速开始

### 1. 命令行（零安装）

```bash
git clone https://github.com/LucasDevKid9/collab-charter && cd collab-charter

# 会话开始：第一章要求的接收自检（≤3 行）
PYTHONPATH=src python3 -m collab_charter.cli receipt

# 这次该走全量还是快速通道？
PYTHONPATH=src python3 -m collab_charter.cli route "帮我重构这个模块"
# → Route(全量): 安全闸门 → 意图解析 → 认知镜像 → 记忆检索 → 角色协作 → 综合裁决 → 输出 → 反馈回流

# 跑完整管线，看逐站轨迹 + 输出 + 自检结论
PYTHONPATH=src python3 -m collab_charter.cli handle "重构这个模块" --constraint 保持API兼容

# 查任意条款原文（「查来源」用）
PYTHONPATH=src python3 -m collab_charter.cli clause 0.5-R4

# 宪章完整性自检
PYTHONPATH=src python3 -m collab_charter.cli verify

# 知识库摘要（第十一章：词条数 / 断链 / 跨文件同名 / 未验证）
PYTHONPATH=src python3 -m collab_charter.cli kb

# 语义场深挖：加权词条 + 分布权重 + 闸门结论 + 覆盖缺口
PYTHONPATH=src python3 -m collab_charter.cli mine "谷圈 痛包 晒谷" --state 收敛期

# 潜空间语义场：关联网络 / 中心性 / 社群 / 缺口
PYTHONPATH=src python3 -m collab_charter.cli field "谷圈 痛包 晒谷" --state 收敛期

# 符号锚定：多条件权衡交给 z3 硬算（需 pip install z3-solver）
PYTHONPATH=src python3 -m collab_charter.anchor \
  --declare "x:可行性,y:预算充足,z:时间允许,w:风险可控" \
  --constraints "x+y+z+w>=3; Implies(y==0,w==1)" \
  --decisions "做:x+y+z+w>=4; 观望:x+y+z+w==3; 不做:x+y+z+w<3" \
  --rounds "|y==0"
```

### 2. Python

```python
from collab_charter import Charter, Session
from collab_charter.flows import user_instruction, model_speculation

session = Session(Charter.load())
session.register_tool(ToolSpec("web_search", "联网检索", my_search_fn, {"q": {"type": "string"}}))

session.ask("帮我查一下 z3 的最新技术选型")
session.call_tool("web_search", q="z3 solver 2024")
out = session.handle("顺便评估下迁移成本", constraints=["不能停机"])

print(out.text)         # 输出
print(out.trace)        # 逐站轨迹（「讲思路」时展开）
print(out.explain_failures())  # 自检没通过时说清楚哪里没通过
```

### 3. MCP（推荐给 Agent 平台）

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

零依赖（只用标准库实现 JSON-RPC over stdio），拷到任何沙箱都能直接跑。
**14 个工具**：条款查询 / 通览 / 接收自检 / 路由决策 / 管线执行 / 冲突裁决 /
安全闸门 / 提示词诊断 / 记忆沉淀 / 记忆检索 / 符号锚定求解 / 知识库检索 /
语义场深挖 / 潜空间语义场。

（`anchor_solve` 需要可选依赖 `z3-solver`：`pip install collab-charter[anchor]`；
未安装时返回明确安装指引，不影响其余 13 个工具。）

### 4. 特征簇提示词诊断

```bash
PYTHONPATH=tools python3 -m fcslint "古早立绘，半身像，赛璐璐平涂，16-bit indexed color，硬边缘，4:3"
```

输出六大功能簇归类、权重梯度偏离、冲突清单、控制力量化评分（0–100）、
以及**同范式的簇结构保留优化稿**（重排 / 降权 / 删无效项 / 补锚点）。
词库已升级为可扩容知识库（`knowledge/`，330 条），诊断与深挖共用同一份数据。

## 项目结构

```
charter/           ① 宪章层   CHARTER.md（人读） · charter.yaml（★单一事实源） · compact.md（精简版）
knowledge/         ② 知识层   lexicon.yaml · styles.yaml · subcultures.yaml（330 条，11.1）
src/collab_charter/ ③ 内核层  flows · gates · router · arbiter · memory · selfcheck · session · cli
                              · lexicon/（知识库四件套） · anchor/（符号求解器）
interfaces/        ④ 接口层   mcp_server.py（零依赖 MCP，14 工具）
tools/             ⑤ 工具层   fcslint/（特征簇诊断） · anchor/solve.py（兼容 shim）
skills/            ⑥ 技能层   using-charter · info-flow-protocol · feature-cluster-syntax
                              · deep-research · authoring-skills
harnesses/         ⑦ 适配层   claude/codex/cursor 清单 · session-start 钩子 · tool-mapping.md
tests/             ⑧ 验证层   368 项测试，含条款↔实现双向追溯
docs/              ANALYSIS · ARCHITECTURE · SEMANTIC-FIELD · TRACEABILITY
```

## 四个值得一看的设计

**① 单一事实源 + 双向追溯。** 条款只写在 `charter/charter.yaml`，每条有全局唯一 id。
代码申报"我执行哪些条款"，测试机械验证"条款真实存在 → 模块真实存在 → 有指名测试"，
并做**反向检查**——不允许声明实现一个宪章里不存在的条款。
见 [docs/TRACEABILITY.md](docs/TRACEABILITY.md)。

**② 把不变量写成断言，而不是注释。** 宪章 0.3 规定了八个站点。如果代码里少一个站，
普通实现会静默跑偏；本项目**启动即校验**，不一致直接抛错。同样手法用于闸门矩阵覆盖度、
自检项一致性、知识库断链、MCP 工具数。

**③ 技能正文不指名工具。** 技能只写动作（「查一条条款」），平台差异收敛到
[harnesses/tool-mapping.md](harnesses/tool-mapping.md) 一张映射表。
新增平台**不修改任何技能与源码**——这是本项目最重要的不变式。

**④ 确定性优先于聪明。** 向量空间不用 hashing trick（330 条规模下碰撞噪声可观测），
社群划分不用随机初始化，空间按任务临时建构用后即弃。一切为了 11.2-V1：
同输入 → 同输出 → 可复现、可审计。见 [docs/SEMANTIC-FIELD.md](docs/SEMANTIC-FIELD.md)。

## 平台接入

| 平台 | 接入方式 |
|---|---|
| Claude Code | `harnesses/claude-plugin/`（含 `mcpServers` 字段，装即用） |
| Codex | `harnesses/codex-plugin/` |
| Cursor | `harnesses/cursor-plugin/` + `hooks/hooks.json` |
| Gemini CLI | `harnesses/gemini-cli/GEMINI.md`（无钩子平台的兜底） |
| 其他 / 自研 Agent | `harnesses/generic/AGENTS.md` + `tool-mapping.md` |

各平台能力缺口与降级方案（无记忆 / 无文件访问 / 无联网 / 无子代理）见
[tool-mapping.md](harnesses/tool-mapping.md)。

## 测试

```bash
python3 -m pytest -q                              # 368 项
python3 -m pytest tests/test_traceability.py -v   # 条款追溯
PYTHONPATH=src python3 -m collab_charter.cli verify
```

依赖：Python ≥ 3.9，`pyyaml`（仅此一项；MCP server 与 fcslint 核心零依赖）。
`fastapi`/`uvicorn` 为可选（HTTP 接口）；`z3-solver` 为可选（符号锚定，
`pip install collab-charter[anchor]`）。

## 文档

- [docs/ANALYSIS.md](docs/ANALYSIS.md) —— 对 superpowers / cognitive-core / 特征簇总纲 / 协作宪章
  四份材料的**实证式深度分析**与缺陷清单（按 P0–P3 分级），以及本项目的自我约束
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) —— 七个关键设计决策、备选方案取舍、诚实边界
- [docs/SEMANTIC-FIELD.md](docs/SEMANTIC-FIELD.md) —— 知识库 / 向量征量空间 / 分布权重 /
  潜空间语义场的深度说明与诚实边界
- [docs/TRACEABILITY.md](docs/TRACEABILITY.md) —— 90 条条款逐条归属（代码执行 / 技能承载）

## 许可

MIT，见 [LICENSE](LICENSE)。

---

## English

**collab-charter** turns a Chinese-language *user-side collaboration charter* from a
prompt document into an executable layer for AI agents.

- **90 clauses** with globally unique, addressable IDs in a single source of truth
  (`charter/charter.yaml`); human-readable text and code both reference it.
- **8-stage pipeline** (safety gate → intent → mirror → recall → council → adjudicate →
  emit → reflow) with a fast path for trivial requests.
- **Deterministic conflict arbitration** with 5-level priority, every verdict citing its clause.
- **Safety gate** as a data table (sensitivity × permission), executed, not hard-coded.
- **330-entry knowledge base** (dictionary / styles / internet subcultures) with a
  deterministic sparse measure space, distribution weights, and latent-field network
  analysis — see `docs/SEMANTIC-FIELD.md`.
- **Symbolic anchoring** (cognitive-anchor v2.0 merged in): z3 full enumeration,
  AST whitelist sandbox, multi-round drift detection.
- **14 MCP tools**, zero third-party dependencies (stdlib JSON-RPC over stdio).
- **368 tests**, including bidirectional clause↔implementation traceability.
- Skills describe *actions*, never tool names; per-platform differences live in one
  mapping table, so adding a platform touches no skill or source file.

Use it to give any agent a consistent, auditable, verifiable collaboration protocol —
and to lint image-generation prompts against a formal feature-cluster grammar.
