# -*- coding: utf-8 -*-
"""静态类型检查（pyright）—— 给 Python 补一道「写完就报错」的关，且只许变好不许变坏。

**为什么要它**（2026-09-19 立）：
    Python 没有编译期。用了不存在的属性、把可能是 None 的东西直接 `.get()`、
    参数类型传错 —— 这些都要等到那一行真的跑到才炸，而那一行往往在花钱的
    流水线深处。`test_no_undefined_names` 只管「名字有没有定义」，这里管
    「定义了的东西用得对不对」。第一次跑就顺手揪出 3 处躲过守卫的 sys.path 补丁。

**为什么是「基线」而不是「零错误」**：
    老代码从没按类型检查写过，首跑 223 条。要求一次清零不现实，硬清会把
    时间花在给没坏的代码加标注上。所以记一份**每个文件的现有错误数**当基线：
    - 哪个文件的错误数**超过**基线 → 红（新写的代码引入了类型错）
    - 哪个文件**少于**基线 → 提示把基线收紧（`--基线` 重记）
    这就是「棘轮」：只能拧紧，不能松。

## 用法
    python host/doctor/typecheck.py            # 对照基线，超了就非零退出
    python host/doctor/typecheck.py --基线      # 修完一批之后重记基线（只许变小，变大会拒绝）
    python host/doctor/typecheck.py --全部      # 打印所有错误（按文件）

## 它发现不了什么（不要指望）
    没有类型标注的函数之间传的东西大多是 Unknown，pyright 对 Unknown 不报错。
    所以它对**有标注的库调用**（标准库、typeshed 里的第三方）最敏感，对我们自己
    函数之间的传参基本盲。要它更有用，新代码给公开函数的参数与返回值写标注。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io
import json

from shared.kernel import paths
from shared.kernel.cli import flag, wants_help
from shared.kernel.subproc import run as _run

ROOT = paths.ROOT
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'type_baseline.json')


def is_available():
    """本机装了 pyright 没有（`pip install pyright`，首次运行会自己下 node 版内核）。"""
    try:
        import pyright  # noqa: F401
        return True
    except ImportError:
        return False


def run():
    """跑一遍 pyright → {相对路径: 错误数}，另返回原始诊断列表（给 --全部 用）。"""
    r = _run([sys.executable, '-m', 'pyright', '--outputjson'], cwd=ROOT, timeout=600)
    # pyright 有错误时退出码是 1，但 JSON 照样完整；只有解析不了才算工具本身坏了
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError('pyright 没给出结果：' + (r.stderr or r.stdout or '')[:400])
    counts = {}
    diags = []
    for d in data.get('generalDiagnostics', []):
        if d.get('severity') != 'error':
            continue
        rel = os.path.relpath(d['file'], ROOT).replace(os.sep, '/')
        counts[rel] = counts.get(rel, 0) + 1
        diags.append((rel, d['range']['start']['line'] + 1,
                      d.get('rule', ''), d['message'].split('\n')[0]))
    return counts, diags


def load_baseline():
    if not os.path.exists(BASELINE):
        return {}
    return json.load(io.open(BASELINE, encoding='utf-8'))


def compare(counts, baseline):
    """→ (变坏的 [(文件, 基线, 现在)], 变好的 [(文件, 基线, 现在)])。"""
    worse, better = [], []
    for f in sorted(set(counts) | set(baseline)):
        was, now = baseline.get(f, 0), counts.get(f, 0)
        if now > was:
            worse.append((f, was, now))
        elif now < was:
            better.append((f, was, now))
    return worse, better


def write_baseline(counts):
    json.dump(dict(sorted(counts.items())), io.open(BASELINE, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


def main():
    if wants_help():
        print(__doc__)
        return 0
    if not is_available():
        print('没装 pyright：pip install pyright')
        return 2
    counts, diags = run()
    total = sum(counts.values())
    if flag('--全部'):
        for rel, ln, rule, msg in diags:
            print(f'{rel}:{ln}  [{rule}] {msg}')
        print(f'\n共 {total} 条，{len(counts)} 个文件')
        return 0
    baseline = load_baseline()
    worse, better = compare(counts, baseline)
    if flag('--基线'):
        if worse and baseline:          # 第一次记（还没有基线）直接放行
            print('拒绝重记：有文件比基线更差，基线只许拧紧。先修掉：')
            for f, was, now in worse:
                print(f'  {f}: {was} → {now}')
            return 1
        write_baseline(counts)
        print(f'基线已记：{total} 条错误，{len(counts)} 个文件 → {os.path.relpath(BASELINE, ROOT)}')
        return 0
    print(f'类型错误 {total} 条（基线 {sum(baseline.values())}）')
    for f, was, now in worse:
        print(f'  ✗ {f}: 基线 {was} → 现在 {now}')
        for rel, ln, rule, msg in diags:
            if rel == f:
                print(f'      {ln}: [{rule}] {msg}')
    for f, was, now in better:
        print(f'  ✓ {f}: 基线 {was} → 现在 {now}（可以 --基线 收紧）')
    return 1 if worse else 0


if __name__ == '__main__':
    sys.exit(main())
