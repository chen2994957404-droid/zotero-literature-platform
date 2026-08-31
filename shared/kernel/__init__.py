# -*- coding: utf-8 -*-
"""shared.kernel —— 内核环。

谁都可以依赖它，它**不依赖任何人**（不依赖 shared.domain / shared.adapters / tools / host，
也不联网、不调用第三方库）。这是四环架构最底下的一环。

见 `docs/架构重构_v2总体设计.md` 第一节。

现有成员：
    paths   —— 数据契约的唯一实现（所有 workflow_data 路径只此一处）
"""
