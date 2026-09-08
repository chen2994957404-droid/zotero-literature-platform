# -*- coding: utf-8 -*-
"""remote.py 的离线测试 —— **不连任何机器**，只验命令怎么拼、诊断怎么分、配置怎么选。

为什么这些值得测：这个工具存在的一半理由就是「把看起来一样、根因完全不同的
几种失败分开」。分错了，人就会照着错方向查 —— 真事：一次账号名写错，
报的却是密钥的错，白查了两轮。**分类错的诊断比没有诊断更贵。**

跑法：`python -m pytest tests -q`（在仓库根目录）
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import remote  # noqa: E402


# ───────── 配置：选哪台机器 ─────────

CONF = {
    'default': 'b',
    'machines': {
        'a': {'hosts': ['10.0.0.1'], 'user': 'u1', 'key': '~/.ssh/k1',
              'local': 'D:/dev/proj-a'},
        'b': {'hosts': ['10.0.0.2'], 'user': 'u2', 'key': '~/.ssh/k2',
              'local': 'D:/dev/proj-b'},
    },
}


def test_按当前目录自动选机器():
    """**在哪个项目里就连哪台** —— 忘了加参数而连错机器，是这类工具最贵的一种错。"""
    assert remote.pick_machine(CONF, cwd='D:/dev/proj-a/tools')[0] == 'a'
    assert remote.pick_machine(CONF, cwd='D:/dev/proj-b')[0] == 'b'


def test_目录对不上就用默认的():
    assert remote.pick_machine(CONF, cwd='C:/somewhere/else')[0] == 'b'


def test_显式指定优先于一切():
    assert remote.pick_machine(CONF, name='a', cwd='D:/dev/proj-b')[0] == 'a'


def test_配置缺项时不会崩():
    """没有配置文件也要能 import、能打印帮助 —— 否则第一次用的人只看到一个 traceback。"""
    flat = remote.resolve(conf={})
    assert flat['hosts'] == [] and flat['name'] == ''
    assert flat['job_task'] and flat['job_dir'], '这两项要有兜底默认值'


def test_读不动的配置文件不当成空配置(tmp_path, capsys):
    """TOML 写坏了要**说出来**。静默当成空配置，表现是「连不上」，会查错方向。"""
    bad = tmp_path / 'machines.toml'
    bad.write_text('这不是 TOML [[[', encoding='utf-8')
    assert remote.load_conf(str(bad)) == {}
    assert '配置文件读不动' in capsys.readouterr().out


# ───────── 连接参数 ─────────

def test_命令一定套着UTF8外壳():
    """对面控制台默认 GBK。不套壳中文输出全是乱码，而且乱得像数据坏了。"""
    argv = remote.ssh_argv('Write-Output "测试"')
    script = argv[-1]
    assert 'OutputEncoding' in script and 'UTF8' in script
    assert "PYTHONIOENCODING='utf-8'" in script
    assert script.endswith('Write-Output "测试"'), '外壳要在前面，真正的命令在后面'


def test_连接参数齐全():
    """`BatchMode=yes` 少了会在没有密钥时**挂住等密码**（自动化里就是永久卡死）。"""
    argv = remote.ssh_argv('x')
    assert 'BatchMode=yes' in argv, '没有 BatchMode，连不上时会卡在等密码'
    assert any(a.startswith('ConnectTimeout=') for a in argv), '没有超时会挂很久'


def test_ssh命令行认得出指定的地址():
    argv = remote.ssh_argv('x', host='10.9.9.9')
    assert f'{remote.USER}@10.9.9.9' in argv


# ───────── 诊断：这几条在这边看起来都像「连不上」，该查的方向却完全不同 ─────────

@pytest.mark.parametrize('stderr, want', [
    ('kex_exchange_identification: Connection closed by remote host', '睡眠'),
    ('ssh: connect to host 1.2.3.4 port 22: Connection timed out', '别先认定它睡了'),  # preflight-ok 报错样例里的假地址
    ('Permission denied (publickey,password).', '账号不存在'),
    ('Host key verification failed.', '主机密钥'),
])
def test_几种失败要分得开(stderr, want):
    tip = remote.diagnose(stderr)
    assert want in tip, f'{stderr[:40]!r} 的诊断没提到「{want}」，实际：{tip[:80]}'


def test_没见过的错误不硬编一个原因():
    """认不出来就返回空，让原始报错自己说话。

    硬套一个最像的原因，会把人**主动**带偏 —— 比不给建议更糟。
    """
    assert remote.diagnose('some totally unexpected failure') == ''
    assert remote.diagnose('') == ''


def test_断开的诊断要把两种可能都说出来():
    """**言之凿凿的错判比不给判断更糟。**

    第一版只写了「机器在睡眠」，结果连一个根本不存在的地址也被诊断成睡眠 ——
    而真相是本机代理接管了连接。
    """
    tip = remote.diagnose('kex_exchange_identification: Connection closed by remote host')
    assert '睡眠' in tip, '少了「对面在睡」这一种'
    assert '代理' in tip, '少了「本机代理接管」这一种'
    assert '不存在' in tip, '少了那条能分清两者的判据'


def test_超时的诊断不许只说关机():
    """同一个教训换了个错误码复发过一次：断的往往是**路**，不是机器。"""
    tip = remote.diagnose('ssh: connect to host 1.2.3.4 port 22: Connection timed out')  # preflight-ok 报错样例里的假地址
    assert 'ping' in tip, '少了「别拿 ping 当判据」——它在不回 ICMP 的机器上什么都不证明'
    assert '代理' in tip and '电源事件' in tip


def test_滤掉ssh客户端自己的告警():
    """噪音盖住信号就不只是噪音：失败时人往往只看最后一行，而告警恰恰在最后。"""
    out = remote.clean('真正的输出\nThe server may need to be upgraded (post-quantum)')
    assert out == '真正的输出'


# ───────── 候选地址 ─────────

def test_多个候选地址按顺序试(monkeypatch):
    """局域网地址排前面 —— 直连比绕一圈快得多。"""
    monkeypatch.setattr(remote, 'HOSTS', ['10.0.0.1', '10.0.0.2'])
    monkeypatch.setattr(remote, 'LAST_GOOD', '/nonexistent/nope.txt')
    assert remote.candidates() == ['10.0.0.1', '10.0.0.2']


def test_上次通的那个排到最前面(monkeypatch, tmp_path):
    """**这是为了省时间**：一个连不上的地址要等满 ConnectTimeout 才放弃，
    候选多了每次都从头试，会让每条命令都白等十几秒。
    """
    f = tmp_path / 'last.txt'
    f.write_text('10.0.0.2\n', encoding='utf-8')
    monkeypatch.setattr(remote, 'HOSTS', ['10.0.0.1', '10.0.0.2'])
    monkeypatch.setattr(remote, 'LAST_GOOD', str(f))
    assert remote.candidates() == ['10.0.0.2', '10.0.0.1']


def test_记着的地址已经不在候选里就忽略它(monkeypatch, tmp_path):
    """换了组网方案之后，旧的虚拟地址不该还被优先试。"""
    f = tmp_path / 'last.txt'
    f.write_text('192.168.99.99\n', encoding='utf-8')
    monkeypatch.setattr(remote, 'HOSTS', ['10.0.0.1'])
    monkeypatch.setattr(remote, 'LAST_GOOD', str(f))
    assert remote.candidates() == ['10.0.0.1']


# ───────── 换不换地址重试（这条关系到钱）─────────

def _fake_run(calls, rc_by_host):
    """假的 run()：记下每次用的地址，按预设返回退出码。"""
    def fake(argv, timeout=180):
        host = [a for a in argv if '@' in a][0].split('@')[1]
        calls.append(host)
        return rc_by_host.get(host, 0), 'out-from-' + host
    return fake


def _two_hosts(monkeypatch, tmp_path, rc_by_host):
    calls = []
    monkeypatch.setattr(remote, 'HOSTS', ['10.0.0.1', '10.0.0.2'])
    monkeypatch.setattr(remote, 'LAST_GOOD', str(tmp_path / 'last.txt'))
    monkeypatch.setattr(remote, 'run', _fake_run(calls, rc_by_host))
    ok, out = remote.call('随便一条命令')
    return calls, ok, out


def test_连不上才换下一个地址(monkeypatch, tmp_path):
    """255 是 ssh 自己的错，命令**肯定没跑**，换个地址是安全的。"""
    calls, ok, _ = _two_hosts(monkeypatch, tmp_path,
                              {'10.0.0.1': 255, '10.0.0.2': 0})
    assert calls == ['10.0.0.1', '10.0.0.2']
    assert ok


def test_远端命令失败绝不换地址重跑(monkeypatch, tmp_path):
    """**这条关系到钱。** 命令跑了、只是它自己失败了 —— 换个地址重跑
    等于让它跑第二遍。幂等的作业只是白跑，调付费 API 的作业**付两次钱**。
    """
    calls, ok, _ = _two_hosts(monkeypatch, tmp_path,
                              {'10.0.0.1': 3, '10.0.0.2': 0})
    assert calls == ['10.0.0.1'], '命令跑过了，不许换地址再跑一遍'
    assert not ok


def test_超时更不许换地址重跑(monkeypatch, tmp_path):
    """超时是**最危险**的一种：命令很可能已经跑了，甚至跑完了。

    2026-09-05 实测撞到过：一批下载跑了 4 分多钟被判超时，
    工具换地址重跑，前 3 篇被下了两遍。
    """
    calls, ok, out = _two_hosts(monkeypatch, tmp_path,
                                {'10.0.0.1': remote.TIMED_OUT, '10.0.0.2': 0})
    assert calls == ['10.0.0.1'], '超时之后换地址重跑 = 二次执行'
    assert not ok
    assert '还在对面继续跑' in out, '超时要提醒人「它可能还在跑」'


def test_本机没有ssh就别再试别的地址(monkeypatch, tmp_path):
    """换地址也没用 —— 缺的是本机的 ssh。"""
    calls, ok, _ = _two_hosts(monkeypatch, tmp_path,
                              {'10.0.0.1': remote.NO_SSH, '10.0.0.2': 0})
    assert calls == ['10.0.0.1']
    assert not ok


# ───────── 传文件的退路 ─────────

def test_太大的文件不硬塞进命令行(tmp_path, monkeypatch):
    """base64 要塞进命令行，命令行有长度上限 —— 超了要**明说**，不能默默截断。

    默默截断的后果是对面拿到一个坏文件，而两边都显示「成功」。
    """
    f = tmp_path / 'big.bin'
    f.write_bytes(b'x' * 900_000)      # base64 后 120 万，超过上限
    called = []
    monkeypatch.setattr(remote, 'call', lambda *a, **k: called.append(a) or (True, ''))
    ok, msg = remote._push_via_ssh(str(f), 'C:/tmp/big.bin')
    assert not ok
    assert not called, '超限了就不该真发出去'
    assert 'scp' in msg, '要告诉人换哪条路'


def test_ssh直传会把路径转成反斜杠(tmp_path, monkeypatch):
    """对面是 Windows PowerShell，正斜杠在有些位置会被吃掉。"""
    f = tmp_path / 'a.txt'
    f.write_bytes(b'hi')
    seen = {}

    def fake_call(script, timeout=None):
        seen['script'] = script
        return True, 'ok'

    monkeypatch.setattr(remote, 'call', fake_call)
    ok, _ = remote._push_via_ssh(str(f), 'C:/Windows/Temp/a.txt')
    assert ok
    # ⚠ 必须用原始字符串：`'C:\\Windows\\Temp\\a.txt'` 里的 `\\a` 是**响铃字符**，
    # 那个字面量根本不是一条路径。Windows 路径写进 Python 一律加 r 前缀。
    assert r'C:\Windows\Temp\a.txt' in seen['script']
    assert 'FromBase64String' in seen['script']


# ───────── 几条防手滑 ─────────

def test_只许触发配置里列出的计划任务(capsys, monkeypatch):
    """防手滑，不是防坏人：随手打错一个任务名不该真去启动点什么。"""
    monkeypatch.setitem(remote.M, 'tasks', ['MyWatcher'])
    assert remote.cmd_task('DefragmentDisks') == 2
    assert '不认识的任务' in capsys.readouterr().out


def test_没配上线脚本就不假装能部署(capsys, monkeypatch):
    monkeypatch.setitem(remote.M, 'deploy_cmd', '')
    assert remote.cmd_deploy() == 2
    assert 'deploy_cmd' in capsys.readouterr().out


def test_唤醒包格式对():
    """魔术包 = 6 个 0xFF + MAC 重复 16 次。格式错了不会报错，只是**不生效**。"""
    mac = 'AA-BB-CC-DD-EE-FF'
    packet = b'\xff' * 6 + bytes.fromhex(mac.replace('-', '')) * 16
    assert len(packet) == 102, '标准长度就是 102 字节'
    assert packet[:6] == b'\xff' * 6
    assert packet[6:12] == b'\xaa\xbb\xcc\xdd\xee\xff'


def test_不知道MAC时不假装发了(monkeypatch, tmp_path, capsys):
    """拿不到 MAC 就直说，别打印「已发送」——那会让人以为是对面的问题。"""
    monkeypatch.setattr(remote, 'MAC_FILE', str(tmp_path / 'nope.txt'))
    monkeypatch.setitem(remote.M, 'mac', '')
    monkeypatch.setattr('sys.argv', ['remote.py', 'wake'])
    assert remote.cmd_wake() == 2
    out = capsys.readouterr().out
    assert '不知道对面的 MAC' in out and '已向' not in out


def test_日志位置可以有多条(monkeypatch):
    """写死一个的话，连上去只看到「文件不存在」—— 那看起来像「服务没在写日志」。"""
    monkeypatch.setitem(remote.M, 'logs', ['data/logs/{name}.log', 'logs/{name}.log'])
    monkeypatch.setattr(remote, 'ROOT_R', 'D:/x')
    assert remote.log_paths('w') == ['D:/x/data/logs/w.log', 'D:/x/logs/w.log']


def test_作业外壳脚本写死了UTF8与退出码():
    """外壳只有一份定义（由代码生成），两份迟早不一致 ——
    而不一致的那天，症状看起来像「任务没触发」。
    """
    src = remote.wrapper_source()
    assert 'OutputEncoding' in src and 'UTF8' in src
    assert remote.JOB_DONE in src and remote.JOB_OUT in src


def test_临时脚本带BOM(tmp_path):
    """⚠ Windows PowerShell 5.1 读 .ps1 **文件**时没有 BOM 就按 GBK 解，
    脚本里的中文在**执行之前**就已经烂了。顶上那层 UTF-8 外壳管不到这一步。
    """
    tmp = remote._write_temp('Write-Output "中文"\n')
    try:
        raw = io.open(tmp, 'rb').read()
        assert raw[:3] == b'\xef\xbb\xbf', '少了 BOM，中文会在执行前就烂掉'
    finally:
        os.remove(tmp)

def test_选项的值不会被当成位置参数(monkeypatch):
    """`logs watcher --timeout 60` 里的 60 是 --timeout 的值，不是第三个位置参数。

    这种错**不报错，只是安静地做错事** —— 最难发现的一类。
    约定：位置参数一律写在选项前面，遇到第一个 `-` 就停。
    """
    monkeypatch.setattr('sys.argv', ['remote.py', 'logs', 'watcher',
                                     '--timeout', '60'])
    assert remote.positionals() == ['logs', 'watcher']
    assert remote.opt('--timeout') == '60'
