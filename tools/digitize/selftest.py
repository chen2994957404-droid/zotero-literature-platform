# -*- coding: utf-8 -*-
"""digitize 离线自测：**不联网、不碰用户数据**。
用法: python tools/digitize/selftest.py

R7 窗重写。此前这份自测要求本地 Ollama 装着 qwen2.5vl、且库里有已解析文献，
于是在编程端永远是红的（`urlopen error 10061`）—— 一个「本机没装东西就红」的
自测等于噪音，久了就没人看了（同 `health_check` 分离线/实测两档的理由）。

真要验「视觉模型读得准不准」，那是 `evals/` 的活（要花钱、要真图、要人看结果），
不是自测的活。自测只管这块**不依赖外部世界的那部分**：

  · 提示词在不在、模板占位符对不对（改坏了会在真调用时才炸，那时已经花了钱）
  · 模型回话的容错解析（带 ```json 围栏、前后有废话，都得能解出来）
  · 拿不到模型时返回 `{'error': ...}` 而不是抛异常（调用方按这个契约写的）
"""
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters.llm_client import _parse_json_lenient
from tools import digitize as D

ok = total = 0


def check(name, cond, extra=''):
    global ok, total
    total += 1
    if cond:
        ok += 1
        print(f'  [PASS] {name}')
    else:
        print(f'  [FAIL] {name} {extra}')


def main():
    print('== 1. 提示词与模板 ==')
    check('系统提示词非空', len(D._SYS.strip()) > 50, f'只有 {len(D._SYS)} 字')
    user = D._USER_TMPL.format(hint='')
    check('模板能填（花括号都转义对了）', 'chart_type' in user and '{hint}' not in user)
    check('填了提示就出现在正文里',
          '只读红色曲线' in D._USER_TMPL.format(hint='额外提示：只读红色曲线'))

    print('== 2. 模型回话的容错解析 ==')
    plain = '{"chart_type": "line", "series": [{"name": "a", "points": [[1, 2]]}]}'
    fenced = '这是结果：\n```json\n' + plain + '\n```\n以上。'
    r1, r2 = _parse_json_lenient(plain), _parse_json_lenient(fenced)
    check('裸 JSON 解得出', r1.get('chart_type') == 'line')
    check('带围栏和废话也解得出', r2 == r1, str(r2)[:80])

    print('== 3. 拿不到模型时的契约 ==')
    # 指一个必定连不上的 provider：契约是**返回 error 字段**，不是抛异常。
    # 调用方（cli / mcp / 面板）全按这个契约写的，一旦改成抛异常就会整条炸。
    out = D.digitize('bm90IGFuIGltYWdl', provider='ollama',
                     model='definitely-not-installed-model')
    check('返回 dict 而不是抛异常', isinstance(out, dict), type(out).__name__)
    check('失败时带 error 字段', 'error' in out, str(out)[:80])

    print('== 4. 读不了图片文件也要守同一个契约 ==')
    out2 = D.digitize_file(os.path.join(os.path.dirname(__file__), '不存在的图.png'))
    check('文件读不了 → error 字段', isinstance(out2, dict) and 'error' in out2, str(out2)[:80])

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
