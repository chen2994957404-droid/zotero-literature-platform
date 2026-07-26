# -*- coding: utf-8 -*-
"""config 自测：验证密钥加载链路（环境变量 → .env）与缺失时的报错。
用法: python modules/config/selftest.py
"""
import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from modules.config import get_key, all_keys, ENV_FILE


def main():
    ok = total = 0

    # 1. 环境变量优先
    total += 1
    os.environ['_TEST_CFG_KEY'] = 'from_env'
    if get_key('_TEST_CFG_KEY') == 'from_env':
        print('  [PASS] 环境变量能读到'); ok += 1
    else:
        print('  [FAIL] 环境变量读取失败')
    os.environ.pop('_TEST_CFG_KEY', None)

    # 2. 缺失时返回默认值、不抛异常
    total += 1
    if get_key('_NOT_EXIST_KEY_XYZ', default='fallback') == 'fallback':
        print('  [PASS] 缺失时返回默认值'); ok += 1
    else:
        print('  [FAIL] 缺失处理异常')

    # 3. required=True 时抛出带指引的错误（避免静默失败）
    total += 1
    try:
        get_key('_NOT_EXIST_KEY_XYZ', required=True)
        print('  [FAIL] required 缺失时应报错')
    except RuntimeError as e:
        if 'setx' in str(e) or '.env' in str(e):
            print('  [PASS] required 缺失时报错并给出指引'); ok += 1
        else:
            print('  [FAIL] 报错信息缺少修复指引')

    # 4. .env 文件存在时能读到真实密钥
    total += 1
    if os.path.exists(ENV_FILE):
        keys = all_keys()
        if keys:
            print(f'  [PASS] .env 可用，配置项 {len(keys)} 个'); ok += 1
        else:
            print('  [FAIL] .env 存在但读不到配置')
    else:
        print('  [SKIP] 无 .env 文件（首次使用请复制 .env.example）'); ok += 1

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
