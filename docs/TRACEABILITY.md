# 条款追溯矩阵

**目的**：宪章有 90 条可执行条款。本表回答一个问题——**每一条，到底由什么在执行？**

答案是三类，且**不回避第三类**：

| 类别 | 含义 | 数量 | 验证方式 |
|---|---|---|---|
| **代码执行** | 有可断言的实现，违规能被机械检出 | 54 | `tests/test_traceability.py` 机械验证 |
| **技能承载** | 行为约定，由技能文档约束模型行为，无法机械断言 | 36 | 技能正文 + 人工核验 |
| **待实现** | 已知缺口，已登记理由与边界 | 0 | 见 [ANALYSIS.md](ANALYSIS.md) 第五节 |

> 依据宪章 **5-R2 / 8-R2**：不把"写了文档"说成"已经实现"。

---

## 一、代码执行的条款（54 条）

`tests/test_traceability.py` 会逐条验证：条款真实存在 → 模块真实存在 → 有指名测试。

### 第〇章 · 信息流协议

| 条款 | 内容摘要 | 执行模块 | 指名测试 |
|---|---|---|---|
| `0.1-V` | 两个正交维度（分层 × 类型） | `flows.py` | `test_分层与宪章一致` |
| `0.2-V` | 八个元数据标签 | `flows.py` | `test_八个元数据标签齐备` |
| `0.3-I1` | 没有回流，系统就是开环 | `router.py`（第 8 站） | `test_reflow_后自检通过` |
| `0.3-I2` | 认知镜像为强制节点 | `router.py`（第 3 站） | `test_全量路由包含认知镜像` |
| `0.3-I3` | 不过闸则 2–8 站不执行 | `gates.py` + `router.py` | `test_不过闸时管线终止` |
| `0.4-R1` | 准确性否决用户目标 | `arbiter.py`（优先级阶梯） | `test_真实高于用户目标` |
| `0.5-R1` | 事实>推测；高置信>低置信 | `arbiter.py` | `test_事实优于推测` |
| `0.5-R2` | 新>旧（稳定偏好/安全约束豁免） | `arbiter.py` | `test_新信息优于旧信息` |
| `0.5-R3` | 用户显式陈述 > 模型推测 | `arbiter.py` | `test_用户显式陈述优于模型推测` |
| `0.5-R4` | 同级同源并列，一次最多 1 问 | `arbiter.py` | `test_同级同源并列呈现` |
| `0.5-R5` | 情感流不参与事实裁决 | `arbiter.py` | `test_情感流不参与事实裁决` |
| `0.6-O1` | 记忆沉淀 | `memory.py` | `test_沉淀生成记忆节点` |
| `0.6-O2` | 记忆再激活（带元数据） | `memory.py` | `test_再激活还原为带元数据的流` |
| `0.6-O3` | 衰减与刷新 | `memory.py` | `test_用户纠正刷新为高置信并记录来源` |
| `0.7-R1` | 内部流默认不展示 | `router.py` | `test_内部流不进入输出` |
| `0.7-R2` | "简化"只留结论与依据 | `session.py` | `test_简化快捷词压缩输出` |
| `0.7-R3` | 低置信必须标"待验证" | `router.py` | `test_低置信流出前补待验证` |
| `0.8-C1` | 关键约束是否丢失 | `selfcheck.py` | `test_约束丢失被检出` |
| `0.8-C2` | 推测是否已标注置信度 | `selfcheck.py` | `test_未回流时自检失败` |
| `0.8-C3` | 来源是否可追溯 | `selfcheck.py` | `test_不可追溯的事实流被检出` |
| `0.8-C4` | 反馈是否已回流 | `selfcheck.py` | `test_未回流时自检失败` |
| `0.8-C5` | 安全闸门是否生效 | `selfcheck.py` | `test_未回流时自检失败` |
| `0.8-C6` | 输出是否只含必要信息 | `selfcheck.py` | `test_全部通过时报告为空` |

### 第一 / 九 / 十章

| 条款 | 内容摘要 | 执行模块 | 指名测试 |
|---|---|---|---|
| `1-C1` | 接收自检不超过 3 行 | `session.py:receipt()` | `test_receipt_不超过三行` |
| `1-C2` | 不可执行须附降级方案 | `session.py` + `DEFAULT_DEGRADATIONS` | `test_声明不可执行时附降级方案` |
| `1-C3` | 确认称呼 | `session.py:receipt()` | `test_receipt_无寒暄` |
| `1-C4` | 直接进入工作，不复述全文 | `session.py:receipt()` | `test_receipt_无寒暄` |
| `9-W1` | 快捷词「展开」 | `session.py:SHORTCUT_BEHAVIOR` | `test_快捷词被识别` |
| `9-W2` | 快捷词「简化」 | `session.py` | `test_简化快捷词压缩输出` |
| `9-W3` | 快捷词「讲思路」 | `session.py` + `PipelineRun.trace()` | `test_handle_返回完整结果` |
| `9-W4` | 快捷词「查来源」 | `session.py` + 各 Finding 的 `clause` 字段 | `test_结构化输出字段完整` |
| `9-W5` | 快捷词「快速」 | `router.py:plan()` | `test_快速词走快速通道` |
| `9-W6` | 快捷词「深挖」 | `router.py:plan()` | `test_快捷词被识别` |
| `10-R1` | 平台安全优先于本宪章 | `gates.py`（裁决表未覆盖时保守处理） | `test_每种组合都有裁决` |
| `10-R2` | AI 永远是 AI | `gates.py` + 技能约束 | 技能承载 |
| `10-R3` | 隐私只读不外发 | `gates.py:strip()` + 闸门矩阵 | `test_禁外发一律拦截` |
| `10-R4` | 不可逆操作须确认 | `gates.py`（`confirm` 裁决） | `test_高危需要用户确认` |

### 特征簇规范的代码执行部分

| 规范条款 | 内容摘要 | 规则码 | 测试 |
|---|---|---|---|
| 2.1 | 六大功能簇封闭集 | `FCS001` | `test_未归类词条被显式报出` |
| 2.1 | 簇排布顺序（隐性权重梯度） | `FCS011` | `test_簇序倒置被检出` |
| 3.1 | 核心载体锚点 | `FCS008` | `test_缺主体锚点被报错` |
| 3.2 | 风格域数量法则 | `FCS006` | `test_风格域超限被警告` |
| 3.4 | 抽象词条权重与数量 | `FCS003` / `FCS005` | `test_抽象词条高权重被报错` |
| 3.5 | 权重梯度 | `FCS010` | `test_权重梯度偏离给提示但不定罪` |
| 5.4 | 冗余过滤 | `FCS007` | `test_无效技术参数被报出` |
| 8.3 | 直接冲突（必须删除其一） | `FCS004` | `test_直接语义冲突被报错` |
| 8.3 | 跨域冲突（标记而非删除） | `FCS009` | `test_跨域逻辑冲突只警告` |
| 9.1 | 权重区间 0.5–1.4 | `FCS002` | `test_权重越界被报错` |
| 5.4 | 控制力量化四维打分 | `ControlScore` | `test_评分四项都有明细` |
| 5.2 | 簇结构保留优化 | `report.suggest()` | `test_优化稿不移除核心意图词条` |

### 第十一 / 十二章（v3.2 新增）

知识库四件套在 `src/collab_charter/lexicon/`，求解器在 `src/collab_charter/anchor/`。
深度说明：[SEMANTIC-FIELD.md](SEMANTIC-FIELD.md)。

| 条款 | 内容摘要 | 执行模块 | 指名测试 |
|---|---|---|---|
| `11.1-K1` | 知识只存 `knowledge/*.yaml`，零代码扩容 | `lexicon/kb.py` | `test_零代码扩容` |
| `11.1-K2` | 来源 + 置信度；不可溯源进名单 | `lexicon/kb.py` | `test_不可溯源条目进入名单` |
| `11.1-K3` | 调用随结果输出 digest | `lexicon/kb.py` | `test_digest_稳定且随内容变化` |
| `11.2-V1` | 同输入同向量同排序，无随机性 | `lexicon/vectors.py` | `test_空间指纹随上下文变化` |
| `11.2-V2` | 得分可分解为分布权重 | `lexicon/mine.py` | `test_分布权重归一` |
| `11.2-V3` | 空间任务期临时建构、用后即弃 | `lexicon/vectors.py` | `test_空间任务期临时建构用后即弃` |
| `11.3-F1` | 网络确定性推出，无随机初始化 | `lexicon/field.py` | `test_关联网络与社群` |
| `11.3-F2` | 覆盖缺口必须输出 | `lexicon/field.py` | `test_覆盖缺口可操作` |
| `11.3-F3` | 语义场结论是知识流非事实流 | `lexicon/kb.py` | `test_检索工具返回可溯源字段` |
| `11.4-M1` | 非公开条目附闸门结论 | `lexicon/mine.py` | `test_高危条目闸门_block` |
| `11.4-M2` | 在线扩容只报不执行 | `lexicon/mine.py` | `test_在线扩容只报不执行` |
| `11.4-M3` | 语义状态显式影响权重 | `lexicon/mine.py` | `test_语义状态策略表齐全` |
| `12.1-A1` | 结论来自求解器枚举 | `anchor/solver.py` | `test_第一轮推荐观望` |
| `12.1-A2` | AST 白名单，逃逸一律拒绝 | `anchor/solver.py` | `test_逃逸构造一律被拒` |
| `12.1-A3` | 警告原样转告 | `anchor/solver.py` | `test_无解轮给出建议` |
| `12.1-A4` | 漂移必须提示「标准未稳」 | `anchor/solver.py` | `test_solve_检测漂移并提示标准未稳` |
| `12.1-A5` | 未覆盖解数必须报告 | `anchor/solver.py` | `test_档位未覆盖的解被计数` |

---

## 二、技能承载的条款（36 条）

这些条款约束的是**模型的判断与表达**，没有可机械断言的谓词——强行写成代码只会得到
一堆"看起来在检查、其实什么也没检查"的断言。它们由技能文档承载：

| 章节 | 条款 | 承载技能 |
|---|---|---|
| 一 | `1-C2`（降级声明，部分） | `using-charter` |
| 二 | `2-P1` … `2-P6`（用户画像 6 条） | `using-charter` + `info-flow-protocol` |
| 三 | `3-R1` … `3-R7`（沟通铁律 7 条） | `info-flow-protocol` |
| 四 | `4-V1` … `4-V4`（最小充分上下文 4 条） | `info-flow-protocol` |
| 五 | `5-R1` … `5-R6`（分析纪律 6 条） | `deep-research` |
| 六 | `6-R1` … `6-R4`（本地文件 4 条） | `info-flow-protocol` + `tool-mapping.md` 降级表 |
| 七 | `7-R1` … `7-R4`（认知与记忆 4 条） | `info-flow-protocol` + `authoring-skills` |
| 八 | `8-R1` … `8-R5`（输出格式 5 条） | `info-flow-protocol` |
| 十 | `10-R2`（AI 永远是 AI） | `using-charter` |

**为什么这样分**：宪章第二章要求"对齐成本由 AI 承担、反感清单轰炸"，第三章要求"回问极克制"——
这些是**判断力条款**。把它们写成 `if len(questions) > 1: raise` 只会制造形式主义，
反而违反 0.9「协议不得把自身变成繁琐的前置仪式」。

---

## 三、如何自己验证

```bash
# ① 内核结构自检（SSOT 契约 + 站点一致性 + 矩阵覆盖 + 自检项一致性）
python3 -m collab_charter.cli verify

# ② 条款追溯（条款存在 → 模块存在 → 有指名测试）
python3 -m pytest tests/test_traceability.py -v

# ③ 全量测试
python3 -m pytest -q
```

**追溯是双向的**：不仅有"条款 → 实现"，还有反向检查——
`test_实现声明不指向不存在的条款` 会拦住"声明实现了一个宪章里根本没有的条款"这种一厢情愿。

---

## 四、维护契约

新增或修改条款时，必须同时更新三处，否则测试会失败：

1. `charter/charter.yaml` —— 条款正文（**先改这里**）
2. `charter/CHARTER.md` —— 人读版同步
3. `tests/test_traceability.py` —— 若是代码执行条款，加入 `CLAUSE_IMPLEMENTATION` 与 `TEST_COVERAGE`

若新增的是规则引擎条款，还要在 `knowledge/lexicon.yaml` 或 `rules.py` 落地，
并加入 `SPEC_IMPLEMENTATION`。

若新增的是知识库/语义场条款，执行模块写在 `src/collab_charter/lexicon/`（点号路径
`lexicon.kb` 等）；符号锚定条款写在 `src/collab_charter/anchor/`。

这套约束让"规范漂移"从**不可避免**变成**第一次提交就报错**。
