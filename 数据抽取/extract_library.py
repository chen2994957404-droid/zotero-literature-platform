# -*- coding: utf-8 -*-
"""结构化抽取（粗层 / 广度抽取，全库）：照 vectorize_library.py 的路子，直接吃 Zotero
自带的 /fulltext 全文索引（不解析PDF、不占空间），用【本地 Ollama qwen2.5】把全库每篇
粗抽成结构化字段。零 API 成本、不限量，专供"广撒网找方向"。

与精层的关系（对称于 vectorize_library.py ↔ vectorize.py）：
  - 精层 extract_structured.py：吃 MineRU 高质量 full.md，用云端 DeepSeek-pro，最准，供重点文献
  - 粗层 extract_library.py（本文件）：吃 Zotero fulltext，用本地 qwen2.5，够筛，供全库
  - 已被精层抽过的 key，粗层自动跳过（精层优先，绝不覆盖高质量结果）

复用 extract_structured.py 的 SCHEMA / SYS / build_user_prompt / build_compare_table，
保证粗细两层字段一致、并入同一张 compare.md。

用法:
  python extract_library.py            # 增量（只抽没抽过的）
  python extract_library.py --rebuild  # 重抽全部粗层
"""
import os, sys, json, re, urllib.request, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths, role

from core.cli import flag
from core.config import get_key, get_site, need_site

# 同文件夹脚本互相 import（标准开头只把项目根加进 sys.path，兄弟脚本目录需自己加）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 复用同一份 schema 与提示词，保证粗细两层字段一致
from domain.schema import SCHEMA, SYS, build_user_prompt, hierarchical_body
from pipelines.extract import write_compare_table as build_compare_table

OUT_DIR = paths.STRUCTURED
os.makedirs(OUT_DIR, exist_ok=True)

# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
USER_ID = need_site('ZOTERO_USER_ID')
LOCAL = get_site('ZOTERO_API_HOST') + '/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
OLLAMA_CHAT = get_site('OLLAMA_HOST') + '/api/chat'
LOCAL_MODEL = get_key('OLLAMA_MODEL', default='qwen2.5:7b-instruct')   # 本地抽取模型；qwen3:8b 亦可
REBUILD = flag('--rebuild')

def lget(path):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(LOCAL + path, headers=LH), timeout=20).read())

def get_fulltext(att_key):
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            LOCAL + f'/items/{att_key}/fulltext', headers=LH), timeout=20).read()
        return json.loads(r).get('content', '')
    except Exception:
        # 该附件无全文索引是常态：降级为空串，主流程 len<500 会跳过，不影响其他篇
        return ''

def _parse_json_lenient(txt):
    """本地小模型偶尔在JSON外包裹解释或代码围栏，做容错解析。"""
    txt = txt.strip()
    txt = re.sub(r'^```(?:json)?|```$', '', txt, flags=re.M).strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r'\{.*\}', txt, re.S)   # 兜底：截第一个 {...}
        if m:
            return json.loads(m.group(0))
        raise   # 截取后仍无合法 JSON：本地模型输出损坏属意外，抛给上层报错，不静默

def ollama_extract(title, body):
    payload = {
        'model': LOCAL_MODEL,
        'format': 'json',                 # 让 Ollama 强制 JSON 输出
        'options': {'temperature': 0.1},
        'stream': False,
        'messages': [{'role': 'system', 'content': SYS},
                     {'role': 'user', 'content': build_user_prompt(title, body)}],
    }
    body_b = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(OLLAMA_CHAT, data=body_b,
        headers={'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return _parse_json_lenient(r['message']['content'])

def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    role.require_prod('全库结构化抽取', force=flag('--force'))
    # 已抽过的 key（精层 or 粗层都算），增量跳过；精层结果绝不覆盖
    # protected：精层记录（source != 'coarse'），即使 --rebuild 也跳过，防止被粗层降级（踩坑 #16）
    done = set(); protected = set()
    for f in os.listdir(OUT_DIR):
        if f.endswith('.json'):
            k = f[:-5]; done.add(k)
            try:
                if json.load(open(os.path.join(OUT_DIR, f), encoding='utf-8')).get('source') != 'coarse':
                    protected.add(k)
            except Exception:
                # 单个结果文件损坏就读不出 source：跳过精层保护判断，不影响主流程
                pass

    # 取所有顶层文献
    tops, start = [], 0
    while True:
        d = lget(f'/items/top?limit=100&start={start}')
        if not d: break
        tops += d; start += 100
        if len(d) < 100: break
    arts = [x for x in tops if x['data'].get('itemType') in
            ('journalArticle', 'conferencePaper', 'thesis', 'bookSection', 'book')]
    print(f'Zotero顶层文献 {len(arts)} 篇，开始本地粗层结构化抽取（模型 {LOCAL_MODEL}）...\n')

    processed = skipped = nofull = failed = 0
    for x in arts:
        key = x['key']
        title = x['data'].get('title', key)
        if key in protected:            # 精层结果绝不被粗层覆盖，即使 --rebuild（踩坑 #16）
            skipped += 1; continue
        if key in done and not REBUILD:
            skipped += 1; continue
        try:
            children = lget(f'/items/{key}/children')
        except Exception:
            # Zotero 读子条目失败就跳过该篇（如条目刚被删），不中断全库流程
            continue
        att = next((c['key'] for c in children
                    if c['data'].get('contentType') == 'application/pdf'), None)
        if not att:
            nofull += 1; continue
        txt = get_fulltext(att)
        if len(txt) < 500:
            nofull += 1; continue
        body = hierarchical_body(txt)
        try:
            data = ollama_extract(title, body)
        except Exception as e:
            print(f'[抽取失败] {title[:40]}: {e}'); failed += 1; continue   # 单篇失败计入 failed 继续下一篇
        record = {'key': key, 'title': title, 'doi': x['data'].get('DOI', ''),
                  'source': 'coarse', **data}   # 标注来源=粗层，便于区分
        json.dump(record, open(os.path.join(OUT_DIR, f'{key}.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        processed += 1
        print(f'[{processed}] {title[:45]}')
        time.sleep(0.1)

    # 汇总所有结构化记录（粗+精）成同一张对比表
    all_recs = [json.load(open(os.path.join(OUT_DIR, f), encoding='utf-8'))
                for f in sorted(os.listdir(OUT_DIR)) if f.endswith('.json')]
    if all_recs:
        build_compare_table(all_recs)
    print(f'\n完成：新抽 {processed} 篇，已有跳过 {skipped}，无全文 {nofull}，失败 {failed}')
    print(f'对比表：{os.path.join(OUT_DIR, "compare.md")}（共 {len(all_recs)} 篇）')

if __name__ == '__main__':
    main()
