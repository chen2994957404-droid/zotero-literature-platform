# -*- coding: utf-8 -*-
"""shared.kernel.errors —— 异常分类。

**为什么需要它**（见 docs/架构重构_v2总体设计.md 阶段 1 第 7 项）：

重构前，一个步骤失败了，调用方**没有办法知道该怎么办**。
`zotero_watcher` 拉起子进程，只拿得到退出码和一坨 stdout；
积木抛出来的也多是裸 `Exception` / `RuntimeError`。于是所有失败都被同等对待 ——
「MineRU 这一秒过载了」和「你传的 key 根本不合法」走同一条路，
结果要么该重试的没重试，要么不该重试的白重试一轮。

分类的唯一目的是**让调用方能做决定**，所以分类维度不是「哪里出的错」，
而是**「该拿它怎么办」**：

    BadInputError        调用方传错了     → 重试没用，直接失败，修调用方
    ConfigError          用户没配好       → 重试没用，让用户去控制面板配
    DataError            我们自己的数据坏了 → 重试没用，要人来看
    ExternalServiceError 外面的世界出问题  → **可以重试**（限流/超时/临时 5xx）
      └ AuthError        密钥不对/过期     → 重试没用，让用户换密钥

判断「该不该重试」只用一个函数：`is_retryable(e)`。

用法：
    from shared.kernel import errors

    raise errors.ConfigError('MINERU_TOKEN 没配，去控制面板填')
    raise errors.RateLimited('MineRU 限流', retry_after=30)

    try:
        ...
    except Exception as e:
        if errors.is_retryable(e):
            ...退避重试...
        else:
            ...记下来，跳过这篇...

采用进度：`shared.kernel.paths` 已采用（BadKeyError）。各 adapters 在重构阶段 2 逐个改造 ——
在那之前，`is_retryable` 对不认识的异常一律返回 False（保守：宁可不重试，
也不要对着一个永远不会成功的调用烧钱）。
"""


class PlatformError(Exception):
    """平台自己抛出的错误的共同祖先。

    抓 `PlatformError` = 抓「我们预见到并分类过的失败」；
    抓到别的说明是真的没想到，应该让它冒上去。
    """
    retryable = False


# ── 重试也没用的四类 ──────────────────────────────────────────────────
class BadInputError(PlatformError, ValueError):
    """调用方给的参数不对（不是合法 key、文件不存在、类型不对）。

    继承 ValueError，这样旧代码里 `except ValueError` 的地方仍然能接住。
    """


class ConfigError(PlatformError):
    """用户还没配好（缺密钥、缺 Zotero 用户 ID、模型名写错）。

    抛这个的时候，消息里要写清**用户该去哪儿做什么**，
    因为它最终会显示给一个不懂编程的人看。
    """


class DataError(PlatformError):
    """我们自己的数据违反了契约（该有的 full.md 不在、meta.json 坏了）。

    这类错误意味着某个环节留下了半成品，需要人来看，不该悄悄重跑掩盖。
    """


class WrongMachineError(PlatformError):
    """这台机器不该做这件事（见 docs/两台机器的分工.md）。

    典型场景：在编程端（A 机）试图写回 Zotero、启动 watcher、跑全库批量作业。
    两台机器共用同一个 Zotero 账号，编程端一回写就污染真实文献库，
    而且会立刻同步到主力机 —— 这类错误没有「重试」一说，
    要么换机器做，要么明确知道自己在干什么再加 --force。
    """


class AuthError(PlatformError):
    """密钥无效、过期、余额不足 —— 属于外部服务，但重试一万次也不会好。"""


# ── 值得重试的一类 ────────────────────────────────────────────────────
class ExternalServiceError(PlatformError):
    """外部服务出问题：超时、连不上、5xx、临时故障。

    这是**唯一默认可重试**的分类。
    """
    retryable = True

    def __init__(self, msg, service=None):
        super().__init__(msg)
        self.service = service      # 'mineru' / 'zotero' / 'deepseek' / 'ollama' …


class ServiceUnavailable(ExternalServiceError):
    """服务没在跑（Ollama 没启动、Zotero 桌面没开）。

    技术上可重试，但通常需要用户先把服务打开 —— 消息里要说清是哪个。
    """


class RateLimited(ExternalServiceError):
    """被限流了。`retry_after` 是服务方给的建议等待秒数（没给就是 None）。"""

    def __init__(self, msg, service=None, retry_after=None):
        super().__init__(msg, service=service)
        self.retry_after = retry_after


def is_retryable(exc):
    """这个异常值不值得退避后重试？

    保守策略：只有明确标记为可重试的才返回 True。
    不认识的异常一律 False —— 宁可让一次失败暴露出来，
    也不要对着一个永远不会成功的调用反复烧钱。
    """
    return bool(getattr(exc, 'retryable', False))


def retry_after(exc, default=None):
    """服务方建议等多久再试（秒）。没有建议就返回 default。"""
    v = getattr(exc, 'retry_after', None)
    return default if v is None else v
