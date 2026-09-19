# -*- coding: utf-8 -*-
"""typesafe 自测：题目拼装与响应解析离线验；真实调用只在 --live 时跑（花钱，默认 SKIP）。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.cli import flag
from shared.adapters import typesafe

RESP = {'model': 'jev-latest', 'answers': {
    'urgent': {'type': 'noul', 'noul': 0.92},
    'dept': {'type': 'choice', 'choice': 'technical',
             'probabilities': {'billing': 0.08, 'technical': 0.85, 'sales': 0.07}, 'confidence': 0.82},
    'mood': {'type': 'score', 'score': 1.6, 'legend': {'0': 'Calm', '1': 'Frustrated', '2': 'Very angry'},
             'probabilities': {'0': 0.05, '1': 0.3, '2': 0.65}, 'confidence': 0.78}},
    'usage': {'input_tokens': 312, 'output_tokens': 48}}

ABSTRACT = ('A self-healing polyborosiloxane elastomer with dynamic B-O bonds recovers 95% of its '
            'tensile strength after 12 h at room temperature.')


def main():
    ok = total = 0
    total += 1
    q = typesafe.build_questions(noul={'a': ('urgent?', None)},
                                 choice={'b': ('which?', {'x': 'X', 'y': None})},
                                 score={'c': ('how?', ['low', 'high'])})
    if q['a'] == {'type': 'noul', 'instructions': 'urgent?'} and q['b']['criteria'] == {'x': 'X', 'y': None} \
            and q['c']['criteria'] == ['low', 'high']:
        print('  [PASS] 三类题拼成接口格式'); ok += 1
    else:
        print('  [FAIL] 拼装不对：%s' % q)
    total += 1
    try:
        typesafe.build_questions(score={'c': ('how?', ['only-one'])})
        print('  [FAIL] score 一档没被拦')
    except Exception:
        print('  [PASS] score 少于 2 档被拦'); ok += 1
    total += 1
    a = typesafe.parse_answers(RESP)
    if a['urgent']['value'] == 0.92 and a['dept']['value'] == 'technical' and a['dept']['confidence'] == 0.82 \
            and a['mood']['value'] == 1.6 and a['mood']['legend']['2'] == 'Very angry':
        print('  [PASS] 响应解析成简化结果'); ok += 1
    else:
        print('  [FAIL] 解析不对：%s' % a)
    if flag('--live'):
        total += 1
        try:
            c, p, conf = typesafe.choice(
                ABSTRACT, 'Which topic does this abstract belong to?',
                {'dynamic_bond_elastomer': 'self-healing / dynamic covalent or supramolecular polymers',
                 'battery': 'electrochemical energy storage',
                 'catalysis': 'catalysts and chemical reactions'},
                purpose='SELFTEST')
            if c == 'dynamic_bond_elastomer':
                print('  [PASS] 真实调用：选中 %s（置信 %.2f，分布 %s）' % (c, conf, p)); ok += 1
            else:
                print('  [FAIL] 真实调用选错：%s %s' % (c, p))
        except Exception as e:
            print('  [FAIL] 真实调用失败：%s' % str(e)[:200])
    else:
        print('  [SKIP] 真实调用要加 --live（花钱）')
    print('\n%d/%d 通过' % (ok, total))
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
