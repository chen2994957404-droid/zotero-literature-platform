# -*- coding: utf-8 -*-
"""core.role —— 这台机器是什么角色。

**为什么需要它**（见 `docs/两台机器的分工.md`）：

本平台跑在两台机器上，**共用同一个 Zotero 账号**：

    A 机 = 编程端   有 Claude Code，改代码的唯一入口
    B 机 = 运行端   Ollama、watcher、4 个自启任务、workflow_data 权威副本

编程端做验证时如果回写 Zotero（打标签、传附件、改名），
**污染的是真实文献库，而且立刻同步到主力机**。同理，在编程端误跑一次
全库批量作业，烧的是真钱。

分工写在文档里没有强制力 —— 人会忘，LLM 更会忘。所以让代码自己知道在哪台机器上。

## 现状为什么不能靠「反正编程端写不了」

编程端的 `ZOTERO_USER_ID` 是 `0`（Zotero 本地 API 的约定值），
拿这个 id 去写 `api.zotero.org` 会失败 —— 但这是**巧合形成的保护，不是设计**。
一旦有人为了让本地 API 表现一致而把它改成真实数字 id，
编程端立刻就获得了改写真实文献库的能力，而且没有任何东西会拦。

## 用法

```python
from core import role

role.require_prod('写回 Zotero')            # 编程端上直接抛 WrongMachineError
role.require_prod('全库重抽', force=flag('--force'))   # 显式 --force 可越过

if role.is_dev():
    out_dir = sandbox_dir           # 编程端把产物写到沙盒，不碰权威数据
```

## 默认值：未设置时按 `dev` 处理（fail safe）

两种默认的代价不对称：

- 默认 `prod` → 编程端在配置好之前**毫无保护**，一次手滑就静默污染真实数据，
  而且很难发现是什么时候被改的
- 默认 `dev` → 主力机在配置好之前会**明确拒绝并告诉你怎么改**，
  响亮、立刻可修

所以默认 `dev`。主力机第一次部署时在控制面板把角色设成 `prod` 即可
（`更新平台.bat` 会提醒）。
"""
from core import errors

DEV = 'dev'        # 编程端：有 Claude Code，改代码的地方
PROD = 'prod'      # 运行端：跑服务、持有权威数据的地方
VALID = (DEV, PROD)

_LABEL = {DEV: '编程端（A 机）', PROD: '运行端（B 机）'}


def current():
    """本机角色。未设置或值非法时一律按 dev（安全侧）。"""
    # 延迟 import：core.config 会读 .env / 凭据库，不该在模块导入时就触发
    from core.config import get_site
    try:
        v = (get_site('ROLE') or '').strip().lower()
    except Exception:
        v = ''
    return v if v in VALID else DEV


def is_dev():
    return current() == DEV


def is_prod():
    return current() == PROD


def label(r=None):
    """给人看的角色名。"""
    r = r or current()
    return _LABEL.get(r, r)


def is_configured():
    """角色是**显式配过**的，还是在吃默认值？（体检要区分这两种情况）

    刻意绕开 get_site —— 它会把内置默认值 'dev' 一起返回，
    那样就永远分不清「配成了 dev」和「压根没配」。
    """
    from core.config import get_key
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
    if force:
        print(f'⚠ 已用 --force 越过机器角色检查：在{label()}上执行「{action}」。'
              f'两台共用同一个 Zotero 账号，改动会同步过去。')
        return
    hint = ('' if is_configured() else
            '（本机没设置角色，按最安全的 dev 处理）')
    raise errors.WrongMachineError(
        f'「{action}」不能在{label()}上做{hint}。\n'
        f'  · 如果这台是主力机：打开控制面板，把「机器角色」改成 运行端(prod)\n'
        f'  · 如果这台是编程端：这件事请到主力机上做\n'
        f'  · 确实知道自己在干什么：命令行加 --force\n'
        f'  详见 docs/两台机器的分工.md')
