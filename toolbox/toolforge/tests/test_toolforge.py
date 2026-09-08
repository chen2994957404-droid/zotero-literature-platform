# -*- coding: utf-8 -*-
"""工厂自己的测试 —— 生出来的骨架能不能跑、体检能不能抓到该抓的。

**为什么体检那几条最值得测**：一个漏报的体检比没有体检更危险 ——
它会让人以为已经查过了。所以这里专门种几个"该被抓住"的东西进去。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import new_project  # noqa: E402
import preflight  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gen(tmp_path, name='demo-tool'):
    """用真正的入口跑一次生成（不是调内部函数）—— 命令行坏了也要能发现。"""
    r = subprocess.run([sys.executable, os.path.join(HERE, 'new_project.py'),
                        name, '--desc', '演示用', '--dir', str(tmp_path)],
                       capture_output=True, timeout=120)
    assert r.returncode == 0, r.stdout.decode('utf-8', 'replace')
    return tmp_path / name


# ───────── 骨架 ─────────

def test_生成的骨架该有的都有(tmp_path):
    d = gen(tmp_path)
    for f in ('README.md', 'LICENSE', '.gitignore', 'install.py',
              'config.example.toml', 'demo_tool.py',
              'skill/SKILL.md', 'tests/test_smoke.py'):
        assert (d / f).exists(), f'骨架少了 {f}'


def test_带横杠的名字要换成能import的文件名(tmp_path):
    """`demo-tool.py` 这种文件名 **import 不进来**，测试第一行就会崩。"""
    d = gen(tmp_path)
    assert (d / 'demo_tool.py').exists() and not (d / 'demo-tool.py').exists()


def test_生成的骨架自己的测试能过(tmp_path):
    """陌生人 clone 下来第一件事就是跑测试。红的话他直接就走了。"""
    d = gen(tmp_path)
    r = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=str(d),
                       capture_output=True, timeout=300)
    assert r.returncode == 0, r.stdout.decode('utf-8', 'replace')[-1500:]


def test_骨架里不许留占位符(tmp_path):
    """占位符没换干净 = 生成的项目自己就过不了体检。"""
    d = gen(tmp_path)
    for cur, _dirs, files in os.walk(d):
        for f in files:
            text = open(os.path.join(cur, f), encoding='utf-8').read()
            assert '{{' not in text, f'{f} 里还留着占位符'


def test_不覆盖已经存在的目录(tmp_path):
    """骨架盖掉真代码是那种「一秒钟毁掉一下午」的事故。"""
    gen(tmp_path)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'new_project.py'),
                        'demo-tool', '--dir', str(tmp_path)],
                       capture_output=True, timeout=60)
    assert r.returncode == 2
    assert '已经存在' in r.stdout.decode('utf-8', 'replace')


# ───────── 体检 ─────────

def test_抓得到密钥和公网地址():
    rep = preflight.Report()
    preflight.scan_text('x.py', 'KEY = "sk-abcdefghijklmnopqrst1234"', rep)  # preflight-ok 故意种的假货
    assert any('API key' in w for _, w in rep.bad)

    rep = preflight.Report()
    preflight.scan_text('x.md', '连 8.8.4.4 试试', rep)  # preflight-ok 故意种的假货
    assert any('公网地址' in w for _, w in rep.bad)


def test_抓得到写死的用户目录():
    """会暴露真名 —— 而且是那种自己完全看不见的暴露。"""
    rep = preflight.Report()
    preflight.scan_text('a.py', r'p = "C:\\Users\\zhangsan\\.ssh\\id_ed25519"', rep)  # preflight-ok 故意种的假货
    assert any('用户目录' in w for _, w in rep.bad)


def test_内网地址只提醒不阻断():
    """测试里写 10.0.0.1 是正常的。全都阻断的话，人很快就学会无视它。"""
    rep = preflight.Report()
    preflight.scan_text('t.py', "HOSTS = ['10.0.0.1', '192.168.1.5']", rep)  # preflight-ok 故意种的假货
    assert not rep.bad and len(rep.warn) == 2


def test_文档专用地址一个都不报():
    """RFC 5737 那三段就是留着写文档的，报它们纯属噪音。"""
    rep = preflight.Report()
    preflight.scan_text('README.md', '例：203.0.113.10 与 192.0.2.1', rep)  # preflight-ok 故意种的假货
    assert not rep.bad and not rep.warn


def test_版本号不当成IP():
    rep = preflight.Report()
    preflight.scan_text('a.md', '扩展版本 1.0.90.0，另一个 300.1.2.3', rep)  # preflight-ok 故意种的假货
    assert not rep.bad


def test_占位符没填要拦下():
    rep = preflight.Report()
    preflight.scan_text('README.md', '作者：<请填入你的名字>', rep)  # preflight-ok 故意种的假货
    assert any('占位符' in w for _, w in rep.bad)


def test_刚生成的骨架体检结果是可预期的(tmp_path):
    """骨架里**还留着模板注释**，所以体检必然报一些提醒 —— 这是对的：
    它在催你把 README 填完。要保证的是**不出现阻断项**。
    """
    d = gen(tmp_path)
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=str(d), timeout=60)
    subprocess.run(['git', 'add', '-A'], cwd=str(d), timeout=60)
    rep = preflight.check_repo(str(d))
    assert not rep.bad, rep.bad

# ───────── 豁免口：没有豁免口的检查，人只会学会无视它 ─────────

def test_行内标记能让这一行不被查():
    """故意种的假密钥要能豁免 —— 但**必须留痕**（标记就写在那一行上）。"""
    rep = preflight.Report()
    preflight.scan_text('t.py', 'k = "sk-abcdefghijklmnopqrst1234"  # preflight-ok',
                        rep)
    assert not rep.bad


def test_没有标记的那一行照样拦():
    """豁免只对写了标记的那一行生效。"""
    rep = preflight.Report()
    preflight.scan_text('t.py',
                        'a = "sk-aaaaaaaaaaaaaaaaaaaa1234"  # preflight-ok'
                        + chr(10) + 'b = "sk-zzzzzzzzzzzzzzzzzzzz9999"', rep)  # preflight-ok 这是判据表本身
    assert len(rep.bad) == 1


def test_skip清单能豁免整块目录():
    """模板目录里就该有占位符 —— 不给豁免口，这个工具连自己都过不了。"""
    pats = ['template/**', 'docs/samples/**']
    assert preflight.skipped('template/README.md', pats)
    assert preflight.skipped('template/skill/SKILL.md', pats)
    assert not preflight.skipped('tests/test_x.py', pats)


def test_本仓库自己的skip清单读得出来():
    """这份清单是留痕用的：豁免了什么，一眼看得见。"""
    assert 'template/**' in preflight.load_skip(HERE)
