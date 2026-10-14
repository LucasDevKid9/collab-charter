# 架构设计

## 一句话

把《用户协作宪章》从一份**提示词文档**，变成 Agent **可加载、可调用、可验证**的执行层。

## 六层结构

```
collab-charter/
├── charter/            ① 宪章层 —— 规范本身（人读 + 机读双形态）
│   ├── CHARTER.md          人读版全文
│   ├── charter.yaml        ★ 单一事实源：条款 id / 规则 / 裁决表
│   └── compact.md          精简版（字数受限的平台用）
│
├── src/collab_charter/ ② 内核层 —— 把规则变成可执行的类
│   ├── charter_loader.py   加载 + 条款索引 + 章节访问
│   ├── flows.py            流与 8 个元数据标签（0.1 / 0.2）
│   ├── gates.py            安全闸门（0.3 第 1 站 / 第十章）
│   ├── router.py           八站管线 + 快速通道（0.3 / 0.9）
│   ├── arbiter.py          五级优先级 + 五条冲突规则（0.4 / 0.5）
│   ├── memory.py           沉淀 / 再激活 / 衰减 / 纠错（0.6）
│   ├── selfcheck.py        回流前六项自检（0.8）
│   ├── session.py          会话门面 + 工具注册
│   └── cli.py              命令行
│
├── interfaces/         ③ 接口层 —— 让外部平台调用得到
│   └── mcp_server.py       零依赖 MCP server（10 个工具）
│
├── skills/             ④ 技能层 —— 让模型知道何时用、怎么用
│   ├── using-charter/          入口：技能发现与调用规则
│   ├── info-flow-protocol/     第〇章的可操作版
│   ├── feature-cluster-syntax/ 领域：图像提示词（含 3 个 references）
│   ├── deep-research/          认知：检索 / 对抗验证 / 证据账本
│   └── authoring-skills/       元：技能该怎么写
│
├── harnesses/          ⑤ 适配层 —— 投递到各平台
│   ├── claude-plugin/ codex-plugin/ cursor-plugin/   清单
│   ├── hooks/session-start                           会话注入
│   ├── tool-mapping.md                               ★ 动作 → 工具名
│   └── generic/AGENTS.md  gemini-cli/GEMINI.md       无钩子平台的兜底
│
└── tests/              ⑥ 验证层 —— 证明实现确实执行了条款
    └── test_traceability.py  ★ 条款 ↔ 实现 双向追溯
```

## 五个关键设计决策

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
用于：闸门矩阵必须覆盖 9/9 组合、自检项必须与 0.8 一致。

### 决策 3：安全闸门用数据表，不用 if-else

敏感度 × 权限 = 9 种组合。写成 `if-else` 意味着**改行为要改代码**。

本项目把裁决表放进 `charter.yaml`：

```yaml
gate_matrix:
  - {sensitivity: 高危, permission: 禁外发, verdict: block}
```

`SafetyGate` 只做查表。宪章改一行，行为改一处。**未覆盖的组合按最保守处理并
显式说明**——绝不静默放行（这本身就是第十章的要求）。

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

`SessionOutcome.trace` 就是"讲思路"时逐站展开的材料；`degraded` 就是第一章 1-C2
要求显式声明的"哪些条款我执行不了 + 降级方案"。

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

## 诚实的边界

| 边界 | 说明 |
|---|---|
| 词库覆盖率 | 约 150 条，遇到 `FCS001` 需人工判定；程序不猜（6.6 禁止静默过滤） |
| 语义理解 | 规则基于词典子串匹配，不做语义模型推理；同义改写可能漏检 |
| 参考图反向工程 | 仅留接口位（12.2），需视觉能力，不在纯文本内核范围内 |
| 真实并行 | 三角视角在无子代理能力的平台上串行执行，已登记降级 |
