# -*- coding: utf-8 -*-
"""query_expand 自测：验证扩展能真的产出多个互补检索式，且降级安全。"""
import sys, os
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pipelines.query_expand import to_english, expand, looks_chinese, _clean_lines

def main():
    ok = 0; total = 5
    if looks_chinese("聚硼硅氧烷") and not looks_chinese("polyborosiloxane"):
        print("  [PASS] 中英文判别"); ok += 1
    else:
        print("  [FAIL] 中英文判别有问题")

    raw = "1. shear thickening gel\n- borosiloxane creep\n\n2) 中文的应该被剔除\nabc"
    c = _clean_lines(raw, 5)
    if "shear thickening gel" in c and "borosiloxane creep" in c and not any(looks_chinese(x) for x in c):
        print(f"  [PASS] 清洗LLM输出（去编号/去中文）: {len(c)} 条"); ok += 1
    else:
        print(f"  [FAIL] 清洗结果异常: {c}")

    if expand("shear stiffening gel", n=1) == ["shear stiffening gel"]:
        print("  [PASS] n=1 时原样返回，不调用LLM"); ok += 1
    else:
        print("  [FAIL] n=1 行为不对")

    q = expand("polyborosiloxane shear stiffening", mode="survey", n=4)
    if len(q) >= 2 and q[0] == "polyborosiloxane shear stiffening":
        print(f"  [PASS] 系统调研模式产出 {len(q)} 个检索式，首个是原式"); ok += 1
        for x in q[1:]:
            print(f"         · {x}")
    else:
        print(f"  [FAIL] 扩展失败: {q}")

    q2 = expand("my material creeps at room temperature", mode="problem", n=4)
    if len(q2) >= 2 and not any(looks_chinese(x) for x in q2):
        print(f"  [PASS] 解决问题模式产出 {len(q2)} 个检索式，全英文"); ok += 1
    else:
        print(f"  [FAIL] 问题模式异常: {q2}")

    print(f"\n{ok}/{total} 通过")
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
