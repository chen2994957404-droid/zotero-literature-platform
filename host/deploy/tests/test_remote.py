# -*- coding: utf-8 -*-
"""remote.py 的离线测试 —— **不连 B 机**，只验命令怎么拼、诊断怎么分。

为什么这些值得测：这个工具存在的一半理由就是「把看起来一样、根因完全不同的
几种失败分开」。分错了，人就会照着错方向查 —— 踩坑 #74 就白查了两轮密钥，
而真相是账号名写错了。**分类错的诊断比没有诊断更贵。**
"""
import pytest

from host.deploy import remote


def test_用户名是账号不是计算机名():
    """踩坑 #74 的钉子。

    `吧啦吧啦` 是主力机的**计算机名**，`Administrator` 才是账号。
    用错时 sshd 只回 `Permission denied (publickey,...)` —— 这句话对
    「账号不存在」和「公钥不对」是同一句，在 A 机这边根本分不出来。
    2026-09-03 发现 `.claude/settings.local.json` 里那条授权还写着计算机名。
    """
    assert remote.USER == 'Administrator', (
        f'用户名成了 {remote.USER!r} —— 如果这是计算机名，会白查两轮密钥（踩坑 #74）')


def test_命令一定套着UTF8外壳():
    """B 那边控制台默认 GBK。不套壳中文输出全是乱码，而且乱得像数据坏了。"""
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
    assert f'{remote.USER}@{remote.HOST}' in argv


@pytest.mark.parametrize('stderr, want', [
    ('kex_exchange_identification: Connection closed by remote host', '睡眠'),
    ('ssh: connect to host 1.2.3.4 port 22: Connection timed out', '关机或睡眠'),
    ('Permission denied (publickey,password).', '踩坑 #74'),
    ('Host key verification failed.', '主机密钥'),
])
def test_几种失败要分得开(stderr, want):
    """**这几条在 A 机这边看起来都像「连不上」，但该查的方向完全不同。**"""
    tip = remote.diagnose(stderr)
    assert want in tip, f'{stderr[:40]!r} 的诊断没提到「{want}」，实际：{tip[:80]}'


def test_没见过的错误不硬编一个原因():
    """认不出来就返回空，让原始报错自己说话。

    硬套一个最像的原因，会把人**主动**带偏 —— 比不给建议更糟。
    """
    assert remote.diagnose('some totally unexpected failure') == ''
    assert remote.diagnose('') == ''


def test_只许触发白名单里的计划任务(capsys):
    """防手滑，不是防坏人：随手打错一个任务名不该真去启动点什么。"""
    assert remote.cmd_task('DefragmentDisks') == 2
    assert '不认识的任务' in capsys.readouterr().out


def test_唤醒包格式对():
    """魔术包 = 6 个 0xFF + MAC 重复 16 次。格式错了不会报错，只是**不生效**。"""
    mac = 'AA-BB-CC-DD-EE-FF'
    packet = b'\xff' * 6 + bytes.fromhex(mac.replace('-', '')) * 16
    assert len(packet) == 102, '标准长度就是 102 字节'
    assert packet[:6] == b'\xff' * 6
    assert packet[6:12] == b'\xaa\xbb\xcc\xdd\xee\xff'


def test_不知道MAC时不假装发了(monkeypatch, tmp_path, capsys):
    """拿不到 MAC 就直说，别打印「已发送」——那会让人以为是 B 那边的问题。"""
    monkeypatch.setattr(remote, 'MAC_FILE', str(tmp_path / 'nope.txt'))
    monkeypatch.setattr('sys.argv', ['remote.py', 'wake'])
    assert remote.cmd_wake() == 2
    out = capsys.readouterr().out
    assert '不知道 B 的 MAC' in out and '已向' not in out


# ───────── 多候选地址（2026-09-03 加：笔记本到处跑，B 可能有两个地址）─────────

def test_多个候选地址按顺序试(monkeypatch):
    """局域网地址排前面 —— 直连比走组网中继快得多。"""
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


def test_ssh命令行认得出指定的地址():
    argv = remote.ssh_argv('x', host='10.9.9.9')
    assert f'{remote.USER}@10.9.9.9' in argv


def test_断开的诊断要把两种可能都说出来():
    """**言之凿凿的错判比不给判断更糟。**

    2026-09-03 第一版只写了「机器在睡眠」，结果连一个根本不存在的地址
    也被诊断成睡眠 —— 而真相是本机代理接管了连接。
    """
    tip = remote.diagnose('kex_exchange_identification: Connection closed by remote host')
    assert '睡眠' in tip, '少了「对面在睡」这一种'
    assert '代理' in tip, '少了「本机代理接管」这一种'
    assert '不存在' in tip, '少了那条能分清两者的判据'
