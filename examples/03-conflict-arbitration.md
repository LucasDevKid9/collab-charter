# 示例三：冲突裁决与安全闸门

这两个能力对应宪章里最容易"说起来清楚、做起来含糊"的两处：**0.5 冲突裁决**与**第十章安全闸门**。
本示例展示它们被做成可查询的确定性判定后是什么样子。

## 一、冲突裁决（0.5）

### 场景：用户的两句话互相矛盾

```python
from collab_charter import Charter, Session
from collab_charter.flows import Flow, FlowLayer, FlowType, Source, Direction, TTL, Confidence

s = Session(Charter.load())

# 用户明说的事实
fact = Flow(text="这个接口已经废弃了", layer=FlowLayer.INPUT, type=FlowType.FACT,
            source=Source.USER_STATED, direction=Direction.INBOUND,
            ttl=TTL.SESSION, confidence=Confidence.HIGH)

# 模型的推测
guess = Flow(text="应该还能用", layer=FlowLayer.INTERNAL, type=FlowType.SPECULATION,
             source=Source.MODEL_GUESS, direction=Direction.INTERNAL,
             ttl=TTL.SESSION, confidence=Confidence.LOW)

c = s.router.arbiter.compare(fact, guess)
print(c.verdict, c.clause, c.reason)
```

```text
Verdict_.LEFT 0.5-R1 事实流优先于推测流
```

**关键**：结论里带着 `clause="0.5-R1"`。用户说「查来源」时，可以直接
`python3 -m collab_charter.cli clause 0.5-R1` 取回条文原文。

### 五条规则是怎么排优先级命中的

`Arbiter.compare()` 严格按宪章 0.5 的书写顺序**先命中先用**：

| 顺序 | 规则 | 命中条件 | 结果 |
|---|---|---|---|
| 1 | `0.5-R5` | 任一方是情感流，另一方是事实流 | 事实胜出，**情绪只调节表达权重** |
| 2 | `0.5-R1` | 一方事实一方推测 | 事实流胜出 |
| 3 | `0.5-R1` | 置信度不同 | 高置信胜出 |
| 4 | `0.5-R3` | 来源不同且一方是用户明说 | 用户陈述胜出 |
| 5 | `0.5-R2` | 新旧不同 | 新信息胜出（稳定偏好/安全约束**豁免**） |
| 6 | `0.5-R4` | 以上都不适用 | **并列呈现，请用户裁断，一次最多 1 问** |

注意第 1 条排在最前——这直接落实宪章 0.5 最后一条："情感流不参与事实裁决"。
把情绪排在裁决链最前面短路掉，比放在最后补救更安全。

### 无法裁决时不会硬凑一个答案

```python
a = Flow(text="方案甲更稳", ...)
b = Flow(text="方案乙更快", ...)
r = s.router.arbiter.arbitrate([a, b])
print(r.has_tiebreak, r.tiebreak_questions[0])
```

```text
True 「方案甲更稳」与「方案乙更快」同级同源、无法裁决，请指定以哪条为准。（0.5-R4）
```

两条都保留，分歧升级为**一次**用户裁断。测试 `test_并列时最多只问一次` 守住
"一次最多 1 问"这条硬约束。

## 二、安全闸门（第十章）

闸门不是 `if-else`，而是一张从 `charter.yaml` 读入的裁决表：

```bash
PYTHONPATH=src python3 -c "
from collab_charter import Charter, Session
from collab_charter.flows import *
s = Session(Charter.load())
f = Flow(text='probe', layer=FlowLayer.OUTPUT, type=FlowType.KNOWLEDGE,
         source=Source.MODEL_PRIOR, direction=Direction.OUTBOUND,
         ttl=TTL.SESSION, confidence=Confidence.HIGH,
         sensitivity=Sensitivity('高危'), permission=Permission('禁外发'))
d = s.router.gate.inspect(f)
print(d.verdict, d.terminates, d.clause)
print(d.explain())
"
```

```text
Verdict.BLOCK True 10-R3
该内容被拦截（高危 × 禁外发，依据 10-R3）。我可以改用不含敏感信息的表述，或只在本地为你分析、不外发。
```

三件事同时成立：

1. **`verdict=block`** —— 裁决结果；
2. **`terminates=True`** —— 落实 0.3-I3「不过闸则第 2–8 站一律不执行」；
3. **`explain()` 给出"解释 + 替代"** —— 落实第十章要求的「不因拒绝而生硬」。

### 3×3 全组合

| 敏感度 \ 权限 | 可输出 | 仅内部 | 禁外发 |
|---|---|---|---|
| 公开 | 放行 | 剥离后放行 | **拦截** |
| 隐私 | 待确认 | 仅内部放行 | **拦截** |
| 高危 | 待确认 | 仅内部放行 | **拦截** |

"禁外发"整列都是拦截——因为 10-R3 明确"不外发、不留存、不扩散"，
它是最高优先级约束，不因敏感度低而放松。

### 表未覆盖时按最保守处理

如果有人在 `charter.yaml` 里删掉某一行，`SafetyGate` **不会静默放行**：

```
verdict=confirm
reason=裁决表未覆盖「X × Y」组合，按最保守处理
```

`tests/test_gates.py::test_闸门矩阵覆盖九种组合` 会在 CI 阶段直接拦住这种删减。

## 三、把这些接进 Agent

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "charter_gate",
            "arguments": {"sensitivity": "高危", "permission": "禁外发"}}}
```

```json
{"verdict": "block", "verdict_zh": "拦截", "passed": false,
 "terminates_pipeline": true, "needs_user_input": false, "clause": "10-R3",
 "explain": "该内容被拦截（高危 × 禁外发，依据 10-R3）。我可以改用不含敏感信息的表述，或只在本地为你分析、不外发。"}
```

同样地，`charter_arbitrate` 工具处理冲突裁决。这样模型不需要"记得"这些规则，
而是**查询**它们——规则改了，行为跟着改，不需要重新调提示词。
