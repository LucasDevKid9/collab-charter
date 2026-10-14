# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
版本号与宪章版本对齐：内核 `3.1.x` 对应宪章 `v3.1`。

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
