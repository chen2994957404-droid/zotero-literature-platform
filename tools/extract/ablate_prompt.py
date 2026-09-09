# -*- coding: utf-8 -*-
"""提示词消融：同一篇、同一个模型，**只换 system 提示词的版本**，看指标动不动。

用法:
  python -m tools.extract.ablate_prompt --n 3 --force            # 自动挑 3 篇，跑 v1/v2/v3
  python -m tools.extract.ablate_prompt KEY1 KEY2 --repeat 2 --force
  python -m tools.extract.ablate_prompt --n 3 --arms v1,v3 --force
  python -m tools.extract.ablate_prompt --n 1 --model qwen-plus --force

为什么要有这个（2026-09-07）：项目规矩「提示词只增不改」执行了很久，
但**加进去的每一条约束到底有没有用，从来没有被测过**（架构准则【已知待推翻项】第 1 条）。
`compare_models.py` 比的是「换模型」，这里比的是「换提示词」—— 模型钉死，只动那一个变量。

⚠ 这个实验有一个必须知道的混淆项（写在这里免得看错结论）：
`schema.build_user_prompt_v2` 生成的 **user 提示词里已经重复了同样的规则**
（「数字照抄不许换算」「location 猜的不如空着」）。所以本实验测的**不是**
「这些规则有没有用」，而是「**在 user 提示词已经说过之后，再往 system 里加一遍
还有没有边际作用**」。这恰好就是「只增不改」那条规矩的真实问句。

**绝不写盘**：只打印，不碰 `structured/<key>.json`（同 compare_models，踩坑 #16）。
"""
import io
import os
import re
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths, prompts, role
from shared.kernel.cli import flag, opt, positionals, wants_help
from shared.kernel.config import get_key
from shared.adapters import llm_client
from shared.domain import schema
from tools.extract import compare_models as bench

# 默认走阿里云百炼跑生产同款模型：模型与线上一致，额度用用户的免费档。
# 2026-09-07 实测：`qwen3.7-plus` 已 403「Free quota exhausted」，
# `qwen-plus` 与 `deepseek-v4-flash` 可用；账号开着「仅用免费额度」，
# 额度用完是 403 而不是扣钱。
默认模型 = 'deepseek-v4-flash'
默认厂商 = 'dashscope'


def 对准规则的指标(data):
    """两个**对准被测规则**的指标 —— 通用指标看不见提示词的差别，这两个能看见。

    2026-09-07 实测教训：只用「数字可追溯」当主指标，9 次跑全是 100%（天花板效应），
    什么也分不出来。原因是那个指标测的是「有没有编数字」，而 v2/v3 加的规则
    管的根本是**别的事**：
      - v2 规则 1「每个数字必须属于一个具名样品」→ 看 **绑定率**
      - v2 规则 3 / v3 收窄「location 只写真的知道的编号表图」→ 看 **location 猜测率**
    指标要对准规则，否则消融只能得出「看不出来」。
    """
    ms = (data or {}).get('measurements') or []
    名 = {str(x.get('sample_id') or '').strip().lower()
          for x in ((data or {}).get('samples') or [])}
    名.discard('')
    绑定 = sum(1 for m in ms
               if str(m.get('sample_id') or '').strip().lower() in 名
               and str(m.get('sample_id') or '').strip().lower() not in ('', 'unknown'))
    有位置 = [str(m.get('location') or '').strip() for m in ms]
    有位置 = [x for x in 有位置 if x]
    编号 = re.compile(r'(table|tab\.|fig|figure|scheme)\s*\.?\s*\d', re.I)
    猜 = sum(1 for x in 有位置 if not 编号.search(x))
    return {'meas': len(ms), '绑定': 绑定, '有位置': len(有位置), '猜位置': 猜}


def 跑一次(版本, 模型, 厂商, 篇):
    """用指定版本的 system 提示词抽一次。返回 (data, 秒)。"""
    系统 = prompts.load('extract', 'main@' + 版本)
    用户 = schema.build_user_prompt_v2(篇['title'], 篇['body'], 篇['si'])
    t = time.time()
    data = llm_client.chat_json(系统, 用户, provider=厂商, model=模型,
                                key=get_key('DASHSCOPE_KEY') if 厂商 == 'dashscope' else None)
    return data, round(time.time() - t, 1)


def 报告(结果, 臂):
    """把各臂的指标并排打出来。接地率是主指标 —— 它衡量『有没有编』。"""
    print('\n' + '=' * 76)
    print('汇总（每格 = 该臂在所有篇上的合计）')
    print(f'{"提示词版本":<10}{"测量条数":>9}{"绑定到样品":>12}'
          f'{"写了位置":>9}{"其中是猜的":>12}{"数字可追溯":>14}')
    for v in 臂:
        行 = [r for r in 结果 if r['arm'] == v]
        if not 行:
            continue
        S = lambda k: sum(r['m'][k] for r in 行)
        测 = S('meas')
        绑 = f'{S("绑定")}/{测} = {round(100.0 * S("绑定") / 测) if 测 else 0}%'
        位 = S('有位置')
        猜 = f'{S("猜位置")}/{位} = {round(100.0 * S("猜位置") / 位) if 位 else 0}%'
        t = S('total')
        追 = f'{S("hit")}/{t} = {round(100.0 * S("hit") / t) if t else 0}%'
        print(f'{("main_" + v):<10}{测:>9}{绑:>14}{位:>9}{猜:>14}{追:>16}')
    print('\n怎么读：**绑定率**对准 v2 规则 1，**猜位置率**对准 v2 规则 3 与 v3 的收窄。')
    print('数字可追溯只是兜底 —— 2026-09-07 实测它容易顶到 100%，分不出东西。')
    print('几个百分点的差别很可能只是噪声 —— 想说「有差别」，先用 --repeat 2 看同一臂')
    print('自己重复两次差多少。同臂重复的波动 ≥ 臂间差距时，这次实验的结论只能是「看不出来」。')


def main():
    if wants_help():
        print(__doc__)
        return
    role.require_prod('提示词消融实验（调用付费 API 抽取若干篇）', force=flag('--force'))

    臂 = [s.strip() for s in (opt('--arms') or 'v1,v2,v3').split(',') if s.strip()]
    模型 = opt('--model') or 默认模型
    厂商 = opt('--provider') or 默认厂商
    重复 = int(opt('--repeat') or 1)

    keys = [paths.check_key(k) for k in positionals()]
    if not keys:
        n = int(opt('--n') or 3)
        keys = [k for k in paths.all_keys() if os.path.exists(paths.fulltext(k))][:n]
    if not keys:
        print('没有可用的篇目（需要 parsed/full.md）。')
        return

    print(f'消融：提示词 {"/".join(臂)} × {len(keys)} 篇 × 重复 {重复} 次'
          f'  模型 {模型}（{厂商}）')
    print(f'共 {len(臂) * len(keys) * 重复} 次调用。只打印，不写盘。')

    结果 = []
    for key in keys:
        篇 = bench._load(key)
        if not 篇:
            print(f'[跳过] {key} 没有 parsed/full.md')
            continue
        源 = 篇['raw'] + '\n' + 篇['si']
        print(f'\n{"-" * 76}\n{key}  {篇["title"][:60]}')
        for 轮 in range(重复):
            for v in 臂:
                try:
                    data, 秒 = 跑一次(v, 模型, 厂商, 篇)
                except Exception as e:
                    print(f'  main_{v} 第{轮 + 1}轮 失败：{type(e).__name__} {e}')
                    continue
                m = bench._metrics(data, 源)
                m.update(对准规则的指标(data))
                结果.append({'key': key, 'arm': v, 'm': m, 'sec': 秒})
                print(f'  main_{v} 第{轮 + 1}轮：测量 {m["meas"]}，'
                      f'绑定 {m["绑定"]}，写位置 {m["有位置"]}（其中猜的 {m["猜位置"]}），'
                      f'可追溯 {m["hit"]}/{m["total"]}，{秒}s')
    if 结果:
        报告(结果, 臂)
    else:
        print('\n一次都没跑成 —— 不出结论。')


if __name__ == '__main__':
    main()
