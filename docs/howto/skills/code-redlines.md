---
name: code-redlines
description: 要新增或修改本项目任何 .py 文件之前必须先读这份。七条有守卫强制的红线（标准开头 / shared.kernel.cli 取参 / shared.kernel.config 取配置 / shared.kernel.paths 取路径 / 联网只许在 shared/adapters / shared.kernel.log 打日志 / 有副作用要加机器角色守卫）、四条硬规则（工具不许互相 import、联网只在 adapters、domain 不许知道路径、没人 import host）、新增积木与新增工具的准入标准，以及改完必跑的验证顺序。凡是动代码、加积木、加工具、搬模块、改脚本都适用。
---

# 改代码红线

**这些不是风格建议，是 `python -m pytest` 里的架构守卫会当场变红的硬约束**
（21 条守卫在 `tests/test_architecture.py`）。完整原文见
`docs/howto/代码规范_标准脚本模板.md`；本页是执行清单。

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

⚠ **标准开头要写在文档字符串后面**，写前面 `__doc__` 就是 None（踩坑 #84）。

### 2. 命令行参数一律走 `shared.kernel.cli`
`from shared.kernel.cli import pos, flag, opt, opts, positionals, wants_help`。
**禁止手写 `sys.argv`。** 没人认识的参数会被当成「没给参数」，
于是走进最贵那条路（踩坑 #85：`--help` 曾直接触发全库抽取）——
所以有分支的入口先 `wants_help()`。

### 3. 配置与模型名一律走 `shared.kernel.config`
`get_key()` / `get_site()` / `get_model()`。**禁止 hardcode 密钥、URL、模型名。**
密钥加载顺序：环境变量 → 系统凭据库 → `.env`。用户在控制面板里填。

### 4. 数据路径一律走 `shared.kernel.paths`
`paths.fulltext(key)` / `paths.CURATED` / `paths.RAW` / `paths.log(名)`。
**禁止手写 `data` 字样的路径**，有守卫拦截。
R6 窗把数据换成五层，全系统只改了 `paths.py` 一个文件 —— 靠的就是这条。

### 5. 联网只许在 `shared/adapters/`
别处要调外部服务，**先把它包成 `shared/adapters/<服务名>`，本环只调那块**。
这条守着的是「换掉 MineRU 只改一个文件」这个承诺。

### 6. 日志走 `shared.kernel.log` 的 `get_logger(名)`
**不要自己写 `def log()`，更不要劫持 `print`。**
注意 Logger 是全局的，同名再取一次会把 handler 挂两遍（踩坑 #48）。

### 7. 有副作用的操作要加机器角色守卫
凡是**写 Zotero / 花钱的批量作业 / 起常驻服务**：
```python
from shared.kernel import role
from shared.kernel.cli import flag

def main():
    role.require_prod('批量精读（调用付费 API）', force=flag('--force'))
```
- **必须写在函数体里，不能写模块顶层** —— 写顶层会让 `import` 就抛错，
  体检的运行时导入检查、pytest 收集、面板借用逻辑会一起挂。守卫挡的是「执行」不是「加载」。
- 动作描述会原样显示给不懂编程的用户看，写人话。
- 常驻服务要在 `__main__` 里接住 `WrongMachineError`，打印人话而非 traceback。
- 守卫测试会扫描所有出现 `api.zotero.org` 的文件，漏一个就红。

## 二、四条硬规则（REBUILD.md 第三节，守卫强制）

```
host  →  tools  →  shared.domain / shared.adapters  →  shared.kernel
```

1. **下沉规则**：一段代码被 **≥2 个使用者**（工具或 host 的块）用到才允许进 `shared/`；
   只有 1 个用，搬进那个使用者里。
   例外只有 adapters 整环 —— 把外部服务封装搬进工具会违反规则 3。
2. **工具隔离**：`tools/*` **不许 import 别的 `tools/*`**。出路只有三条：
   共用的代码**下沉**到 `shared/`；跨工具的编排**上浮**到 `host/`；
   或者承认这件事本来就属于其中一个工具，整个搬过去。
3. **联网只在** `shared/adapters/`。`shared/domain/` 不许 import adapters，
   也**不许 import `shared.kernel.paths`** —— 纯逻辑永远不知道文件放在哪，路径由调用方传进来。
4. **没人 import `host/`**；`host/` 可以 import 一切。

**该往哪一层放**，判据是「什么会让它需要改」：

| 层 | 什么会让它改 | 能联网 |
|---|---|---|
| `shared/kernel/` | 几乎不会（路径/配置/日志/异常/参数/锁/提示词读取） | 否 |
| `shared/domain/` | 只有我们自己想法变了（算法、格式、schema） | 否，且不许知道文件放在哪 |
| `shared/adapters/` | 外部世界变了（API 换版本、换模型、换向量库） | **只有这一层** |
| `tools/` | 需求一变就变（把上面三者按顺序组合成一个工具） | 否 |
| `host/` | 平台自身的运维方式变了（面板、体检、部署、MCP、常驻服务） | 否 |

**铁律 1 的反面判据**：「如果一个能力还能被拆成『先做 A 再做 B』，
它就不是公理，是定理」→ 定理放 `tools/`，公理放 `shared/domain/` 或 `shared/adapters/`。

## 三、新增东西的准入

### 新增共用件 `shared/<环>/<名>/`：三件套缺一不可
- `__init__.py` —— docstring 写清「解决的真实问题 + 用法」，公开函数列表用表格注释
- `selftest.py` —— **不联网、不依赖用户数据**的纯逻辑自测（体检会挨个跑）
- `CLAUDE.md` —— 照 `shared/kernel/config/CLAUDE.md` 的版式

**只做一件不可再分的事。** 想在积木里加「顺便还做 XX」时，XX 属于上层。
**且先确认有第二个使用者** —— 只有一个使用者的东西不许住 `shared/`（硬规则 1）。

### 新增工具 `tools/<名>/`：七件套缺一不可
`tool.toml` · `__init__.py` · `cli.py` · `mcp.py` · `SKILL.md` · `README.md` · `tests/`
（另加 `selftest.py`、`prompts/`、`evals/`）。

- `tool.toml` 的 `expose` 判据：**只读且便宜 → `tool`；只读数据 → `resource`；
  花钱或有副作用 → `prompt`。** 花钱/有副作用的注册成 `tool` 会被守卫和
  `host/mcp/registry.check()` 一起拦下 —— tool 是模型能自己调的，
  等于把钱包交给模型（踩坑 #86）。
- `SKILL.md` 必须写「**什么时候别用我**」—— 模型选错工具的主因是不知道边界。
- `mcp.py` 只做参数转换，**不许有逻辑**。
- 提示词进 `prompts/<名>_v<N>.txt`，**只增不改**；版本号在 `tool.toml` 里声明，
  守卫会核对那一版真在盘上。

## 四、改完的验证顺序（前两步离线、秒级，必须全绿）

```bash
python <路径>/selftest.py                        # 改了哪块先验哪块
python -m pytest -q                              # 离线测试 + 21 条架构守卫
python host/doctor/health_check.py --offline     # 离线档体检（必须 10/0/0）
python host/doctor/health_check.py               # 完整体检（A 机没主力机密钥会红，正常）
python host/codegen/handover.py                  # 刷新 AGENTS.md 结构树 + HANDOVER.md
python host/codegen/skills.py                    # 改了 SKILL.md / 规则源就重新生成 .claude/
```

⚠ **能 import 成功 ≠ 代码没问题**（踩坑 #49）：import 只证明语法过了，
函数体里的 NameError 照样在。别拿「import 通过」当验证。

⚠ **加了守卫要故意违反一次，确认它真的会红**（踩坑 #83：改名之后守卫会静默空转；
R7 窗抓到两条空转了六个窗）。还原时**别用 `git checkout --`**，
会把本窗其它未暂存的改动一起冲掉（踩坑 #90）。

## 五、改完必做的三件事

1. 技术发现 / 踩坑 → 当场追加 `docs/incidents/踩坑记录.md`（编号 + 现象 + 根因 + 解法），
   工具特有的坑同时写进 `tools/<t>/INCIDENTS.md`
2. 改代码 / 删数据 / 运维 → 当场记 `docs/变更记录.md`
3. **git commit**（每步一个提交，可回退）

写中文用 Python `io.open(...encoding='utf-8')` 追加，避开 PowerShell 的 GBK 乱码。

## 六、命名约定

小写下划线；函数名动词开头；返回是否的用 `has_` / `is_` 前缀；
集合用复数名词；布尔开关常量大写。
