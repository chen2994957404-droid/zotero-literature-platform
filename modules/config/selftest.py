# -*- coding: utf-8 -*-
"""config 自测：验证密钥加载链路（环境变量 → .env）与缺失时的报错。
用法: python modules/config/selftest.py
"""
import sys, os, tempfile, io

# 可能被无控制台的 pythonw 拉起，强制 UTF-8 输出（踩坑 #32）
# 用 reconfigure 而非替换 sys.stdout：后者会让原对象被回收、底层缓冲被关闭，
# 表现为程序跑到一半 print 抛「I/O operation on closed file」（踩坑 #37）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.config import (get_key, all_keys, ENV_FILE, keyring_status,
                            key_location, _kr_set, _kr_get, SECRET_KEYS)


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

    # 5. 系统凭据库可用性（不可用不算失败，会自动降级到 .env）
    total += 1
    avail, backend = keyring_status()
    print(f'  [{"PASS" if avail else "SKIP"}] 系统凭据库：{backend}'); ok += 1

    # 6. 凭据库存取往返 + get_key 能优先读到它 —— 这是本次安全升级的核心承诺
    total += 1
    if avail:
        probe = '_SELFTEST_SECRET'
        try:
            import modules.config as C
            C.SECRET_KEYS = tuple(SECRET_KEYS) + (probe,)   # 临时把探针当密钥
            _kr_set(probe, 'kr_value')
            C._cache = None
            got = get_key(probe)
            import keyring
            keyring.delete_password(C.KEYRING_SERVICE, probe)
            C.SECRET_KEYS = SECRET_KEYS
            if got == 'kr_value':
                print('  [PASS] 密钥可存入凭据库并被 get_key 优先读到'); ok += 1
            else:
                print(f'  [FAIL] 凭据库存取往返失败: {got!r}')
        except Exception as e:
            print(f'  [FAIL] 凭据库操作异常: {e}')
    else:
        print('  [SKIP] 凭据库不可用，跳过往返测试'); ok += 1

    # 7. 真实密钥现在存在哪 —— 提示是否还有明文残留
    total += 1
    locs = {k: key_location(k) for k in SECRET_KEYS}
    plain = [k for k, v in locs.items() if v == '.env明文']
    print(f'  [{"PASS" if not plain else "WARN"}] 密钥存放：'
          + '、'.join(f'{k}={v}' for k, v in locs.items()))
    if plain:
        print(f'         ↑ 这些仍是明文，建议在控制面板点「迁移到系统凭据库」：{plain}')
    ok += 1     # 明文残留只提醒，不判失败（迁移是用户的决定）

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
