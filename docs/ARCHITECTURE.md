# 架构设计

## 一句话

把《用户协作宪章》从一份**提示词文档**，变成 Agent **可加载、可调用、可验证**的执行层；
把《模块化特征簇标记语法》从一份**纯描述性规范**，变成**可证伪的检查与可复现的挖掘**。

## 仓库全景

```
collab-charter/
├── charter/            ① 宪章层 —— 规范本身（人读 + 机读双形态）
│   ├── CHARTER.md          人读版全文（v3.2，含第十一/十二章）
│   ├── charter.yaml        ★ 单一事实源：条款 id / 规则 / 裁决表
│   └── compact.md          精简版（字数受限的平台用）
│
├── knowledge/          ② 知识层 —— 字典/风格/亚文化语料（11.1）
│   ├── lexicon.yaml        136 条视觉词条（原 tools/fcslint/lexicon.yaml）
│   ├── styles.yaml          46 条风格域
│   └── subcultures.yaml    148 条互联网亚文化
│
├── src/collab_charter/ ③ 内核层 —— 把规则变成可执行的类
│   ├── charter_loader.py   加载 + 条款索引 + 章节访问
│   ├── flows.py            流与 8 个元数据标签（0.1 / 0.2）
│   ├── gates.py            安全闸门（0.3 第 1 站 / 第十章）
│   ├── router.py           八站管线 + 快速通道（0.3 / 0.9）
│   ├── arbiter.py          五级优先级 + 五条冲突规则（0.4 / 0.5）
│   ├── memory.py           沉淀 / 再激活 / 衰减 / 纠错（0.6）
│   ├── selfcheck.py        回流前六项自检（0.8）
│   ├── session.py          会话门面 + 工具注册
│   ├── cli.py              命令行（receipt/clauses/route/handle/verify/export/kb/mine/field/anchor）
│   ├── lexicon/            知识库与潜空间语义场（第十一章）
│   │   ├── kb.py               加载 / 断链校验 / digest / 检索
│   │   ├── vectors.py          向量征量空间：稀疏特征 + IDF + 上下文增益
│   │   ├── field.py            潜空间语义场：关联 / 中心性 / 社群 / 缺口
│   │   └── mine.py             深挖引擎：策略表 / 评分 / 分布权重 / 闸门
│   └── anchor/           符号锚定（第十二章，cognitive-anchor v2.0 并入）
│       ├── solver.py           z3 全枚举 + AST 白名单 + 多轮漂移检测
│       ├── cli.py              参数与 cognitive-anchor v2.0 完全兼容
│       └── __main__.py         python -m collab_charter.anchor
│
├── interfaces/         ④ 接口层 —— 让外部平台调用得到
│   └── mcp_server.py       零依赖 MCP server（14 个工具）
│
├── tools/              ⑤ 工具层
│   ├── fcslint/            特征簇 linter（解析器 + 9 条规则 + 评分器）
│   └── anchor/solve.py     cognitive-anchor 时代调用方式的兼容 shim
│
├── skills/             ⑥ 技能层 —— 让模型知道何时用、怎么用
│   ├── using-charter/          入口：技能发现与调用规则
│   ├── info-flow-protocol/     第〇章的可操作版
│   ├── feature-cluster-syntax/ 领域：图像提示词（含 3 个 references）
│   ├── deep-research/          认知：检索 / 对抗验证 / 证据账本
│   └── authoring-skills/       元：技能该怎么写
│
├── harnesses/          ⑦ 适配层 —— 投递到各平台
│   ├── claude-plugin/ codex-plugin/ cursor-plugin/   清单
│   ├── hooks/session-start                           会话注入
│   ├── tool-mapping.md                               ★ 动作 → 工具名
│   └── generic/AGENTS.md  gemini-cli/GEMINI.md       无钩子平台的兜底
│
└── tests/              ⑧ 验证层 —— 证明实现确实执行了条款
    ├── test_traceability.py  ★ 条款 ↔ 实现 ↔ 测试 双向追溯
    ├── test_lexicon.py       第十一章四件套（34 项）
    ├── test_anchor.py        第十二章求解器（28 项，含 cognitive-anchor 18 项断言）
    └── test_mcp.py           接口层（含 4 个新工具的端到端调用）
```

## 依赖关系（谁能 import 谁）

```
charter.yaml ──> charter_loader ──> flows / gates / router / arbiter
                                     │
                                     ├─> session ──> selfcheck
                                     │
knowledge/*.yaml ──> lexicon.kb ──> lexicon.vectors ──> lexicon.field
                                     │                    ▲
                                     └─> lexicon.mine ─────┘（mine 同时消费两者）
anchor.solver（独立：只依赖 z3，不依赖宪章其余部分；通过 cli/mcp 暴露）
```

两条纪律：

1. **知识不内联**（11.1-K1）：词条数据只进 `knowledge/*.yaml`。fcslint 的
   词库已从 `tools/fcslint/lexicon.yaml` 迁至 `knowledge/lexicon.yaml`
   （`rules.py` 解析式定位 + 旧路径回退，向后兼容）；
2. **条款是唯一权威**：任何行为变更先改 `charter.yaml`，代码只申报执行条款。

## 七个关键设计决策

### 决策 1：条款写成 YAML，而不是继续写在 Markdown 里

**问题**：宪章原文是散文体。代码要引用某条规则，只能硬编码字符串；宪章改了，
代码不知道。这正是被分析的四份材料共同的失败模式——**规范与实现必然脱节**。

**方案**：`charter/charter.yaml` 作为单一事实源，每条条款携带：

```yaml
- id: 0.5-R4                              # 全局唯一，可寻址
  statement: 同级同源冲突：并列呈现并标注分歧…   # 可判定的陈述
```

人读版 Markdown 与代码都引用它。三条 SSOT 契约写在 YAML 头部：
① 只能先改 YAML；② id 发布后不得复用或改写含义；③ 每条条款必须可判定。

**代价与取舍**：多了一次格式转换的维护成本。**但**这个成本换来的是可追溯性——
`test_traceability.py` 能机械验证「每条条款都有人执行」。对一份被四份材料反复
证明"文档会漂移"的项目来说，这是值得的。

### 决策 2：把「不变量」写成断言，而不是写成注释

宪章 0.3 规定了八个站点。如果代码里少了一个站，普通实现会静默运行。

本项目的做法是**启动即校验**：

```python
declared = [s["id"] for s in charter.section(..., "0.3_pipeline")["stages"]]
if declared != [s.value for s in PipelineStage]:
    raise CharterError("路由站点与宪章 0.3 不一致")
```

改宪章不改代码、或改代码不改宪章，都会**立刻报错**而不是悄悄跑偏。同样的手法
用于：闸门矩阵必须覆盖 9/9 组合、自检项必须与 0.8 一致、知识库断链即错、
MCP 工具数与版本号与内核一致。

### 决策 3：安全闸门用数据表，不用 if-else

敏感度 × 权限 = 9 种组合。写成 `if-else` 意味着**改行为要改代码**。

本项目把裁决表放进 `charter.yaml`：

```yaml
gate_matrix:
  - {sensitivity: 高危, permission: 禁外发, verdict: block}
```

`SafetyGate` 只做查表。宪章改一行，行为改一处。**未覆盖的组合按最保守处理并
显式说明**——绝不静默放行（这本身就是第十章的要求）。第十一章 11.4-M1 把同一
张表复用到知识库深挖：词条带 `sensitivity/permission` 元数据，命中非公开条目
必须输出闸门结论。

### 决策 4：技能正文不指名工具（三层投递模型）

来自 superpowers 的实测结论：一份技能要跑在 14 个平台上，只有一种写法可行。

| 层 | 内容 | 是否随平台变化 |
|---|---|---|
| 技能正文 | 「调用一次路由决策」「查一条条款」 | **不变** |
| 工具映射 | `harnesses/tool-mapping.md`：动作 → 该平台真实工具名 | 随平台**新增一列** |
| 引导注入 | `harnesses/hooks/session-start`：把入口技能塞进上下文 | 随平台**换格式** |

**不变量**：新增平台不改 `skills/` 与 `src/` 下任何文件。

### 决策 5：MCP server 零依赖

superpowers 在 `AGENTS.md` 里明写 "zero-dependency plugin by design"，理由是
依赖会让插件在陌生环境里装不上。

本项目沿用：`interfaces/mcp_server.py` 只用标准库实现 JSON-RPC over stdio，
**不引 `mcp` SDK**。代价是要自己写协议层（约 80 行），换来的是"把仓库拷到任何
沙箱都能直接跑"，不需要先建虚拟环境——这对 Agent 场景是决定性的。

唯一的例外是**符号锚定**：z3 求解器无法零依赖实现，因此设为**可选依赖**
（`pip install collab-charter[anchor]`）。未安装时内核其余部分不受影响，
`anchor_solve` 工具返回明确的安装指引而不是崩溃。

### 决策 6：向量空间用精确稀疏向量，不用 hashing trick

330 条知识规模下，工程上的诱惑是上个 hashing trick 了事。实测否定了这条路：

- blake2b 哈希到 1024 维后，**碰撞噪声可观测**——"赛璐璐"曾混进"谷圈"社群；
- 碰撞让"特征级归因"（11.2-V2）失真：归因到的特征根本不是原文特征。

改为**精确稀疏特征向量**（特征 → 权重字典）后：无碰撞、`feature_weights`
可直接当归因输出、`dimension` 随知识库自然增长。代价是内存随特征数线性增长
——330 条 × 数千特征完全不是问题，且诚实的边界写进了 `docs/SEMANTIC-FIELD.md`：
万级条目需要近似最近邻，当前实现不假装支持。

### 决策 7：cognitive-anchor 并入而非外挂

符号求解器最初是独立仓库（cognitive-anchor v2.0）。用户的要求是**两仓库功能
合一**，因此：

- 求解器原样移植为 `src/collab_charter/anchor/solver.py`，18 项内置断言
  与 pytest 共用同一份 `selftest_checks()`——两套验收不可能漂移；
- `tools/anchor/solve.py` 是兼容 shim，只转发不承载逻辑；
- 宪章新增第十二章把它的五条规则收编为条款（12.1-A1..A5），
  从此"AI 不得自行下最终判断"是有条款 id 的规则，不是README 里的一句劝告。

## 数据流：一次请求的完整路径

```
用户消息
   │
   ├─ Session.ask()                    记为输入流 × 指令流
   │
   ├─ Router.plan()                    0.9 路由决策
   │     ├─ 命中"快速"/L1 → 三站最小管线
   │     └─ 否则 → 八站全量
   │
   ├─ ① 安全闸门      SafetyGate.inspect_all()      0.3-I3 不过闸则终止
   ├─ ② 意图解析      按 FlowType 分组
   ├─ ③ 认知镜像      生成"我理解你要的是 X，对吗？"  0.3-I2 强制节点
   ├─ ④ 记忆检索      MemoryStore.recall()          0.6-O2 带元数据还原
   ├─ ⑤ 角色协作      建构者/质疑者/验证者             7-R3    标记 internal_only
   ├─ ⑥ 综合裁决      Arbiter.arbitrate()           0.4/0.5 每条结论带 clause
   ├─ ⑦ 输出         过滤 internal_only + 低置信补标  0.7-R3
   └─ ⑧ 反馈回流     MemoryStore.deposit()/decay()  0.3-I1 否则开环
   │
   ├─ SelfCheckRunner.run()            0.8 六项自检（仅全量路由）
   │
   └─ SessionOutcome                   text / trace / tiebreak / selfcheck / degraded
```

## 特征簇 linter 为什么值得单独存在

它把一份**纯粹描述性的规范**（特征簇总纲）变成了**可证伪的检查**：

| 规范条文 | 原来是 | 现在是 |
|---|---|---|
| 2.1 六大簇封闭集 | 一句要求 | `FCS001` 报出所有未归类词条 |
| 9.1 权重区间 0.5–1.4 | 一句要求 | `FCS002` 报出越界词条与具体数值 |
| 3.4 抽象词条须少于实体 | 一句要求 | `FCS005` 报出两者计数 |
| 8.3 直接冲突必须删除其一 | 一句要求 | `FCS004` 报出冲突词对 |
| 8.3 跨域冲突需标记 | 一句要求 | `FCS009` 报出异源词对 |
| 5.4 控制力量化 | 四项维度描述 | 四项实际打分 + 明细 + A/B/C/D 分档 |
| 5.2 簇结构保留优化 | 五步流程描述 | 生成**同范式**优化稿（重排/降权/删无效项/补锚点） |

**关键克制**：工具只报"可能与顺序形成的隐性权重不一致"，不替创作者做判决。
依据第 11 章禁止项 5——"禁止直接删除用户核心创作意图对应的词条"。

## 两个 v3.2 子系统速览

深度说明见专门文档，这里只给定位：

| 子系统 | 一句话 | 文档 |
|---|---|---|
| 知识库 + 潜空间语义场 | 330 条知识的可扩容知识库，配确定性向量空间、分布权重与网络分析；回答"该带哪些词条、各占多少、哪些需求还没人接" | [SEMANTIC-FIELD.md](SEMANTIC-FIELD.md) |
| 符号锚定 | 多条件权衡交给 z3 全枚举硬算；AST 白名单防逃逸、档位投票出结论、多轮漂移必须提示 | 本文件决策 7 + `src/collab_charter/anchor/solver.py` 文档字符串 |

## 诚实的边界

| 边界 | 说明 |
|---|---|
| 词库覆盖率 | 330 条，遇到 `FCS001` 仍需人工判定；程序不猜（6.6 禁止静默过滤） |
| 语义理解 | 规则基于词典子串匹配与 n-gram 统计，不做语义模型推理；同义改写可能漏检（详见 SEMANTIC-FIELD.md §7） |
| 向量空间规模 | 精确稀疏向量在千条级从容，万级需近似最近邻——未实现，不假装支持 |
| 参考图反向工程 | 仅留接口位（12.2），需视觉能力，不在纯文本内核范围内 |
| 真实并行 | 三角视角在无子代理能力的平台上串行执行，已登记降级 |
| 在线语料 | 11.4-M2 只定义闸门口径，实时语料检索未实现；`allow_online` 只产生报告 |
| z3 依赖 | 符号锚定为可选依赖；未安装时该工具不可用，内核其余部分正常 |
