# -*- coding: utf-8 -*-
"""发布前体检 —— 把一个仓库**推到公网之前**该看的东西，一次看完。

    python preflight.py <仓库目录>            # 例：python preflight.py D:/dev/getpdf
    python preflight.py <仓库目录> --tests    # 顺带把它的测试也跑一遍

## 为什么要有它

拆 `remote-machine` 那次，"扫一遍有没有真实 IP、账号、密钥"是**临场想起来**才做的。
临场想起来的事，第二次就会忘 —— 而这件事忘一次的代价是**永久的**：
推上公网的东西，删掉了也已经被抓过、被缓存过。

所以规矩改成：**发布前跑一次这个脚本，红的一条都不许剩。**

## 它查什么（分两档，别混）

**阻断（红）** —— 有一条就别推：
  · 疑似密钥/令牌（`sk-`、`ghp_`、AWS、私钥文件内容）
  · 公网 IP（内网地址只是提醒，公网地址等于把你家门牌号贴出去）
  · 你自己的用户目录路径（`C:\\Users\\某某`）—— 会暴露真名
  · 模板占位符没填（两层大括号包起来的那种，或尖括号里写着「请填入」的那种）
  · LICENSE 缺失或没填名字

**提醒（黄）** —— 看一眼，确认是故意的就行：
  · 内网 IP、邮箱地址
  · README 缺「怎么装」或「怎么用」
  · 没有 tests 目录
  · `.gitignore` 没挡住配置文件

**只看进了版本库的文件**（`git ls-files`）—— 没被 git 跟踪的东西根本不会被推上去，
把它们也算进来只会制造一堆假警报，而**假警报多了，真警报就没人看了**。

## 怎么让它闭嘴（两种，都要**留痕**）

有些"违规"是故意的：模板目录里就该有占位符，测试里就该种几个假密钥。
但**闭嘴的方式必须留下痕迹**，否则下次真有问题时你也看不见。

1. **整块目录**：仓库根放一个 `.preflight.toml`

       skip = ["template/**", "docs/samples/**"]

2. **单独一行**：在那一行末尾写上 `preflight-ok`

       KEY = "sk-这是测试用的假货"   # preflight-ok 故意种的

这两种都是本工具自己在用的 —— 它的模板目录满是占位符，
测试里种着假密钥和假 IP，全靠这两条才没把自己拦下来。
"""
import io
import os
import re
import subprocess

# Windows 上 subprocess 默认会弹控制台窗口。toolforge 要能脱离任何项目
# 独立运行，所以不 import 别处的封装，自己带一份。
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

_NL = chr(10)

# ── 判据表 ────────────────────────────────────────────────────────────

# 密钥长什么样。写成前缀而不是「长得像随机串」——
# 后者会把哈希、UUID、base64 图片全抓进来，假警报淹掉真警报。
SECRET_PAT = [
    (r'sk-[A-Za-z0-9]{16,}', 'OpenAI/DeepSeek 那一类的 API key'),
    (r'ghp_[A-Za-z0-9]{20,}', 'GitHub 个人访问令牌'),
    (r'github_pat_[A-Za-z0-9_]{20,}', 'GitHub 细粒度令牌'),
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key'),
    (r'-----BEGIN [A-Z ]*PRIVATE KEY-----', '私钥文件的内容'),
    (r'xox[baprs]-[A-Za-z0-9-]{10,}', 'Slack 令牌'),
    (r'AIza[0-9A-Za-z_\-]{30,}', 'Google API key'),
]

# 文档里可以放心写的地址（RFC 5737 专门留给举例用的三段，加上本机）
DOC_SAFE_IP = ('192.0.2.', '198.51.100.', '203.0.113.', '127.0.0.1', '0.0.0.0',
               '255.255.255.255', '8.8.8.8', '1.1.1.1')
PRIVATE_IP = re.compile(r'^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)')
IPV4 = re.compile(r'(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])')

PLACEHOLDER = [r'\{\{[A-Z_]+\}\}', r'<请填入[^>]*>', r'TODO：填', r'FIXME']  # preflight-ok 这是判据表本身

# 「版本 1.0.90.0」这种，前面这些词一出现就八成不是地址
VERSIONISH = re.compile(r'版本|版|version|Version|VERSION|ver\.|build|Build|[ 	(=]v')

# 二进制与生成物不必看
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.pyc',
            '.woff', '.woff2', '.ttf', '.mp4', '.xlsx', '.docx'}


class Report:
    def __init__(self):
        self.bad, self.warn = [], []

    def block(self, where, what):
        self.bad.append((where, what))

    def note(self, where, what):
        self.warn.append((where, what))


def tracked_files(repo):
    """只看进了版本库的文件 —— 没被跟踪的推不上去。"""
    try:
        p = subprocess.run(['git', '-C', repo, 'ls-files'],
                           capture_output=True, timeout=60, creationflags=_NOWIN)
        if p.returncode == 0:
            names = p.stdout.decode('utf-8', 'replace').splitlines()
            return [n for n in names if n.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def load_skip(repo):
    """读 `.preflight.toml` 里的 skip 清单（没有就是空的）。

    为什么需要它：模板目录、示例数据这类地方**本来就该**长得像违规。
    没有豁免口的检查，人只会学会无视它 —— 那就等于没有检查。
    """
    path = os.path.join(repo, '.preflight.toml')
    try:
        import tomllib
        with io.open(path, 'rb') as fh:
            conf = tomllib.load(fh)
    except (OSError, ValueError):
        return []
    return [str(x) for x in (conf.get('skip') or [])]


def skipped(rel, patterns):
    import fnmatch
    rel = rel.replace(os.sep, '/')
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat.rstrip('/*') + '/*'):
            return True
    return False


def read(path):
    try:
        return io.open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


# 行末写上这个词，这一行就不查了。**必须留痕** —— 悄悄关掉检查等于没有检查。
MUTE = 'preflight-ok'


def scan_text(rel, text, rep):
    """逐行查。**按行而不是按整篇**，是为了让「这一行是故意的」能单独豁免。"""
    text = _NL.join(l for l in text.splitlines() if MUTE not in l)

    for pat, name in SECRET_PAT:
        if re.search(pat, text):
            rep.block(rel, f'疑似{name}')

    for m in IPV4.finditer(text):
        ip = m.group(1)
        if any(int(x) > 255 for x in ip.split('.')):
            continue                      # 一看就不是地址
        if ip.startswith(DOC_SAFE_IP):
            continue
        if PRIVATE_IP.match(ip):
            rep.note(rel, f'内网地址 {ip}（确认是示例就行）')
        elif VERSIONISH.search(text[max(0, m.start() - 16):m.start()]):
            # 四段式版本号（1.0.90.0）跟 IP 长得一模一样。硬判成地址会天天误报，
            # 而**误报多了真的那条就没人看了** —— 所以只提醒，把判断交回给人。
            rep.note(rel, f'{ip} 前面像是在说版本，确认它不是地址就行')
        else:
            rep.block(rel, f'公网地址 {ip} —— 等于把门牌号贴出去')

    for pat in PLACEHOLDER:
        if re.search(pat, text):
            rep.block(rel, f'模板占位符没填（{pat}）')

    # 你自己的用户目录会暴露真名
    for m in re.finditer(r'[Cc]:[\\/]+Users[\\/]+([A-Za-z0-9_.\- ]+)', text):
        who = m.group(1)
        if who.lower() not in ('public', 'default', '<你>', 'username', 'user'):
            rep.block(rel, f'写死了某个人的用户目录（C:\\Users\\{who}）')

    for m in re.finditer(r'[\w.\-]+@[\w\-]+\.[A-Za-z]{2,}', text):
        rep.note(rel, f'邮箱地址 {m.group(0)}')


def check_repo(repo, run_tests=False):
    rep = Report()
    files = tracked_files(repo)
    if files is None:
        rep.block('.', '这不是一个 git 仓库（或 git 跑不起来）——'
                       '没法判断哪些文件会被推上去')
        return rep

    skip = load_skip(repo)
    for rel in files:
        if os.path.splitext(rel)[1].lower() in SKIP_EXT or skipped(rel, skip):
            continue
        scan_text(rel, read(os.path.join(repo, rel)), rep)

    lower = [f.lower() for f in files]

    if 'license' not in lower:
        rep.block('.', '没有 LICENSE —— 公开仓库不写许可证，'
                       '法律上等于「保留所有权利」，别人不敢用')
    else:
        lic = read(os.path.join(repo, files[lower.index('license')]))
        if re.search(r'<[^>]*>|请填入', lic):
            rep.block('LICENSE', '许可证里还留着占位符（版权人没填）')

    if 'readme.md' not in lower:
        rep.block('.', '没有 README —— 陌生人打开只能看到一堆代码')
    else:
        rd = read(os.path.join(repo, files[lower.index('readme.md')]))
        if not re.search(r'装|安装|install|Install', rd):
            rep.note('README.md', '没写「怎么装」')
        if not re.search(r'用法|怎么用|使用|Usage|```', rd):
            rep.note('README.md', '没写「怎么用」，也没有一段示例')

    if not any(f.startswith('tests/') or '/tests/' in f for f in files):
        rep.note('.', '没有 tests/ —— 别人不敢改你的代码')

    gi = os.path.join(repo, '.gitignore')
    if os.path.isfile(gi):
        ign = read(gi)
        for risky in ('.env', 'config.toml', 'machines.toml', 'secrets'):
            if risky in ign:
                break
        else:
            rep.note('.gitignore', '没看到挡配置/密钥文件的规则'
                                   '（这类文件一旦提交，改回来也留在历史里）')
    else:
        rep.note('.', '没有 .gitignore')

    if run_tests:
        p = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=repo,
                           capture_output=True, timeout=900, creationflags=_NOWIN)
        out = (p.stdout or b'').decode('utf-8', 'replace').strip().splitlines()
        tail = out[-1] if out else '（没有输出）'
        if p.returncode != 0:
            rep.block('tests', f'测试没过：{tail}')
        else:
            print(f'测试：{tail}')

    return rep


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    if not args:
        print(__doc__)
        return 0
    repo = os.path.abspath(args[0])
    if not os.path.isdir(repo):
        print(f'找不到这个目录：{repo}')
        return 2

    print(f'体检：{repo}{_NL}')
    rep = check_repo(repo, run_tests='--tests' in sys.argv[1:])

    for where, what in rep.bad:
        print(f'  [阻断] {where}: {what}')
    for where, what in rep.warn:
        print(f'  [提醒] {where}: {what}')

    print()
    if rep.bad:
        print(f'✗ {len(rep.bad)} 条阻断、{len(rep.warn)} 条提醒 —— **先别推**。')
        return 1
    print(f'✓ 没有阻断项（{len(rep.warn)} 条提醒，自己看一眼是不是故意的）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
