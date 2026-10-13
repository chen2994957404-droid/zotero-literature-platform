# -*- coding: utf-8 -*-
"""shared.kernel.role —— 这台机器是什么角色。

**为什么需要它**（见 `docs/howto/两台机器的分工.md`）：本平台跑在两台机器上：

    A 机 = 编程端   有 Claude Code，改代码的唯一入口
    B 机 = 运行端   Ollama、看门狗、文献库应用、data/ 权威副本

在编程端误跑一次全库批量作业，烧的是真钱；起常驻服务会跟主力机抢活。
分工写在文档里没有强制力 —— 人会忘，LLM 更会忘。所以让代码自己知道在哪台机器上。

三档：`dev`（编程端，拒绝）· `prod`（主力机，全部允许）· `test`（编程端测试档，允许，产物只在本机）。
（test 原来的意思是「编程端接测试 Zotero 账号」，还要核对写回目标是测试库；
2026-10-13 Zotero 移出平台，那道核对没有对象了，test 就是「编程端也放行」。）

## 用法

```python
from shared.kernel import role

role.require_prod('全库重抽', force=flag('--force'))   # dev 上抛 WrongMachineError；显式 --force 可越过
```

## 默认值：未设置时按 `dev` 处理（fail safe）

默认 `prod` → 编程端在配置好之前**毫无保护**；默认 `dev` → 主力机在配置好之前会**明确拒绝并告诉你怎么改**。
所以默认 `dev`。主力机第一次部署时在控制面板把角色设成 `prod` 即可。
"""
from shared.kernel import errors

DEV = 'dev'        # 编程端：有 Claude Code，改代码的地方
PROD = 'prod'      # 运行端：跑服务、持有权威数据的地方
TEST = 'test'      # 编程端测试档：允许跑（产物只在本机）
VALID = (DEV, PROD, TEST)

_LABEL = {DEV: '编程端（A 机）', PROD: '运行端（B 机）',
          TEST: '编程端·测试档（A 机）'}


def current():
    """本机角色。未设置或值非法时一律按 dev（安全侧）。"""
    # 延迟 import：shared.kernel.config 会读 .env / 凭据库，不该在模块导入时就触发
    from shared.kernel.config import get_site
    try:
        v = (get_site('ROLE') or '').strip().lower()
    except Exception:
        v = ''
    return v if v in VALID else DEV


def is_dev():
    return current() == DEV


def is_prod():
    return current() == PROD


def is_test():
    return current() == TEST


def label(r=None):
    """给人看的角色名。"""
    r = r or current()
    return _LABEL.get(r, r)


def is_configured():
    """角色是**显式配过**的，还是在吃默认值？（体检要区分这两种情况）

    刻意绕开 get_site —— 它会把内置默认值 'dev' 一起返回，
    那样就永远分不清「配成了 dev」和「压根没配」。
    """
    from shared.kernel.config import get_key
    try:
        return (get_key('ROLE', default='') or '').strip().lower() in VALID
    except Exception:
        return False


def require_prod(action, force=False):
    """这件事只允许在运行端做。在编程端调用会抛 WrongMachineError。

    `action` 写清楚是什么操作，它会出现在报错里给用户看 ——
    报错要让一个不懂编程的人看懂该怎么办。

    `force=True` 用于用户显式加了 `--force` 的场合：
    他知道自己在干什么，就放行，但打印一行警告留痕。
    """
    if is_prod():
        return
    if is_test():
        return
    if force:
        print(f'⚠ 已用 --force 越过机器角色检查：在{label()}上执行「{action}」。')
        return
    hint = ('' if is_configured() else
            '（本机没设置角色，按最安全的 dev 处理）')
    raise errors.WrongMachineError(
        f'「{action}」不能在{label()}上做{hint}。\n'
        f'  · 如果这台是主力机：打开控制面板，把「机器角色」改成 运行端(prod)\n'
        f'  · 如果这台是编程端：这件事请到主力机上做\n'
        f'  · 确实知道自己在干什么：命令行加 --force\n'
        f'  详见 docs/howto/两台机器的分工.md')
