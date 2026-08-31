# -*- coding: utf-8 -*-
"""生成 `.claude/` —— agent 的运行时配置，**全部生成，手写即违规**。

用法: python host/codegen/skills.py          生成
      python host/codegen/skills.py --check  只检查是否与源同步（不写盘）

## 为什么必须生成

`.claude/skills/` 是模型每次会话都会看到的东西。手写它就意味着：
**同一件事在两处各写一遍**（工具里一份 `SKILL.md`，`.claude/` 里一份），
然后其中一份开始过时 —— 而过时的偏偏是模型真正读到的那份。

R7 窗之前正是这样：`.claude/skills/` 里四份手写 skill 提到 `core/`、
`平台管理/`、`workflow_data/`，那些目录在 R1~R6 已经全没了。

所以规矩改成：**源在别处，`.claude/` 只是产物。**

| 产物 | 源 |
|---|---|
| `.claude/skills/<工具名>/SKILL.md` | `tools/<t>/SKILL.md` + `tools/<t>/tool.toml` |
| `.claude/skills/<平台名>/SKILL.md` | `docs/howto/skills/<名>.md` |
| `.claude/rules/<名>.md`            | `docs/howto/rules/<名>.md` |

工具那一族**不是复制**：frontmatter 由 `tool.toml` 生成，
再加一段「花不花钱 / 有什么副作用 / 需要哪档机器角色」的自动摘要 ——
这三件事只有清单知道，而它们恰恰是模型最该在动手前看到的。
"""
import io
import os
import re
import sys
import tomllib

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import flag

ROOT = paths.ROOT
TOOLS_DIR = os.path.join(ROOT, 'tools')
SKILL_SRC = os.path.join(ROOT, 'docs', 'howto', 'skills')
RULE_SRC = os.path.join(ROOT, 'docs', 'howto', 'rules')
OUT_SKILLS = os.path.join(ROOT, '.claude', 'skills')
OUT_RULES = os.path.join(ROOT, '.claude', 'rules')

BANNER = ('<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。'
          '改源：{src} -->')

_FM = re.compile(r'\A---\r?\n(.*?)\r?\n---\r?\n', re.S)


def _split_front_matter(text):
    """→ (frontmatter 文本 or None, 正文)。"""
    m = _FM.match(text)
    return (m.group(1), text[m.end():]) if m else (None, text)


def _first_bullets(body, n=3, limit=220):
    """从「什么时候用我」那一段抓前几条要点，拼进 description。

    description 是模型**决定读不读**这份 skill 的唯一依据。
    只写一句「XX 工具」不足以让它在正确的时候想起来 ——
    真正管用的是那几条具体场景（「用户问我库里有没有 XX」）。
    """
    lines, grabbing, out = body.splitlines(), False, []
    for ln in lines:
        s = ln.strip()
        if s.startswith('#'):
            if grabbing:
                break
            grabbing = '什么时候用我' in s
            continue
        if grabbing and s.startswith(('-', '*')):
            out.append(re.sub(r'[`*]', '', s.lstrip('-* ')).strip())
            if len(out) >= n:
                break
    txt = '；'.join(out)
    return txt[:limit]


def tool_skill(name, d):
    """一个工具 → 它那份 `.claude/skills/<name>/SKILL.md` 的全文。"""
    with open(os.path.join(d, 'tool.toml'), 'rb') as f:
        man = tomllib.load(f)
    body = io.open(os.path.join(d, 'SKILL.md'), encoding='utf-8').read()
    _, body = _split_front_matter(body)          # 源里若有 frontmatter，以清单为准

    when = _first_bullets(body)
    desc = f"{man.get('one_line', '')}。" + (f'什么时候用：{when}' if when else '')

    money = '**会花钱**' if man.get('costs_money') else '不花钱'
    fx = man.get('side_effects') or []
    fx_txt = ('**有副作用**：' + '、'.join(fx)) if fx else '无副作用（只读）'
    role = {'none': '任何机器都能跑', 'test': '需要测试端或运行端',
            'prod': '**只能在运行端（主力机）跑**'}.get(man.get('requires_role'), '未声明')
    expose = {'tool': '`tool`（模型可以自己调）',
              'resource': '`resource`（只读数据）',
              'prompt': '`prompt`（**由人在客户端点，模型不能自己发起**）',
              'internal': '`internal`（不对外暴露）'}.get(man.get('expose'), man.get('expose'))

    head = [
        '---',
        f'name: {name}',
        f'description: {desc}',
        '---',
        '',
        BANNER.format(src=f'tools/{name}/SKILL.md + tools/{name}/tool.toml'),
        '',
        f'> **动手之前先看这三行**（取自 `tools/{name}/tool.toml`）：',
        f'> {money} · {fx_txt} · {role}',
        f'> MCP 暴露方式：{expose}',
        f'> 命令行：`python -m tools.{name}`',
        '',
        '',
    ]
    return '\n'.join(head) + body.lstrip('\n')


def platform_skill(path):
    """`docs/howto/skills/<名>.md` → 同名 skill 全文（frontmatter 原样透传）。"""
    text = io.open(path, encoding='utf-8').read()
    fm, body = _split_front_matter(text)
    rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
    if fm is None:
        raise SystemExit(f'{rel} 缺 frontmatter（至少要有 name 与 description）')
    return '---\n' + fm + '\n---\n\n' + BANNER.format(src=rel) + '\n\n' + body.lstrip('\n')


def rule(path):
    """`docs/howto/rules/<名>.md` → `.claude/rules/<名>.md`。

    规则文件的 frontmatter 里要有 `paths:` —— 那是它的全部意义：
    只有在改到那些文件时才注入，不占平时的上下文。
    """
    text = io.open(path, encoding='utf-8').read()
    fm, body = _split_front_matter(text)
    rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
    if fm is None or 'paths:' not in fm:
        raise SystemExit(f'{rel} 的 frontmatter 里必须有 paths:（否则这条规则永远不会被触发）')
    return '---\n' + fm + '\n---\n\n' + BANNER.format(src=rel) + '\n\n' + body.lstrip('\n')


def plan():
    """要生成哪些文件 → [(输出的绝对路径, 内容)]。"""
    out = []
    for name in sorted(os.listdir(TOOLS_DIR)):
        d = os.path.join(TOOLS_DIR, name)
        if not (os.path.isfile(os.path.join(d, 'tool.toml'))
                and os.path.isfile(os.path.join(d, 'SKILL.md'))):
            continue
        out.append((os.path.join(OUT_SKILLS, name, 'SKILL.md'), tool_skill(name, d)))
    if os.path.isdir(SKILL_SRC):
        for f in sorted(os.listdir(SKILL_SRC)):
            if f.endswith('.md'):
                out.append((os.path.join(OUT_SKILLS, f[:-3], 'SKILL.md'),
                            platform_skill(os.path.join(SKILL_SRC, f))))
    if os.path.isdir(RULE_SRC):
        for f in sorted(os.listdir(RULE_SRC)):
            if f.endswith('.md'):
                out.append((os.path.join(OUT_RULES, f), rule(os.path.join(RULE_SRC, f))))
    return out


def _read(p):
    try:
        return io.open(p, encoding='utf-8').read()
    except OSError:
        return None


def _existing():
    """`.claude/` 里现在有哪些产物（用来发现「源没了但产物还在」）。"""
    have = set()
    for base, pat in ((OUT_SKILLS, 'SKILL.md'), (OUT_RULES, None)):
        if not os.path.isdir(base):
            continue
        for dp, _dn, fn in os.walk(base):
            for f in fn:
                if pat is None or f == pat:
                    have.add(os.path.join(dp, f))
    return have


def main():
    check = flag('--check')
    want = plan()
    stale = _existing() - {p for p, _ in want}
    diff = [p for p, body in want if _read(p) != body]

    if check:
        bad = ([f'过时：{os.path.relpath(p, ROOT)}' for p in sorted(diff)]
               + [f'源已删除但产物还在：{os.path.relpath(p, ROOT)}' for p in sorted(stale)])
        if bad:
            print('.claude/ 与源不同步：\n  ' + '\n  '.join(bad))
            print('\n跑一次 python host/codegen/skills.py 重新生成。')
            sys.exit(1)
        print(f'.claude/ 与源同步（{len(want)} 个文件）')
        return

    for p, body in want:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, 'w', encoding='utf-8', newline='').write(body)
    for p in stale:
        os.remove(p)
        d = os.path.dirname(p)
        if not os.listdir(d):
            os.rmdir(d)
    n_tool = sum(1 for p, _ in want if os.sep + 'skills' + os.sep in p)
    print(f'已生成 {len(want)} 个文件：{n_tool} 份 skill、'
          f'{len(want) - n_tool} 条 rule'
          + (f'；清掉 {len(stale)} 个没源的旧产物' if stale else ''))


if __name__ == '__main__':
    main()
