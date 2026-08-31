---
name: python-redlines
description: 改 .py 之前必须满足的硬约束（守卫会当场变红）
paths:
  - "**/*.py"
---

<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。改源：docs/howto/rules/python-redlines.md -->

# 动 .py 之前：这些是守卫，不是建议

`python -m pytest` 里有一组架构守卫。下面每一条违反了都会当场变红。
**完整清单与理由 → `code-redlines` skill**；这里只列会立刻咬人的。

## 一定会红的写法

| 别这么写 | 要这么写 |
|---|---|
| `sys.path.insert(...)` 塞项目根 | 什么都不写（项目已装成包；`pip install -e . --no-deps`） |
| 手写 `sys.argv` | `from shared.kernel.cli import pos, flag, opt` |
| 硬编码密钥 / URL / 模型名 | `from shared.kernel.config import get_key, get_site, get_model` |
| 自己拼 `data/...` 路径 | `from shared.kernel import paths`，用 `paths.fulltext(key)` 之类 |
| 在 `tools/` 或 `shared/domain/` 里 `urlopen` | 包成 `shared/adapters/<服务名>`，本层只调它 |
| 自己写 `def log()` 或劫持 `print` | `from shared.kernel.log import get_logger` |
| `tools/a` import `tools/b` | 下沉到 `shared/`、上浮到 `host/`，或整个搬过去 |
| 谁 import `host/` | 没人可以。`host/` 单向依赖别人 |
| `shared/domain/` import `paths` 或 adapters | 路径由调用方传进来；纯逻辑必须能离线测 |

## 写 Zotero / 花钱 / 起常驻服务，必须有机器角色守卫

```python
def main():
    role.require_prod('这是什么操作（写给不懂编程的用户看）', force=flag('--force'))
```

**写在函数体里，不能写模块顶层** —— 顶层会让 `import` 就抛错，
体检的运行时导入、pytest 收集、面板借用逻辑会一起挂。守卫挡的是「执行」不是「加载」。

## 标准开头（4 行，且要在文档字符串**后面**）

```python
# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
```

写在文档字符串前面，`__doc__` 就是 `None`（踩坑 #84）。

## 改完至少跑这两条

```bash
python -m pytest -q
python host/doctor/health_check.py --offline
```

**「能 import 成功」不等于「代码没问题」**（踩坑 #49）。
