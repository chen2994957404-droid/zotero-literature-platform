# -*- coding: utf-8 -*-
"""重抽向导：列清单 → 问用哪个模型 → 跑 → 出结果。给主力机双击用。

**为什么整个流程写在 Python 里而不是 .bat 里**（踩坑 #72）：
`chcp 65001` 的 .bat 一旦带标签（`:run` / `goto`），cmd 会按字节偏移重新定位，
把后面那条含中文路径的命令截断成半个字符 —— 表现为
「The system cannot find the path specified.」，而前一条一模一样的命令却正常。
**中文交互放 Python，.bat 只留三行 ASCII**，这类问题就不存在了。

用法：双击根目录的「重抽缺SI的文献.bat」；或
  python -m tools.extract.wizard            # 交互问
  python -m tools.extract.wizard --local     # 不问，直接用本地模型
  python -m tools.extract.wizard --cloud     # 不问，直接用云端
  python -m tools.extract.wizard --cloud --no-eval   # 云端但不做自检重抽（省一半调用）
  python -m tools.extract.wizard --n 5       # 只跑前 5 篇（先看看花多少钱）

**每篇跑完会报这一篇花了多少 token 和大约多少钱**（2026-08-28 加）：
在此之前谁也说不出「一篇要多少钱」，用户只能靠余额掉得快不快来判断，
于是跑到第 7 篇就不敢跑了。看不见的开销没法优化，也没法让人放心。
"""
import io
import os
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters.llm_client import usage_snapshot
from shared.kernel import paths, role
from shared.kernel.cli import flag, opt
from shared.kernel.config import drop_stale_env
from shared.domain import schema
from tools import extract

LINE = '=' * 64


def _index_stats():
    """「各档次 × 各字段有值率」，用来给用户看重抽前后的变化。

    R7 窗之前这里问的是查询库（`tools` 调 `tools`，违反第三节硬规则 2）。
    改成直接算：口径没变 —— 两边都走 `shared.domain.schema.coverage`，
    那才是这个数的唯一定义；也不用再为一段展示文字把整个查询库拖进来。
    """
    try:
        return schema.coverage(extract.all_records(), list(schema.SCHEMA.keys()))
    except Exception:
        return {}

# DeepSeek 官方价（2026-08-28 查 api-docs.deepseek.com/quick_start/pricing，USD / 百万 token）：
#   v4-flash  输入未命中缓存 0.44 / 输出 1.32（高峰价；低谷价减半）
#   v4-pro    输入未命中缓存 1.32 / 输出 3.96
# ⚠ 这是**估算**：不知道这次是不是低谷时段、也不知道缓存命中多少，
#   所以按高峰价、全部未命中算 —— **报出来的数只会高不会低**。真实账单以官网为准。
PRICE_USD = {'deepseek-v4-flash': (0.44, 1.32), 'deepseek-v4-pro': (1.32, 3.96)}
USD_TO_CNY = 7.2      # 粗略汇率，够看个量级


def _money(u0, u1, model):
    """两次 usage 快照之差 → (提示 token, 输出 token, 估算人民币)。"""
    pin = u1['prompt'] - u0['prompt']
    pout = u1['completion'] - u0['completion']
    rate = PRICE_USD.get(model) or PRICE_USD['deepseek-v4-flash']
    cny = (pin * rate[0] + pout * rate[1]) / 1e6 * USD_TO_CNY
    return pin, pout, cny


def _log_path():
    return paths.log('si_rerun')


def ask_provider():
    """问一句用哪个模型。返回 'deepseek' / 'ollama' / None（放弃）。"""
    print('\n 用哪个模型抽？（每篇跑完都会告诉你这一篇花了多少钱）')
    print('   [1] 云端 DeepSeek —— 最准：抽完让模型对照原文自检一轮，漏了就重抽')
    print('   [2] 云端 DeepSeek · 省钱模式 —— 不做自检，调用数减半，准确度略降')
    print('   [3] 本地模型 Ollama —— 免费不限量，慢（约两分钟一篇），准确度低一档')
    print('       （本地抽的会标成「本地+SI」档，绝不冒充云端结果）')
    try:
        ans = input('\n 输入 1 / 2 / 3 后回车（直接关窗口 = 放弃）：').strip()
    except EOFError:
        return None
    if ans == '2':
        os.environ['EXTRACT_NO_EVAL'] = '1'      # 不做自检重抽 —— 调用数直接减半
    return {'1': 'deepseek', '2': 'deepseek', '3': 'ollama'}.get(ans)


def main():
    print(LINE)
    print(' 重抽「有补充材料、但当初抽取没读它」的文献')
    print()
    print(' 为什么要重抽：投料量、配比、温度时间几乎只写在补充材料里，')
    print(' 2026-08-28 之前的抽取根本没打开过它（踩坑 #68）。')
    print(' 不重新解析 PDF，不动 Zotero，旧结果会先自动备份。')
    print(LINE)

    keys = extract.si_pending_keys()
    print(f'\n 有 SI 但抽取时没读 SI 的文献：{len(keys)} 篇')
    for k in keys:
        print('   ' + k)
    if not keys:
        print('\n 没有要重抽的，收工。')
        return

    if flag('--local'):
        provider = 'ollama'
    elif flag('--cloud'):
        provider = 'deepseek'
    else:
        provider = ask_provider()
    if not provider:
        print('\n 没选，退出（什么也没动）。')
        return
    os.environ['EXTRACT_PROVIDER'] = provider
    name = '本地 Ollama' if provider == 'ollama' else '云端 DeepSeek'

    # 双击出来的窗口继承的是 explorer 的环境，里面可能还躺着作废的旧密钥（踩坑 #73）。
    # 凭据库里有新的就用新的 —— 否则下面 28 篇会一篇不落地全 401。
    drop_stale_env(log=print)

    # **先验一把再开跑**：上一版一头扎进去，烧了 28 次失败才发现密钥不对。
    # 「验证要验到事情真的发生」（踩坑 #66 的判据），这里就是那个验证点。
    if provider == 'deepseek':
        from shared.adapters.llm_client import check_key
        ok, msg = check_key()
        print(f'\n 密钥自检：{msg}')
        if not ok:
            print('\n 密钥不可用，什么都没动。请在控制面板里重填密钥并点「测一测」，')
            print(' 如果面板显示的是「⚠ 环境变量」，先点旁边的「清除这个环境变量」，')
            print(' 然后**注销一次 Windows 再登录**（双击出来的程序继承的是登录时的环境）。')
            return

    # 全库作业只允许在运行端跑（见 docs/两台机器的分工.md）
    role.require_prod(f'批量重抽结构化字段（{name}）', force=flag('--force'))

    dest = extract.backup_records(keys)
    if dest:
        print(f'\n 旧结果已备份 {len(keys)} 份 → {dest}')

    log = io.open(_log_path(), 'w', encoding='utf-8')

    def say(*a):
        """同时打给窗口和日志 —— 窗口给人看，日志给事后排查。"""
        msg = ' '.join(str(x) for x in a)
        print(msg, flush=True)
        log.write(msg + '\n')
        log.flush()

    if flag('--no-eval'):
        os.environ['EXTRACT_NO_EVAL'] = '1'      # 不做自检重抽 —— 调用数直接减半
    n_limit = opt('--n')
    if n_limit:
        keys = keys[:int(n_limit)]
        print(f'\n 只跑前 {len(keys)} 篇（--n {n_limit}）')

    before = _index_stats()
    say(f'\n 开始（{name}）。这个窗口要一直开着。\n')
    t0 = time.time()
    done = failed = 0
    u_start = usage_snapshot()
    model = extract._model()
    for i, key in enumerate(keys, 1):
        say(f'[{i}/{len(keys)}] {key}  （已用时 {round(time.time() - t0)}s）')
        u0 = usage_snapshot()
        rec = extract.run(key, force=True, log=say)
        if rec:
            done += 1
            say(f'    合成条件: {str(rec.get("synthesis_conditions"))[:100]}')
        else:
            failed += 1
        if provider == 'deepseek':
            pin, pout, cny = _money(u0, usage_snapshot(), model)
            say(f'    这篇花了：输入 {pin} + 输出 {pout} token ≈ {cny:.3f} 元')
    extract.write_compare_table()
    after = _index_stats()

    say(f'\n{LINE}')
    say(f' 完成：成功 {done}，失败 {failed}，用时 {round(time.time() - t0)}s')
    say('\n 各档次的字段有值率（前 → 后）：')
    tiers = [t for t in schema.TIER_ORDER if t in before or t in after]
    for t in tiers:
        b, a = before.get(t), after.get(t)
        say(f'  【{t}】{b["n"] if b else 0} 篇 → {a["n"] if a else 0} 篇')
        for f in ('precursors', 'synthesis_conditions', 'characterization', 'key_properties'):
            bv = round(b['rate'][f] * 100) if b else 0
            av = round(a['rate'][f] * 100) if a else 0
            say(f'    {f:22s} {bv:3d}% → {av:3d}%')
    say(f'\n 日志：{_log_path()}')
    say(f' 对比表：{paths.compare()}')
    log.close()


if __name__ == '__main__':
    main()
