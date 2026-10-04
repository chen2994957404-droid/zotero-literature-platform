# -*- coding: utf-8 -*-
"""notify · 取全文撞上人机验证时，在主力机桌面弹一条提醒（2026-10-04，Claude Science 需求 P0-3）。

为什么要它：人机验证只有人能点，而调用方（Claude Science）在另一台机器上，用户不一定盯着
「取全文用的浏览器」。不喊一声，这篇就一直挂着 CAPTCHA_REQUIRED。

只用 Windows 自带的通知（PowerShell 调 WinRT），不装任何东西。弹不出来（不是 Windows、
进程不在用户的桌面会话里）就静默算了 —— 提醒是锦上添花，不许让取全文本身失败。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import subproc
from shared.kernel.log import get_logger

log = get_logger('getpdf')

# Win10 上借 PowerShell 自己的 AppId 发通知（不用注册新应用）
_APP_ID = r'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'


def _ps_quote(s):
    return "'" + (s or '').replace("'", "''") + "'"


def toast_script(title, body):
    """拼出弹通知的 PowerShell（单独成函数好测：引号必须转义，不然一个撇号就让整段语法错）。"""
    return (
        '[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; '
        '$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('
        '[Windows.UI.Notifications.ToastTemplateType]::ToastText02); '
        '$x = $t.GetElementsByTagName("text"); '
        '$x.Item(0).AppendChild($t.CreateTextNode(%s)) > $null; '
        '$x.Item(1).AppendChild($t.CreateTextNode(%s)) > $null; '
        '[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(%s).Show('
        '[Windows.UI.Notifications.ToastNotification]::new($t)); "sent"'
        % (_ps_quote(title), _ps_quote(body), _ps_quote(_APP_ID)))


def desktop(title, body):
    """弹一条桌面通知。返回是否发出去了。**不抛异常**。"""
    log.info('提醒：%s —— %s', title, body)
    if os.name != 'nt':
        return False
    try:
        return 'sent' in (subproc.powershell(toast_script(title, body), timeout=20) or '')
    except Exception as e:
        log.info('桌面提醒没发出去：%s', str(e)[:80])
        return False
