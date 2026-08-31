# -*- coding: utf-8 -*-
"""shared.kernel.log —— 统一的日志落点。

**为什么需要它**（见 docs/架构重构_v2总体设计.md 阶段 1 第 6 项）：

重构前，同一件事有三种写法，且都有各自的毛病：

    精读 watcher     把内置的 `print` 整个换掉（`_print = print; def print(...)`）
    看门狗           自己写一个 def log(msg)
    库房维护/auto_sync.py  又自己写一个 def log(msg)

劫持 `print` 尤其糟：读代码的人看到 `print('...')` 会以为只是打屏，
实际上它在往文件里写；而且这个 hack 无法被 import 复用，只能复制粘贴。

三者还共有一个真问题：**没有任何一个会轮转**。
watcher 是常驻服务，日志文件只会一直长下去。

## 用法

```python
from shared.kernel.log import get_logger

log = get_logger('zotero_watcher')

log('开始处理', key)          # 像 print 一样用（这是为了让老代码零成本迁移）
log.warn('PDF 找不到')
log.error('MineRU 失败', exc)
```

每行形如 `[2026-08-26 17:54:01] 开始处理 2T6H4S3D`，同时打到屏幕和
`data/logs/<name>.log`；文件超过 5 MB 自动轮转，保留 3 份历史。

## 设计取舍

- 底层用标准库 `logging`（宪法【首要判据】：轮转这类稳定又琐碎的活，
  用现成的十年不变的实现，不自己写）。
- 但**对外只暴露一个像 `print` 的可调用对象** —— 因为项目里现有的几十处调用
  就长这样，换成 `logger.info(...)` 要改几十处、且对不懂编程的主导者更难读。
  这就是「稳定的接口自己定，多变的实现用现成」在小处的一次应用。
- 写日志失败**绝不能让主流程崩**（磁盘满、文件被占用都可能发生）。
"""
import logging
import logging.handlers
import os
import sys

from shared.kernel import paths

_MAX_BYTES = 5 * 1024 * 1024      # 单个日志文件上限
_BACKUPS = 3                      # 保留几份历史
_FMT = '[%(asctime)s] %(message)s'
_DATEFMT = '%Y-%m-%d %H:%M:%S'

_cache = {}


class Log:
    """像 print 一样调用，同时落到屏幕和文件。"""

    def __init__(self, name, to_stdout=True):
        self.name = name
        self._logger = logging.getLogger('platform.' + name)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False          # 不往 root 冒泡，避免重复打印
        fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)
        target = paths.log(name)

        # 已经挂着的、且指向同一个文件的轮转 handler —— 复用，不重复挂
        # （重复挂会让每条日志写两遍；这是 logging 最常见的坑）
        want = os.path.normcase(os.path.abspath(target))
        have_file = have_stdout = False
        for h in list(self._logger.handlers):
            if isinstance(h, logging.handlers.RotatingFileHandler):
                if os.path.normcase(os.path.abspath(h.baseFilename)) == want:
                    have_file = True
                else:
                    # 目标文件变了（换了日志目录 / 测试里重定向），旧的留着没意义
                    h.close()
                    self._logger.removeHandler(h)
            elif isinstance(h, logging.StreamHandler):
                have_stdout = True

        if not have_file:
            try:
                os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
                fh = logging.handlers.RotatingFileHandler(
                    target, maxBytes=_MAX_BYTES, backupCount=_BACKUPS,
                    encoding='utf-8')
                fh.setFormatter(fmt)
                self._logger.addHandler(fh)
            except Exception:
                pass                             # 写不了文件也不能让主流程挂掉
        if to_stdout and not have_stdout:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            self._logger.addHandler(sh)

    # ── 像 print 一样用 ──
    def __call__(self, *args, **kwargs):
        """`log('a', 'b')` 等价于 `print('a', 'b')`，外加时间戳和落盘。

        接受并忽略 print 的 `flush=` 等关键字，方便老代码原样替换。
        """
        sep = kwargs.get('sep', ' ')
        self._emit(logging.INFO, sep.join(str(a) for a in args))

    def info(self, *args):
        self(*args)

    def warn(self, *args):
        self._emit(logging.WARNING, '⚠ ' + ' '.join(str(a) for a in args))

    def error(self, *args):
        self._emit(logging.ERROR, '✗ ' + ' '.join(str(a) for a in args))

    def _emit(self, level, msg):
        try:
            self._logger.log(level, msg)
        except Exception:
            # 日志系统本身出问题时，至少别丢掉这条消息，也别让调用方崩
            try:
                print(msg)
            except Exception:
                pass

    @property
    def path(self):
        """这个 logger 写到哪个文件（面板要展示日志时用）。"""
        return paths.log(self.name)


def get_logger(name, to_stdout=True):
    """拿一个日志器。同名多次调用返回同一个（不会重复挂 handler）。"""
    key = (name, to_stdout)
    if key not in _cache:
        _cache[key] = Log(name, to_stdout=to_stdout)
    return _cache[key]
