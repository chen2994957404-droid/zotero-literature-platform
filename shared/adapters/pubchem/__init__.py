# -*- coding: utf-8 -*-
"""pubchem · PubChem 公开化合物库（免费、不要密钥）—— 目前只用它把 CAS 号换成结构式

**为什么有这块（2026-10-08）**：Reaxys 里 CAS 号的登记不全。硼酸 10043-35-3 在 Reaxys 只挂在 7 个
矿物 / 水合物条目上（文献最多的 9 篇，全是 19 世纪晶体学），真正的硼酸主条目没登记这个号。
按 CAS 号查 Reaxys 就落不到主条目。PubChem 的同义词里有 CAS 号，换成结构式再去 Reaxys 按结构搜，就对了。

对外接口：
  | 函数 | 说明 |
  |---|---|
  | `cas_to_structure(cas)` | → {cid, smiles, formula} 或 None（查不到） |
  | `pick_smiles(props)` | PubChem 属性字典里取 SMILES（字段名换过：SMILES / IsomericSMILES / CanonicalSMILES） |

接口：PUG REST `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/<CAS>/property/...`（2026-10-08 实测：
10043-35-3 → CID 7628、BH3O3、`B(O)(O)O`；返回字段名是 `SMILES`，不是老文档里的 `IsomericSMILES`）。
PubChem 限速每秒 5 次，这里一次只问一个号。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from shared.kernel import errors

BASE = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug'
UA = 'literature-platform/1.0'
_SMILES_KEYS = ('SMILES', 'IsomericSMILES', 'CanonicalSMILES', 'ConnectivitySMILES')


class PubChemError(errors.ExternalServiceError):
    """PubChem 查询失败（对方的问题，可重试）。"""


def pick_smiles(props):
    for k in _SMILES_KEYS:
        if (props or {}).get(k):
            return props[k]
    return None


def cas_to_structure(cas, timeout=20):
    """CAS 号 → {cid, smiles, formula}；PubChem 没这个号 → None。"""
    cas = (cas or '').strip()
    if not cas:
        return None
    url = (f'{BASE}/compound/name/{urllib.parse.quote(cas)}/property/'
           'SMILES,IsomericSMILES,CanonicalSMILES,MolecularFormula/JSON')
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise PubChemError(f'HTTP {e.code}') from e
    except Exception as e:
        raise PubChemError(f'{type(e).__name__}: {e}') from e
    props = ((d.get('PropertyTable') or {}).get('Properties') or [None])[0]
    if not props or not pick_smiles(props):
        return None
    return {'cid': props.get('CID'), 'smiles': pick_smiles(props), 'formula': props.get('MolecularFormula')}
