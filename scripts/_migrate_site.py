# -*- coding: utf-8 -*-
"""一次性迁移脚本：把硬编码的 Zotero 用户ID / storage 路径改为读配置。

做法：在**首次使用之前**插入 bootstrap（踩坑 #24 的教训：批量替换把 import
插到了使用之后，导致运行时 NameError），然后替换字面量。
跑完请务必执行 health_check（含语法 + 运行时导入检查）。
"""
import os, re, glob, io, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

UID_LIT = '16078117'
STORAGE_LIT = r'D:\03_Software\Zetero\Zotero\storage'

BOOT = [
    "# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env",
    "import os as _os, sys as _sys",
    "_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))",
    "try:",
    "    from modules.config import get_site as _site",
    "except Exception:",
    "    _site = lambda n: _os.environ.get(n, '')",
    "_UID = _site('ZOTERO_USER_ID') or '%s'" % UID_LIT,
    "_STORAGE = _site('ZOTERO_STORAGE') or r'%s'" % STORAGE_LIT,
]


def migrate(path):
    src = io.open(path, encoding='utf-8').read()
    if UID_LIT not in src and STORAGE_LIT not in src:
        return None
    if '_UID = _site(' in src:
        return 'skip(已迁移)'

    lines = src.split('\n')
    # 找第一处使用（用于决定 bootstrap 插入位置 —— 必须在它之前）
    first = next((i for i, l in enumerate(lines)
                  if (UID_LIT in l or STORAGE_LIT in l) and not l.strip().startswith('#')), None)
    if first is None:
        return 'skip(仅注释中出现)'
    indent = re.match(r'\s*', lines[first]).group(0)
    boot = [indent + b for b in BOOT]
    lines = lines[:first] + boot + lines[first:]

    out = []
    for l in lines:
        if l.strip().startswith('_UID = _site(') or l.strip().startswith('_STORAGE = _site('):
            out.append(l); continue          # bootstrap 自身不参与替换
        if UID_LIT in l or STORAGE_LIT in l:
            # 字符串里内嵌的 URL → 转 f-string，用 {_UID} 占位（避免引号嵌套问题）
            if re.search(r'/users/' + UID_LIT, l):
                l = l.replace('/users/' + UID_LIT, '/users/{_UID}')
                l = re.sub(r"(?<![frbFRB])(['\"])(?=[^'\"]*\{_UID\})", r"f\1", l, count=1)
            l = l.replace("'" + UID_LIT + "'", '_UID').replace('"' + UID_LIT + '"', '_UID')
            l = l.replace("r'" + STORAGE_LIT + "'", '_STORAGE')
            l = l.replace('r"' + STORAGE_LIT + '"', '_STORAGE')
        out.append(l)

    new = '\n'.join(out)
    io.open(path, 'w', encoding='utf-8', newline='').write(new)
    return 'migrated'


def main():
    targets = sorted(set(glob.glob('scripts/*.py') + glob.glob('modules/*/*.py')))
    report = []
    for f in targets:
        if os.path.basename(f).startswith('_migrate'):
            continue
        try:
            r = migrate(f)
        except Exception as e:
            r = f'ERROR {e}'
        if r:
            report.append(f'  {os.path.basename(f):32s} {r}')
    io.open('workflow_data/logs/_migrate.txt', 'w', encoding='utf-8').write(
        f'处理 {len(report)} 个文件\n' + '\n'.join(report))


if __name__ == '__main__':
    main()
