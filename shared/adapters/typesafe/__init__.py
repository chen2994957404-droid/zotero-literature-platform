# -*- coding: utf-8 -*-
"""typesafe · TypeSafe 的「只判断不写字」模型 Jev（2026-09-19 建，试用）。

**解决的真实问题**：平台里有一批「判断」环节 —— 一篇文献跟方向贴不贴、该打哪个标签、
抽出来的数字原文支不支持 —— 现在要么靠向量相似度加规则，要么就没做。
普通大模型做这些要写一段话再解析，慢且贵；Jev 只回**答案 + 概率 + 置信度**，
输入 $0.042/M token、输出免费（2026-09-18 查 docs.typesafe.ai/models，标注价格动态调整）。

三种题型（接口 `POST /v1/systemone`，一次可带多题、同一份 state）：
  - noul   真假：  {'type':'noul','instructions':'...','criteria':{'true':'...','false':'...'}} → noul 0–1
  - choice 选一个：{'type':'choice','instructions':'...','criteria':{选项:说明}}            → choice / probabilities / confidence
  - score  打分：  {'type':'score','instructions':'...','criteria':[档位说明...]}             → score（0 起的实数）/ probabilities / confidence

硬限制（模型页）：纯文字、64k/次、state ≤32k、英文最准、**没有公开评测** —— 好不好我们自己测。

对外接口：
  - ask(state, questions, model=None, purpose='')  → 简化后的 answers 字典（记账、限额闸都在这里）
  - noul(state, instructions, ...)   → float
  - choice(state, instructions, options, ...) → (choice, probabilities, confidence)
  - score(state, instructions, levels, ...)   → (score, probabilities, confidence)
  - build_questions(...) 与 parse_answers(...) 是纯函数，自测用

密钥名 `TYPESAFE_KEY`（控制面板填）。没填 → 抛 ConfigError，调用方决定退路。

依赖：Python 标准库 + shared.kernel.config / errors / log / budget。
"""
import json
import time
import urllib.error
import urllib.request

from shared.kernel import errors, budget
from shared.kernel.log import get_logger

BASE = 'https://api.typesafe.ai/v1/systemone'
DEFAULT_MODEL = 'jev-latest'
CHANNEL = 'typesafe'
_log = get_logger('typesafe')


class TypeSafeError(errors.ExternalServiceError):
    """TypeSafe 调用失败（限速 / 过载可重试；401 / 422 不可）。"""


def _key():
    from shared.kernel.config import get_key
    k = (get_key('TYPESAFE_KEY') or '').strip()
    if not k:
        raise errors.ConfigError('没填 TypeSafe 的密钥（控制面板 → 设置与密钥 → TypeSafe Jev）')
    return k


def build_questions(noul=None, choice=None, score=None):
    """把三类题拼成接口要的 questions 字典（纯函数）。

    noul:   {id: (instructions, {'true':..., 'false':...} 或 None)}
    choice: {id: (instructions, {option: 说明或None})}
    score:  {id: (instructions, [档位说明, ...])}  # 至少 2 档
    """
    q = {}
    for qid, (ins, crit) in (noul or {}).items():
        d = {'type': 'noul', 'instructions': ins}
        if crit:
            d['criteria'] = crit
        q[qid] = d
    for qid, (ins, opts) in (choice or {}).items():
        if not opts or len(opts) < 2:
            raise errors.BadInputError(f'choice 题「{qid}」至少要 2 个选项')
        q[qid] = {'type': 'choice', 'instructions': ins, 'criteria': dict(opts)}
    for qid, (ins, levels) in (score or {}).items():
        if not levels or len(levels) < 2:
            raise errors.BadInputError(f'score 题「{qid}」至少要 2 档')
        q[qid] = {'type': 'score', 'instructions': ins, 'criteria': list(levels)}
    if not q:
        raise errors.BadInputError('一道题都没有')
    return q


def parse_answers(resp):
    """响应 → {id: 简化结果}（纯函数）。

    noul   → {'type':'noul','value':0.92}
    choice → {'type':'choice','value':'technical','probabilities':{...},'confidence':0.82}
    score  → {'type':'score','value':1.6,'probabilities':{...},'confidence':0.78,'legend':{...}}
    """
    out = {}
    for qid, a in (resp.get('answers') or {}).items():
        t = a.get('type')
        if t == 'noul':
            out[qid] = {'type': t, 'value': float(a.get('noul', 0.0))}
        elif t == 'choice':
            out[qid] = {'type': t, 'value': a.get('choice'),
                        'probabilities': a.get('probabilities') or {},
                        'confidence': float(a.get('confidence', 0.0))}
        elif t == 'score':
            out[qid] = {'type': t, 'value': float(a.get('score', 0.0)),
                        'probabilities': a.get('probabilities') or {},
                        'confidence': float(a.get('confidence', 0.0)),
                        'legend': a.get('legend') or {}}
        else:
            out[qid] = {'type': t or '?', 'raw': a}
    return out


def ask(state, questions, model=None, purpose='', timeout=60, retries=3):
    """一份 state + 若干题 → parse_answers 的结果。走当日额度闸并记账。"""
    budget.check(f'TypeSafe 判断（{purpose or "未标用途"}）')
    body = json.dumps({'state': state, 'model': model or DEFAULT_MODEL, 'questions': questions},
                      ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(BASE, data=body, method='POST', headers={
        'Authorization': 'Bearer ' + _key(), 'Content-Type': 'application/json',
        'User-Agent': 'literature-platform/1.0'})
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode('utf-8'))
            u = resp.get('usage') or {}
            budget.record(prompt=u.get('input_tokens', 0), completion=u.get('output_tokens', 0),
                          model=resp.get('model') or model or DEFAULT_MODEL,
                          purpose=purpose, channel=CHANNEL)
            return parse_answers(resp)
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', 'replace')[:300]
            except Exception:
                pass
            if e.code == 401:
                raise errors.AuthError('TypeSafe 密钥无效（401）') from e
            if e.code == 422:
                raise errors.BadInputError(f'TypeSafe 不认这个请求（422）：{detail}') from e
            last = TypeSafeError(f'HTTP {e.code} {detail}')
            if e.code not in (429, 529, 500, 502, 503):
                raise last from e
        except Exception as e:
            last = TypeSafeError(f'{type(e).__name__}: {e}')
        time.sleep(2 ** i)
    raise last


def noul(state, instructions, criteria=None, **kw):
    r = ask(state, build_questions(noul={'q': (instructions, criteria)}), **kw)
    return r['q']['value']


def choice(state, instructions, options, **kw):
    r = ask(state, build_questions(choice={'q': (instructions, options)}), **kw)['q']
    return r['value'], r['probabilities'], r['confidence']


def score(state, instructions, levels, **kw):
    r = ask(state, build_questions(score={'q': (instructions, levels)}), **kw)['q']
    return r['value'], r['probabilities'], r['confidence']
