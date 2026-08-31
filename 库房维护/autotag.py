# -*- coding: utf-8 -*-
"""【已弃用 · 2026-07-25】不要再运行本脚本。

用户明确表示自动标签"没什么用还很多余"，已清理全部 690 种分类标签
（type/ mechanism/ topic/ method/ material/ 前缀，共1500次标记）。
Zotero 现在只保留「待精读」「已精读」两个工作流标签。

如需重新启用，先与用户确认。备份见 workflow_data/backup/zotero_tags_backup.json
"""
import os, json, sys, urllib.request, urllib.error, re, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import flag, opt
from shared.kernel.config import get_key, get_model, need_site, get_site
from shared.adapters import zotero_client as zotero
from shared.adapters.llm_client import chat_json as _chat_json

# 本机配置（Zotero 用户ID / 附件目录）统一从 shared.kernel.config 读，换电脑只改 .env
_UID = need_site('ZOTERO_USER_ID')
_STORAGE = need_site('ZOTERO_STORAGE')
USER_ID = _UID
KEY = get_key('ZOTERO_API_KEY')
LOCAL = get_site('ZOTERO_API_HOST') + '/api/users/' + USER_ID
LH = {'Zotero-Allowed-Request': 'true'}
DEEPSEEK_KEY = get_key('DEEPSEEK_KEY')
MODEL = get_model('AUTOTAG_MODEL')  # 打标签用flash：快、便宜、JSON稳

TEST = flag('--test')
APPLY = flag('--apply')
_limit = opt('--limit')
LIMIT = int(_limit) if _limit else None

SYSTEM = """你是科研文献标注助手，专注高分子材料领域。根据文献的标题和摘要，给它打上分类标签。
只输出一个JSON对象，格式：
{"topic":["..."],"material":["..."],"mechanism":["..."],"method":["..."],"type":"research/review/thesis"}
规则：
- 所有标签值用英文小写、连字符连接（如 self-healing, impact-resistant, hydrogen-bond）。
- topic：研究主题方向（如 self-healing, impact-resistant, shear-stiffening, phase-separation, recyclable, adhesive, energy-dissipation）
- material：涉及的材料体系（如 polyurea, polyborosiloxane, pdms, polyurethane, hydrogel, elastomer, ionic-liquid）
- mechanism：关键机制或化学（如 hydrogen-bond, dynamic-bond, boron-chemistry, coordination-bond, sacrificial-bond, crosslinking, microphase-separation）
- method：主要表征或计算方法（如 rheology, dsc, tensile-test, md-simulation, dft, saxs, ftir, gpc）——没提到就留空数组。
- type：research(研究论文)/review(综述)/thesis(学位论文)
- 每类2-5个最贴切的标签，宁精不滥。只输出JSON，不要解释。"""

def lget(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(LOCAL+p, headers=LH), timeout=20).read())

def tag_llm(title, abstract):
    user = f'标题：{title}\n\n摘要：{abstract[:2000]}'
    return _chat_json(SYSTEM, user, provider='deepseek', model=MODEL, key=DEEPSEEK_KEY)

def to_tags(result):
    tags = []
    for dim in ['topic', 'material', 'mechanism', 'method']:
        for v in result.get(dim, []):
            if v and isinstance(v, str):
                tags.append(f'{dim}:{v.strip().lower()}')
    t = result.get('type')
    if t: tags.append(f'type:{t.strip().lower()}')
    return tags


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    forced = flag('--force')
    role.require_prod('自动打标签（写回 Zotero）', force=forced)
    # 取有摘要的文献
    tops = []; s = 0
    while True:
        d = lget(f'/items/top?limit=100&start={s}')
        if not d: break
        tops += d; s += 100
        if len(d) < 100: break
    arts = [x for x in tops if x['data'].get('itemType') in ('journalArticle','conferencePaper','thesis','bookSection')
            and x['data'].get('abstractNote')]
    # 增量：apply模式跳过已有维度标签的（避免重复处理，支持中断续跑）
    if APPLY:
        arts = [x for x in arts if not any(':' in t.get('tag','') for t in x['data'].get('tags',[]))]
    if LIMIT: arts = arts[:LIMIT]
    elif TEST: arts = arts[:6]

    print(f'处理 {len(arts)} 篇（{"试打" if TEST else "写入"}，模型 {MODEL}）\n')
    for x in arts:
        key = x['key']; d = x['data']
        title = d.get('title', ''); abstract = d.get('abstractNote', '')
        try:
            res = tag_llm(title, abstract)
            tags = to_tags(res)
        except Exception as e:
            print(f'✗ {title[:35]} — 解析失败: {e}')
            continue
        print(f'《{title[:45]}》')
        print('  ' + '  '.join(tags))
        print()
        if APPLY:
            # 保留原有非维度标签，加上新标签（去重）
            old = [t for t in d.get('tags', []) if ':' not in t.get('tag','')]
            newtags = old + [{'tag': t} for t in tags]
            # 去重
            seen = set(); uniq = []
            for t in newtags:
                if t['tag'] not in seen:
                    seen.add(t['tag']); uniq.append(t)
            # 写走适配层：限流退避、版本冲突重取、机器角色守卫都在那里
            try:
                zotero.replace_tags(key, uniq, action='自动打标签', force=forced, log=print)
            except Exception as e:
                print(f'  [写回失败] {key}: {e}')
            time.sleep(0.3)

    print('完成')


if __name__ == '__main__':
    main()
