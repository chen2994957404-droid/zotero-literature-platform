# -*- coding: utf-8 -*-
"""静态检查：不许用没定义过的名字。

**为什么这条值得单独一个文件**：

重构阶段 1 把 `zotero_watcher` 里的日志改成 `core.log` 时，顺手删了 `_LOG_DIR`，
但函数体深处还有一行 `os.path.join(_LOG_DIR, 'watcher_heartbeat.txt')` 没改。

那次的验证是「模块能不能 import」—— **它通过了**，因为函数体里的 NameError
只有在那个函数真被调用时才炸。而那行是 watcher 主循环里写心跳的地方：
上线之后，看门狗会因为收不到心跳而反复重启 watcher，看起来像是「服务不稳定」，
根因却是一个删漏的变量名。

同一次检查还揪出 `lib_match` 里另一个同类问题。两个都在提交前被挡住了。

Python 没有编译期，这类错误只能靠静态分析提前发现。这个文件就是那道闸。

## 它能发现什么
    用了没导入的模块、删改后残留的旧变量名、拼错的函数名

## 它发现不了什么（不要指望）
    动态属性、getattr、字符串里的名字、类型错误、逻辑错误
"""
import ast
import builtins
import os

import pytest

from core import paths

ROOT = paths.ROOT
SKIP_DIRS = set(paths.NOISE_DIRS) | {'归档_旧版本'}

# 模块级本来就存在的名字
_MODULE_DUNDERS = {'__file__', '__name__', '__doc__', '__package__',
                   '__spec__', '__loader__', '__builtins__', '__path__'}
_BUILTINS = set(dir(builtins)) | _MODULE_DUNDERS


def _py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


def _bound_names(tree):
    """收集这个文件里「被定义过」的所有名字。

    刻意放宽（不做作用域分析）：宁可漏报，不可误报 ——
    一个天天误报的检查，很快就会被人无视，那还不如没有。
    """
    bound = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)                      # 赋值 / for / with as / 海象 / 推导式
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                bound.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)                    # except X as e
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound.update(n.names)
    return bound


def _used_names(tree):
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def test_没有用到未定义的名字():
    offenders = []
    for f in _py_files():
        rel = os.path.relpath(f, ROOT).replace('\\', '/')
        try:
            tree = ast.parse(open(f, encoding='utf-8').read(), f)
        except SyntaxError as e:
            offenders.append(f'{rel}:{e.lineno}: 语法错误 {e.msg}')
            continue
        undefined = _used_names(tree) - _bound_names(tree) - _BUILTINS
        if undefined:
            offenders.append(f'{rel}: {sorted(undefined)}')
    assert not offenders, (
        '这些名字用了但没有定义（删改后残留 / 忘了导入 / 拼错）：\n  '
        + '\n  '.join(offenders)
        + '\n注意：模块能 import 成功不代表没问题 —— 函数体里的 NameError'
          '只有那个函数被调用时才炸。')


def test_检查器本身能抓到问题(tmp_path):
    """给闸门本身上一道闸：确认它真的会报，而不是永远绿。"""
    bad = tmp_path / 'bad.py'
    bad.write_text('def f():\n    return _被删掉的变量 + 1\n', encoding='utf-8')
    tree = ast.parse(bad.read_text(encoding='utf-8'))
    assert '_被删掉的变量' in (_used_names(tree) - _bound_names(tree) - _BUILTINS)


def test_不会误报常见写法(tmp_path):
    """except as / with as / 推导式 / 海象 / __file__ 都不该被误报。"""
    src = (
        'import os\n'
        'HERE = os.path.dirname(__file__)\n'
        'def f(items):\n'
        '    try:\n'
        '        pass\n'
        '    except ValueError as e:\n'
        '        print(e)\n'
        '    with open(HERE) as fh:\n'
        '        print(fh)\n'
        '    xs = [y * 2 for y in items]\n'
        '    if (n := len(xs)) > 0:\n'
        '        print(n)\n'
        '    return xs\n'
    )
    p = tmp_path / 'ok.py'
    p.write_text(src, encoding='utf-8')
    tree = ast.parse(src)
    assert not (_used_names(tree) - _bound_names(tree) - _BUILTINS)
