# units · 单位解析与量纲（包 Pint）

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

## 这是什么

一个原子模块：论文里的单位写法（`MJ m-3`、`kcal mol-1`、`°C`、`wt%`）→ Pint 的量纲 / 换算。
存在的理由：单位表手写永远补不全；「数的量纲」和「性质该有的量纲」对不上，是抽取里最便宜的一票否决。

## 对外接口

| 函数 | 说明 |
|---|---|
| `dimension(unit_text)` | → 量纲字符串，认不出返回 `''` |
| `same_dimension(a, b)` | 两个单位量纲是否相同 |
| `to_base(value, unit_text)` | → `(基本单位下的值, 单位)`，失败 `None` |
| `normalize_unit(text)` | 论文写法 → Pint 写法（纯函数） |

## 使用者

`tools/extract`（抽取的量纲把关）· `shared/domain/numcheck`（待接）。

## 验证

`python shared/adapters/units/selftest.py`（不联网）。依赖 `pint`（在 pyproject 的 dependencies 里）。
