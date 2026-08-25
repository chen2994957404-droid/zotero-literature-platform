# -*- coding: utf-8 -*-
"""控制面板启动器：pythonw 无窗口看不到报错，这里把启动期一切异常写进 panel_launch.log。

为什么存在：面板曾出现「双击.bat 后浏览器拒绝连接」但不知道原因——
pythonw 静默退出，错误无处可见。本启动器捕获 import 期与 main() 期的一切异常，
把 traceback 落盘，下次打不开时直接看日志就能定位。

用法: pythonw 平台管理\panel_launch.py（由 控制面板.bat 调用）
"""
import os, sys, io, time, traceback

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break
    _ROOT = parent
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 本文件夹，import panel 用
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'panel_launch.log')


def _log(text):
    try:
        with io.open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%m-%d %H:%M:%S")}] {text}\n')
    except Exception:
        pass


if __name__ == '__main__':
    _log('面板启动中…')
    try:
        import panel
        panel.main()
    except SystemExit:
        pass
    except BaseException:
        _log('===== 启动失败 =====')
        try:
            with io.open(LOG, 'a', encoding='utf-8') as f:
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise   # 保留原始退出行为（pythonw 静默），日志已有现场
