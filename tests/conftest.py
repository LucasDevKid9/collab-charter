"""共享测试夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT / "tools", ROOT / "interfaces", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

from collab_charter import Charter, Session  # noqa: E402
from collab_charter.memory import MemoryStore  # noqa: E402

# 规范附录 A.1 的原文，供多个测试复用
CASE_PC98 = (
    "PC-98 era visual novel sprite（PC-98时代视觉小说立绘）, 古早立绘，半身像，赛璐璐平涂，"
    "16-bit indexed color，Bayer dithering，硬边缘，色彩套印不准，透明背景抠图伪影，"
    "对话框 UI, 近距离随手拍，特写镜头，CRT 扫描线, 色差, 极度压缩伪影，极低分辨率，"
    "全景深, 原始未处理截图，低动态范围, 平光，全片ISO为同一固定值，固定高ISO，明显数字噪点，"
    "去除复杂光影，无情绪, 无机质氛围，自动白平衡失误，发灰、偏色、褪色，欠曝, "
    "顶点抖动, 仿射纹理映射扭曲, 原始比例，4:3"
)

# 规范附录 A.2 的节选
CASE_HI8 = (
    "(上世纪80-90年代末的Hi8机分辨率质感风格:1.4)，(Agfacolor胶片色阶浸染，时代印痕:0.8)，"
    "(私影像cult风:1.3)，低保真，光感漫射，带着微微颗粒感，禁噪点，低分辨率，"
    "有点模糊，随机种子，16:9"
)


@pytest.fixture(scope="session")
def charter() -> Charter:
    return Charter.load()


@pytest.fixture
def memory() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def session(charter: Charter, memory: MemoryStore) -> Session:
    return Session(charter, memory=memory)
