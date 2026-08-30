---
name: code-redlines
description: 要新增或修改本项目任何 .py 文件之前必须先读这份。七条有守卫强制的红线（标准开头 / core.cli 取参 / core.config 取配置 / core.paths 取路径 / 联网只许在 adapters / core.log 打日志 / 有副作用要加机器角色守卫）、四环依赖方向、新增积木的三件套准入标准，以及改完必跑的验证顺序。凡是动代码、加积木、搬模块、改脚本都适用。
---

# 改代码红线

**这七条不是风格建议，是 `python -m pytest` 里的架构守卫会当场变红的硬约束。**
完整原文见 `docs/代码规范_标准脚本模板.md`；本页是执行清单。

## 一、七条红线

### 1. 标准开头只有 4 行
```python
# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
```
**不许有任何 `sys.path` 操作。** 旧的 9 行「走查项目根 + sys.path.insert」写法
曾在全项目重复 40 多处，已全删 —— 写回去 pytest 立刻红。
前提是装过一次：`pip install -e . --no-deps`（换电脑/重装后必做）。

### 2. 命令行参数一律走 `core/cli`
`from core.cli import pos, flag, opt, opts, positionals`。**禁止手写 `sys.argv`。**

### 3. 配置与模型名一律走 `core/config`
`get_key()` / `get_site()` / `get_model()`。**禁止 hardcode 密钥、URL、模型名。**
密钥加载顺序：环境变量 → 系统凭据库 → `.env`。用户在控制面板里填。

### 4. 数据路径一律走 `core.paths`
`paths.fulltext(key)` / `paths.LIBRARY` / `paths.log(名)`。
**禁止手写 `workflow_data` 字样的路径**，有守卫拦截。

### 5. 联网只许在 `adapters/`
别处要调外部服务，**先把它包成 `adapters/<服务名>`，本环只调那块**。
这条守着的是「换掉 MineRU 只改一个文件」这个承诺。
反面教材：重构前 `paper_discovery` 编排层里直接写着 OpenAlex 的 URL 和 `urlopen`。

### 6. 日志走 `core.log` 的 `get_logger(名)`
**不要自己写 `def log()`，更不要劫持 `print`。**
注意 Logger 是全局的，同名再取一次会把 handler 挂两遍（踩坑 #48）。

### 7. 有副作用的操作要加机器角色守卫
凡是**写 Zotero / 花钱的批量作业 / 起常驻服务**：
```python
from core import role
from core.cli import flag

def main():
    role.require_prod('批量精读（调用付费 API）', force=flag('--force'))
```
- **必须写在函数体里，不能写模块顶层** —— 写顶层会让 `import` 就抛错，
  体检的运行时导入检查、pytest 收集、面板借用逻辑会一起挂。守卫挡的是「执行」不是「加载」。
- 动作描述会原样显示给不懂编程的用户看，写人话。
- 常驻服务要在 `__main__` 里接住 `WrongMachineError`，打印人话而非 traceback。
- 守卫测试会扫描所有出现 `api.zotero.org` 的文件，漏一个就红。

## 二、四环依赖方向

```
apps → pipelines → domain / adapters → core
```
**只能从上往下 import。** 另外三条：
- `domain/` 不许 import `core.paths` —— 纯逻辑永远不知道文件放在哪，路径由调用方传进来
- `domain/` 不许 import `adapters/` —— 否则没法离线测试
- 不许 import 已经不存在的包（历史上的 `modules`）

**该往哪一环放**，判据是「什么会让它需要改」：

| 环 | 什么会让它改 | 能联网 |
|---|---|---|
| `core/` | 几乎不会（路径/配置/日志/异常/参数/锁） | 否 |
| `domain/` | 只有我们自己想法变了（算法、格式、schema） | 否 |
| `adapters/` | 外部世界变了（API 换版本、换模型、换向量库） | **只有这一环** |
| `pipelines/` | 需求一变就变（把上面三者按顺序组合） | 否 |

**铁律 1 的反面判据**：「如果一个能力还能被拆成『先做 A 再做 B』，
它就不是公理，是定理」→ 定理放 `pipelines/`，公理放 `domain/` 或 `adapters/`。

## 三、新增积木必须三件套

`<环>/<名>/` 下缺一不可：
- `__init__.py` —— docstring 写清「解决的真实问题 + 用法」，公开函数列表用表格注释
- `selftest.py` —— 不联网、不依赖用户数据的纯逻辑自测
- `CLAUDE.md` —— 照 `core/config/CLAUDE.md` 的版式（这是什么 / 职责 / 对外接口 / 谁在用 / 改完必须做）

**只做一件不可再分的事。** 想在积木里加「顺便还做 XX」时，XX 属于上层，放到 `pipelines/`。

## 四、改完的验证顺序（前两步离线、秒级，必须全绿）

```bash
python <环>/<名>/selftest.py          # 改了哪块先验哪块
python -m pytest -q                    # 离线测试 + 架构守卫
python 平台管理/health_check.py --offline   # 离线档体检
python 平台管理/health_check.py             # 完整体检（A 机没主力机密钥会红，正常）
python 平台管理/交接.py                      # 刷新 CLAUDE.md 结构树 + HANDOVER.md
```

⚠ **能 import 成功 ≠ 代码没问题**（踩坑 #49）：import 只证明语法过了，
函数体里的 NameError 照样在。别拿「import 通过」当验证。

## 五、改完必做的三件事

1. 技术发现 / 踩坑 → 当场追加 `docs/踩坑记录.md`（编号 + 现象 + 根因 + 解法）
2. 改代码 / 删数据 / 运维 → 当场记 `docs/变更记录.md`
3. **git commit**（每步一个提交，可回退）

写中文用 Python `io.open(...encoding='utf-8')` 追加，避开 PowerShell 的 GBK 乱码。

## 六、命名约定

小写下划线；函数名动词开头；返回是否的用 `has_` / `is_` 前缀；
集合用复数名词；布尔开关常量大写。
