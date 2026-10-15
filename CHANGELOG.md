# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
版本号与宪章版本对齐：内核 `3.2.x` 对应宪章 `v3.2`。

## [3.3.0] — 2026-10

从「高度可信的审计框架」升级为「可被 Agent 依赖的执行层」：
补齐全部站点执行注入、仲裁零漂移、记忆语义召回、求解器零 eval 纵深防御。

### 仲裁层（0.5）
- `arbiter.py` —— 冲突裁决评估顺序 SSOT 化：`charter.yaml` 新增 `0.5_arbitration.eval_order`
  （R5→R1→R2→R3→R4），`Arbiter.__init__` 启动断言校验代码实现与宪章一致，
  改宪章不改代码、或改代码不改宪章都会立即报错（堵住 R2/R3 顺序漂移）
- 新增测试：`test_评估顺序与宪章SSOT一致` / `test_评估顺序漂移时立即报错` /
  `test_新用户陈述优先于旧模型事实`

### 执行层（0.3 / 0.7）
- `router.py` —— `stage_hooks` 从「仅 EMIT 生效」改为**全 8 站统一生效**；
  新增 `mirror_fn` / `council_fn` 认知执行注入点（真实 LLM 回调替代模板，
  无回调回退零依赖模板）；COUNCIL 站记录对任意角色数鲁棒
- `router.py` —— `plan()` 新增 `auto_guess` 自动任务复杂度判定：复杂度标记
  改为 `bool | None` 语义（None=未表态→文本启发式补位，显式 True/False 优先），
  调用方不打标时内核也能从 user_text 识别创造性产出/多步计划/本地文件
- `session.py` —— `handle()` 新增 `auto_deposit_keys` 白名单自动沉淀，
  使 0.8-C4 回流自检无需手动 `reflow()` 即可通过（安全闸语义不变）；
  复杂度标记透传 None 语义
- README 更新 Python 示例，明确 C4 的两种通过方式与认知注入接线点

### 记忆层（0.6）
- `memory.py` —— `recall()` 新增 `semantic=True` 词元重叠语义检索
  （复用 lexicon 确定性词元策略），同义改写可召回；子串匹配作 fallback

### 锚定层（12.1）
- `anchor/solver.py` —— `_safe_eval` 从 `eval(compile(...))` 改为**纯 AST 解释器**
  （手工遍历白名单节点，符号操作数走 z3 And/Or/Not/Compare），彻底消灭 eval/compile
- 新增测试：`test_表达式求值_零eval_零compile`

### 接口层（MCP）
- `interfaces/mcp_server.py` —— 协议补全：`initialize` 声明 resources/prompts 能力、
  协议版本按客户端声明回显协商、`resources/list` / `prompts/list` 返回空目录、
  所有 `notifications/*` 通知一律不回（含 cancelled/progress）
- 新增测试：真实 `mcp` SDK `ClientSession` 走 stdio 端到端冒烟
  （initialize → tools/list → tools/call，SDK 缺失时跳过）

### 验证
- 测试 368 → 391 项，全绿；`verify` 全过

## [3.2.0] — 2026-10

宪章 v3.2：新增第十一章「知识库与语义场」与第十二章「符号锚定」；
cognitive-anchor v2.0 求解器并入本仓库；词库升级为可扩容知识库。

### 宪章层
- `charter/charter.yaml` —— 条款数 73 → 90；新增第十一章（11.1-K1..K3 / 11.2-V1..V3 /
  11.3-F1..F3 / 11.4-M1..M3，共 13 条）与第十二章（12.1-A1..A5，共 5 条）
- `charter/CHARTER.md` —— 人读版同步新增两章
- `charter/compact.md` —— MCP 工具数 10 → 14

### 知识层（新增，第十一章）
- `knowledge/lexicon.yaml` —— 由 `tools/fcslint/lexicon.yaml` 迁入（git mv 保留历史），
  136 条；fcslint 以解析式定位 SSOT，旧路径回退兼容
- `knowledge/styles.yaml` —— 46 条风格域（覆盖 lexicon style_domain_terms 全部 15 词并扩展）
- `knowledge/subcultures.yaml` —— 148 条互联网亚文化（meme / slang / register /
  community / practice 五类，带 gloss / register / era / platforms / fcs_hint /
  source / confidence；「开盒」「人肉搜索」标 高危/禁外发 演示 11.4-M1 闸门）
- 全库 330 条；related/conflicts 断链即错；跨文件同名词检出；未验证条目名单

### 内核层 · lexicon 包（新增）
- `lexicon/kb.py` —— 多文件加载（零代码扩容）、断链校验、digest、检索、统计
- `lexicon/vectors.py` —— 向量征量空间：精确稀疏特征向量（放弃 hashing trick，
  330 条规模下碰撞噪声可观测）、四层特征体系（词元 1.0 / 单字 0.35 / 元特征 0.6 /
  释义 0.35）+ IDF + 上下文增益 1.6、查询侧词表前向最大匹配分词、
  空间指纹 = sha256(版本|kb digest|上下文 digest)、任务期临时建构用后即弃
- `lexicon/field.py` —— 潜空间语义场：关联网络（cosine≥0.10 + related 显式边 0.5 +
  conflicts 断边）、幂迭代中心性（60 轮均匀初始化确定性）、标签传播社群
  （中心性降序→id 升序固定更新）、覆盖缺口（停用字过滤）、密度+模块度
- `lexicon/mine.py` —— 深挖引擎：语义状态策略表（探索/发散/收敛/聚焦/创意/校验 +
  中性回落）、评分 = 相似度×先验×域增益×类型增益 + 探索期覆盖加分、MMR 去重选择、
  跨文件同词条去重、invalid 剔除、分布权重（11.2-V2）、特征级归因、
  3×3 闸门结论（11.4-M1）、在线扩容只报不执行（11.4-M2）

### 内核层 · anchor 包（新增，cognitive-anchor v2.0 并入）
- `anchor/solver.py` —— z3 全枚举求解器原样移植：AST 白名单沙箱（阻断属性访问 /
  Lambda / 下标等逃逸）、全角归一化、档位投票、变量频率、分支博弈表、
  多轮漂移检测；schema 保持 `cognitive-anchor.solve/2.0` 兼容
- `anchor/cli.py` + `anchor/__main__.py` —— 参数与原仓库 `scripts/solve.py` 完全兼容
- `tools/anchor/solve.py` —— 兼容 shim（只转发，不承载逻辑）
- z3-solver 设为可选依赖：`pip install collab-charter[anchor]`
- 18 项内置断言与 pytest 共用 `selftest_checks()`，两套验收不可能漂移

### 接口层
- MCP 工具 10 → 14：新增 `anchor_solve` / `lexicon_search` / `lexicon_mine` /
  `semantic_field`；SERVER_VERSION 3.1.0 → 3.2.0

### CLI
- 新增子命令 `kb` / `mine` / `field` / `anchor`

### 验证层
- 测试 266 → 368：新增 `test_lexicon.py`（34 项）、`test_anchor.py`（28 项）、
  `test_mcp.py` 增补 7 项（含 4 个新工具端到端调用与版本一致性）
- `test_traceability.py` 接入 17 条新条款的「条款→模块→测试」映射；
  可执行条款类型集扩展 K/F/M/A；模块路径支持包子模块（lexicon.kb / anchor.solver）

### 文档
- 新增 `docs/SEMANTIC-FIELD.md` —— 知识库 / 向量征量空间 / 分布权重 / 潜空间语义场的
  深度说明与诚实边界
- 重写 `docs/ARCHITECTURE.md` —— 七层仓库全景、依赖关系图、七个关键设计决策
- README / TRACEABILITY / tool-mapping 同步更新

### 已知边界（不掩盖）
- 语义理解基于词典子串与 n-gram 统计，无神经嵌入；同义改写可能漏检
- 精确稀疏向量在千条级从容，万级需近似最近邻——未实现，不假装支持
- 在线语料检索未实现（11.4-M2 只定义闸门口径）；`allow_online` 只产生报告
- z3 为可选依赖：未安装时符号锚定工具不可用，内核其余部分正常

## [3.1.0] — 2026-10-14

首个发布版本。把《用户协作宪章》v3.1 与其配套规范做成可执行的 Agent 工具包。

### 宪章层
- `charter/charter.yaml` —— 单一事实源，73 条条款，每条带全局唯一 id 与可判定陈述
- `charter/CHARTER.md` —— 人读版全文（十一章节 + 精简版链接）
- `charter/compact.md` —— 精简版，供字数受限的入口使用
- 补齐原宪章缺失的裁决数据：安全闸门 3×3 全组合矩阵、各章条款 id

### 内核层（`collab_charter`）
- `charter_loader` —— 条款索引、章节访问、关键词检索；三条 SSOT 契约强制校验
- `flows` —— 0.1 七分层 × 七类型、0.2 八个元数据标签
- `gates` —— 0.3 第 1 站；裁决表从宪章读入，未覆盖组合按最保守处理
- `router` —— 八站管线 + 0.9 快速通道；站点集合与宪章 0.3 不一致时启动即报错
- `arbiter` —— 0.4 五级优先级、0.5 五条冲突规则；每次裁决返回依据条款 id
- `memory` —— 0.6 三操作；半衰期衰减（1h / 7d / 不衰减）、纠正留痕、JSON 落盘
- `selfcheck` —— 0.8 六项自检，每项返回可断言的 `passed` 与失败详情
- `session` —— 会话门面、工具注册、快捷词（第九章）、第一章接收自检
- `cli` —— `receipt` / `clauses` / `clause` / `route` / `handle` / `verify` / `export`

### 接口层
- `interfaces/mcp_server.py` —— 零依赖 MCP server（标准库 JSON-RPC over stdio），10 个工具

### 特征簇诊断器（`fcslint`）
- 解析器：逗号唯一分隔符、括号深度感知、全角标点容错、权重与簇标记
- 规则引擎：11 条规则（FCS001–FCS011），每条挂依据条款
- 控制力量化：四维加权评分 + A/B/C/D 分档 + 明细
- 簇结构保留优化：按四层模型重排 / 抽象降权 / 删无效项 / 补锚点，**不改为叙事长句**
- 词条知识库（`lexicon.yaml`）：约 150 条，含直接冲突对与跨域冲突对

### 技能层
- `using-charter` · `info-flow-protocol` · `feature-cluster-syntax`（+3 个 references）
  · `deep-research` · `authoring-skills`

### 适配层
- `claude-plugin` / `codex-plugin` / `cursor-plugin` 清单（含 `mcpServers`）
- `hooks/session-start` —— 会话注入，按平台输出对应 JSON 字段
- `tool-mapping.md` —— 动作 → 工具名映射 + 平台能力缺口降级表
- `generic/AGENTS.md` · `gemini-cli/GEMINI.md` —— 无钩子平台的兜底

### 验证层
- 266 项测试，覆盖条款语义、闸门矩阵、裁决规则、记忆衰减、管线不变量、MCP 协议、规则引擎
- `test_traceability.py`：条款 ↔ 实现 ↔ 测试 双向追溯，含反向检查

### 已知边界（不掩盖）
- 词库覆盖率有限（约 150 条）；遇到未归类词条报 `FCS001` 而非静默过滤（依 6.6）
- 规则引擎基于词典子串匹配，不做语义模型推理
- 参考图反向工程模块仅留接口位（依规范 12.2，需视觉能力）
- 子代理三角视角在无并行能力的平台上串行执行，已在 `tool-mapping.md` 登记降级

### 来源与致谢
架构借鉴 [superpowers](https://github.com/obra/superpowers)（MIT）的三层投递模型、
技能发现优化（SDO）与"形式匹配失败类型"；深度研究方法论吸收 `cognitive-core` v3.1；
领域规则源自《模块化特征簇标记语法》创作范式规范 V1.0。均按其原始许可使用。
