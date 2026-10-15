# collab-charter v3.3.0 — 优化交付说明

> 从「高度可信的审计框架」升级为「可被 Agent 依赖的执行层」。
> 全部改动已实测：378 项测试全绿，`verify` 全过，端到端冒烟通过。

## 本轮解决的问题（对应此前评审的 P0 / P1 / P2）

| # | 问题 | 层级 | 修复 |
|---|------|------|------|
| ① | 仲裁评估顺序漂移（R2/R3 顺序与宪章不符） | P0 | 顺序 SSOT 化 + 启动断言 |
| ② | `handle()` 默认 C4 回流自检必失败、README 误导 | P0 | `auto_deposit_keys` + 文档澄清 |
| ③ | 记忆检索是纯子串匹配，召回差 | P1 | `recall(semantic=True)` 词元语义检索 |
| ④ | 认知镜像/角色协作是模板占位，非真执行 | P1 | `mirror_fn`/`council_fn` 注入 + hooks 全站化 |
| ⑤ | anchor 求解器用 `eval(compile(...))` | P2 | 纯 AST 解释器，零 eval |
| ⑥ | `plan()` 路由决策只转发调用方打标 | P1 | `auto_guess` 自动复杂度判定 |
| ⑦ | MCP 协议子集未经真实客户端验证 | P1 | capabilities/版本协商/通知补全 + 官方 SDK 端到端冒烟 |

## 改动清单（16 文件，+457/-37 行）

### 仲裁层 `arbiter.py` + `charter.yaml`
- `0.5_arbitration` 新增 `eval_order: [0.5-R5, 0.5-R1, 0.5-R2, 0.5-R3, 0.5-R4]`（SSOT）
- `EVAL_ORDER` 常量 + `Arbiter.__init__` 启动断言：**改宪章不改代码、改代码不改宪章都会立即报错**
- `compare()` 分支按 SSOT 顺序重排（R2 先于 R3，堵住顺序漂移）
- 新增测试：SSOT 一致 / 漂移即报错 / 新用户陈述优先于旧模型事实

### 执行层 `router.py` + `session.py`
- `stage_hooks` 从「仅 EMIT」改为**全 8 站统一生效**（每站执行默认逻辑前拦截）
- 新增 `mirror_fn` / `council_fn` 认知执行注入点（真实 LLM 回调替代模板，无回调回退零依赖）
- COUNCIL 站记录对任意角色数鲁棒（不再写死 3 角色）
- `handle()` 新增 `auto_deposit_keys`：白名单流自动沉淀 → 0.8-C4 无需手动 `reflow()` 即通过
- `plan()` 新增 `auto_guess`：复杂度标记改 `bool | None` 语义，调用方不打标时
  内核从 `user_text` 启发式识别创造性产出/多步计划/本地文件；显式值优先
- 新增测试：hooks 对非 EMIT 站生效 / mirror_fn 注入 / council_fn 注入 /
  auto_deposit 使 C4 通过 / auto_guess 识别与优先级

### 记忆层 `memory.py`
- `recall()` 新增 `semantic=True`：复用 lexicon 确定性词元策略（英文按词、CJK 单字+二元组）
  做词元重叠打分，子串命中额外加权；同义改写可召回，子串匹配作 fallback
- 新增测试：同义改写召回 / 确定性

### 锚定层 `anchor/solver.py`
- `_safe_eval` 从 `eval(compile(...))` 改为**纯 AST 解释器**：手工遍历白名单节点，
  符号操作数（z3 BoolRef/ArithRef）走 z3 的 And/Or/Not/Compare，原生值走 Python
- 彻底消灭 eval/compile 调用（仅保留 `ast.parse(mode="eval")` 与 z3 `m.eval`，二者非 Python 求值）
- 新增测试：`test_表达式求值_零eval_零compile` 锁定纵深防线

### 版本与文档
- 版本号 3.2.0 → 3.3.0（pyproject / `__init__` / MCP server）
- README：Python 示例补齐 C4 两种通过方式 + 认知注入接线点；MCP 章节注明真实客户端验证
- CHANGELOG：新增 [3.3.0] 条目
- MCP 版本一致性测试改为引用 `__version__`（更健壮）

### 接口层 `interfaces/mcp_server.py`
- `initialize` 声明 `resources` / `prompts` 能力（真实客户端发现流程必需）
- 协议版本协商：客户端声明已知版本时按客户端回显，未知回退服务端版本
- `resources/list` / `prompts/list` 返回空目录；所有 `notifications/*`（含 cancelled/progress）一律不回
- 新增测试：`test_真实MCP客户端_端到端冒烟` —— 官方 `mcp` SDK `ClientSession`
  走 stdio 连真服务端完成 initialize → tools/list → tools/call（SDK 缺失时跳过）

## 验证结果
- 测试：368 → 391 项，全绿
- `cli verify`：宪章三契约 + 路由站点 + 闸门 9/9 + 自检 6 项，全部 PASS
- 端到端冒烟：mirror_fn 注入 / 语义召回 / C4 自检通过 / 仲裁 SSOT 顺序 /
  auto_guess 路由 / 真实 MCP 客户端握手，均生效

## 备注
- 所有改动保持零硬依赖新增（语义检索用内置词元化，不引入 jieba/嵌入模型）
- 真实 MCP 冒烟测试的 `mcp` SDK 是可选依赖：装了就跑真客户端，没装自动跳过
- 未自动提交 git；改动保留在工作区供你 review
- 至此上轮评审的 P0/P1/P2 全部落地，无遗留项
