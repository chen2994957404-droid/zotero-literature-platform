# -*- coding: utf-8 -*-
"""图表数字化的命令行入口（只解析参数，逻辑在 tools/digitize）。

用法:
    python -m tools.digitize <图片路径>
    python -m tools.digitize <图片路径> --hint "只读红色那条曲线"
    python -m tools.digitize <图片路径> --provider ollama --model qwen2.5vl:7b
    python -m tools.digitize <图片路径> --out 数据.json

⚠ **必须用云端视觉大模型**。本地 7B 会编出看似合理的假数据 ——
   编的数字最像事实，也最难发现（宪法零号判据的反面教材）。
   `--provider ollama` 只用于验证接口通不通，别拿它的数字当真。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io
import json

from shared.kernel.cli import opt, pos, wants_help
from tools import digitize as dg


def main():
    if wants_help():
        print(__doc__)
        return 0
    path = pos(0)
    if not path:
        print(__doc__)
        return 2
    if not os.path.isfile(path):
        print(f'找不到图片：{path}')
        return 1

    r = dg.digitize_file(path, hint=opt('--hint', ''),
                         provider=opt('--provider'), model=opt('--model'))
    text = json.dumps(r, ensure_ascii=False, indent=2)
    out = opt('--out')
    if out:
        io.open(out, 'w', encoding='utf-8').write(text)
        print(f'已写入 {out}')
    else:
        print(text)
    return 1 if r.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
