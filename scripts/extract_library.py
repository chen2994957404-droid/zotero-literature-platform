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
import os, json, re, sys, urllib.request, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
# 复用精层的 schema 与提示词，保证字段一致
from extract_structured import (SCHEMA, SYS, build_user_prompt,
                                build_compare_table, hierarchical_body)

ROOT = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(ROOT, 'workflow_data', 'structured')
os.makedirs(OUT_DIR, exist_ok=True)

# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
try:
    from modules.config import need_site as _site
except Exception:
    _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
_UID = _site('ZOTERO_USER_ID')
_STORAGE = _site('ZOTERO_STORAGE')
USER_ID = _UID
LOCAL = 'http://localhost:23119/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
OLLAMA_CHAT = 'http://localhost:11434/api/chat'
LOCAL_MODEL = 'qwen2.5:7b-instruct'   # 本地抽取模型；qwen3:8b 亦可
REBUILD = '--rebuild' in sys.argv

def lget(path):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(LOCAL + path, headers=LH), timeout=20).read())

def get_fulltext(att_key):
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            LOCAL + f'/items/{att_key}/fulltext', headers=LH), timeout=20).read()
        return json.loads(r).get('content', '')
    except Exception:
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
        raise

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
            print(f'[抽取失败] {title[:40]}: {e}'); failed += 1; continue
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
