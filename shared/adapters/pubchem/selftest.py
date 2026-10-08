# -*- coding: utf-8 -*-
"""pubchem 自测：取 SMILES 的字段名兼容离线验；真去问一次 PubChem 藏在 --live 后面。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import pubchem
from shared.kernel.cli import flag


def main():
    ok = total = 0

    def check(name, cond, detail=''):
        nonlocal ok, total
        total += 1
        if cond:
            print(f'  [PASS] {name}'); ok += 1
        else:
            print(f'  [FAIL] {name}  {detail}')

    check('新字段名 SMILES 优先', pubchem.pick_smiles({'SMILES': 'B(O)(O)O', 'CanonicalSMILES': 'x'}) == 'B(O)(O)O')
    check('老字段名也认', pubchem.pick_smiles({'IsomericSMILES': 'OB(O)O'}) == 'OB(O)O')
    check('都没有 → None', pubchem.pick_smiles({'MolecularFormula': 'BH3O3'}) is None and pubchem.pick_smiles(None) is None)
    check('空 CAS 号 → None（不发请求）', pubchem.cas_to_structure('') is None)

    if flag('--live'):
        try:
            r = pubchem.cas_to_structure('10043-35-3')
            check(f'真查硼酸：{r}', bool(r) and r['cid'] == 7628 and r['formula'] == 'BH3O3')
        except pubchem.PubChemError as e:
            check('真查硼酸', False, str(e))
    else:
        print('  [SKIP] 真去问 PubChem（加 --live）')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
