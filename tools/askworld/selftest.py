# -*- coding: utf-8 -*-
"""askworld 自测：不联网、不调 LLM，验「只答有据的、低相关度被滤掉」这条承诺。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from tools import askworld

EV = [
    {'title': 'Shear stiffening gel', 'year': 2021, 'venue': 'AM', 'citations': 30,
     'page': 3, 'score': 0.91, 'chunk': 'The gel stiffens above 100 s-1.'},
    {'title': 'Borosilicate glass irradiation', 'year': 2009, 'venue': 'JNM',
     'citations': 5, 'page': None, 'score': 0.42, 'chunk': 'Irradiation of glass.'},
]


def main():
    ok = total = 0
    real = (askworld.to_english, askworld.ask_evidence, askworld.chat)
    seen = {}

    def fake_chat(system, user, **kw):
        seen['user'] = user
        seen['system'] = system
        return '中文答案 [1]'

    askworld.to_english = lambda q, context=None: 'shear stiffening mechanism'
    askworld.ask_evidence = lambda q, top_k=8, year_from=None: (
        seen.setdefault('query', q), EV)[1]
    askworld.chat = fake_chat
    try:
        total += 1
        r = askworld.ask_world('剪切硬化机理是什么')
        if seen.get('query') == 'shear stiffening mechanism':
            print('  [PASS] 中文问题先转英文再检索（踩坑 #35）'); ok += 1
        else:
            print(f'  [FAIL] 没转英文就去检索了：{seen.get("query")}')

        total += 1
        if len(r['evidence']) == 1 and r['evidence'][0]['score'] == 0.91:
            print('  [PASS] 相关度 0.42 的噪声片段被滤掉（门槛 0.60）'); ok += 1
        else:
            print(f'  [FAIL] 低相关度片段没滤干净：{[e["score"] for e in r["evidence"]]}')

        total += 1
        if 'The gel stiffens' in seen.get('user', '') \
                and 'Irradiation of glass' not in seen.get('user', ''):
            print('  [PASS] 只有留下的片段进提示词'); ok += 1
        else:
            print('  [FAIL] 提示词里的片段不对')

        total += 1
        if '不要用你自己的知识补充' in seen.get('system', ''):
            print('  [PASS] 系统提示词写死「不许自由发挥」（可追溯的前提）'); ok += 1
        else:
            print('  [FAIL] 系统提示词丢了可追溯约束')

        total += 1
        askworld.ask_evidence = lambda q, top_k=8, year_from=None: []
        r2 = askworld.ask_world('库里外都没有的东西')
        if r2['answer'] == '' and r2['evidence'] == [] and r2['query_used']:
            print('  [PASS] 没证据就不作答（不硬编）'); ok += 1
        else:
            print(f'  [FAIL] 无证据时的行为不对：{r2}')
    finally:
        askworld.to_english, askworld.ask_evidence, askworld.chat = real

    total += 1
    if askworld.norm_title('Shear-Thickening Gel!') == askworld.norm_title('shear thickening gel'):
        print('  [PASS] 标题归一（用于「这篇我有没有」）'); ok += 1
    else:
        print('  [FAIL] 标题归一有问题')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
