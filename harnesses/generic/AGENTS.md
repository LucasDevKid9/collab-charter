# AGENTS.md —— 通用 Agent 接入

> 适用于任何能读项目指令文件的 Agent（Aider / 自研 runner / 无插件体系的 CLI）。
> 完整技能索引见 [`../../skills/`](../../skills/)，动作→工具映射见
> [`../tool-mapping.md`](../tool-mapping.md)。

## 这是什么

本仓库是《用户协作宪章》v3.1 的执行内核。它把用户的协作规范变成可调用、可验证的
运行层：八站信息流管线、五级优先级、冲突裁决规则引擎、安全闸门、记忆回流，
以及对图像提示词的《模块化特征簇标记语法》诊断。

## 你该怎么做

### 1. 会话开始

按宪章第一章输出不超过 3 行自检，**禁止寒暄**：

```bash
python3 -m collab_charter.cli receipt
```

若要声明本环境无法执行的条款（会附降级方案）：

```bash
PYTHONPATH=src python3 -c "
from collab_charter import Charter, Session
print(Session(Charter.load(), agent_cannot=['0.6-O1','6-R1']).receipt())
"
```

> **不允许静默忽略**（7-R4）。无法满足的条款，首次响应必须显式列出，之后不再重复。

### 2. 处理任何请求前，先路由

**别一上来就全量跑八站。** 先判断这次需要多重：

```bash
python3 -m collab_charter.cli route "<用户请求原文>"
```

- L1 简单问题 / 闲聊 / 单事实问答 / 用户说「快速」→ **三站最小管线**
- 其余 → **全量八站**
- 用户说「深挖 / 展开」，或任务是创造性产出、多步计划、本地文件 → **强制全量**

### 3. 需要完整、可审计的处理

```bash
python3 -m collab_charter.cli handle "<用户请求原文>" \
  --constraint "用户给的关键约束" \
  --creative            # 创造性产出
  --plan                # 多步计划
  --local-files         # 涉及本地文件
```

输出包含逐站轨迹、最终输出、认知镜像话术、需要用户裁断的问题（若有）、自检结论。

### 4. 需要的其他能力

| 需要 | 命令 |
|---|---|
| 查一条条款原文 | `python3 -m collab_charter.cli clause 0.5-R4` |
| 通览某章规则 | `python3 -m collab_charter.cli clauses --chapter chapter_5_analysis` |
| 诊断图像提示词 | `PYTHONPATH=tools python3 -m fcslint "<提示词>"` |
| 结构化诊断结果 | `PYTHONPATH=tools python3 -m fcslint --json "<提示词>"` |
| 宪章完整性自检 | `PYTHONPATH=src python3 -m collab_charter.cli verify` |

若你有 MCP 能力，直接接入 `python3 interfaces/mcp_server.py` 用那 10 个工具，比 CLI 更省 token。

### 5. 技能

`skills/` 下五个技能的 `description` 字段写明了各自的触发条件。按需加载：

- `using-charter` —— 入口，确立技能查验规则
- `info-flow-protocol` —— 第〇章的可操作版（路由、优先级、冲突、自检、快捷词）
- `feature-cluster-syntax` —— 图像提示词创作/优化/诊断
- `deep-research` —— 多信源核实、对抗验证、证据账本
- `authoring-skills` —— 要新增或修改技能时

## 三条硬规矩

1. **不许静默降级。** 能力缺失就明说，并给替代路径（6-R4 / 7-R4）。
2. **不许把协议做成前置仪式。** 简单任务直接答（0.9）。
3. **不许改宪章来迁就实现。** 条款的权威在 `charter/charter.yaml`；
   代码若与其不一致，是代码错。`tests/test_traceability.py` 会拦住这种漂移。

## 依赖

Python ≥ 3.9 + `pyyaml`。MCP server 与提示词诊断器零第三方依赖。
