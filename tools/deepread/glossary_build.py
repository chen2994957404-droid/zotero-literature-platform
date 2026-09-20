# -*- coding: utf-8 -*-
"""从范文重建领域术语表：curated/<id>/reference.md（高分子学人推送，人写的）→ serving/glossary.json。

用法：python -m tools.deepread --建术语表
零成本、只读范文、可反复跑。挖与洗的规则在 `shared.domain.glossary`，这里只管找文件、落盘、报数。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass
import io
import json
import time

from shared.domain import glossary as _gl
from shared.kernel import catalog, paths


def build(log=print):
    """→ (表, 范文篇数)。表已写到 paths.glossary()。"""
    texts, n = [], 0
    for pid in catalog.ids():
        p = paths.reference(pid)
        if os.path.exists(p):
            texts.append(io.open(p, encoding='utf-8', errors='replace').read())
            n += 1
    counts = _gl.mine(texts)
    table = _gl.build(counts)
    out = paths.glossary()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, 'w', encoding='utf-8').write(json.dumps(
        {'_built': time.strftime('%Y-%m-%d %H:%M'), '_from': '%d 篇范文' % n, **table}, ensure_ascii=False, indent=1))
    log('范文 %d 篇 → 挖到 %d 个英文词、%d 对；洗后留 %d 个词（≥2 票）→ %s'
        % (n, len(counts), sum(sum(c.values()) for c in counts.values()), len(table), out))
    amb = [(t, e['zh']) for t, e in table.items() if len(e['zh']) > 1]
    log('其中有歧义（多个译名）的 %d 个，例如：%s' % (len(amb), '；'.join('%s=%s' % (t, '/'.join(z)) for t, z in amb[:6])))
    return table, n


def main():
    build()
    return 0


if __name__ == '__main__':
    sys.exit(main())
