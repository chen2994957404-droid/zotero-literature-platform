# -*- coding: utf-8 -*-
"""批量给「已有正文精读 + 有SI」的文献补做 SI 精读，合并后回写 Zotero 并升级标签。

用法: python si_batch.py --file keys.txt    |    python si_batch.py KEY1 KEY2
"""
import os, sys, io, subprocess, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT); sys.path.insert(0, SCRIPT_DIR)
LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')


def run(script, args, timeout=900):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, script)] + args,
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env, timeout=timeout, cwd=ROOT)
    return r


def main():
    if '--file' in sys.argv:
        keys = [l.strip() for l in io.open(sys.argv[sys.argv.index('--file')+1],
                                           encoding='utf-8') if l.strip()]
    else:
        keys = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(f'批量补 SI 精读：{len(keys)} 篇\n', flush=True)

    from zotero_watcher import set_state_tag, TAG_FULL, USER_ID, upload_attachment, \
        find_existing_summary, STORAGE_DIR
    import shutil

    ok = fail = 0
    for i, key in enumerate(keys, 1):
        print(f'[{i}/{len(keys)}] {key}', flush=True)
        # 1. SI 精读
        r = run('si_deepread.py', [key])
        si_html = os.path.join(LIBRARY, key, 'si_summary.html')
        if not os.path.exists(si_html):
            print(f'  SI精读失败: {(r.stdout or r.stderr)[-200:]}', flush=True)
            fail += 1; continue
        print('  SI精读完成', flush=True)
        # 2. 合并
        run('merge_summary.py', [key, '--no-upload'], timeout=300)
        merged = os.path.join(LIBRARY, key, 'summary_full.html')
        final = merged if os.path.exists(merged) else si_html
        # 3. 回写（复用附件条目，避免同步冲突）
        try:
            att = find_existing_summary(key) or upload_attachment(key, final, 'summary')
            if att:
                dd = os.path.join(STORAGE_DIR, att)
                os.makedirs(dd, exist_ok=True)
                # 按 Zotero 记录的文件名写，避免"找不到文件"
                import json, urllib.request
                LH = {'Zotero-Allowed-Request': 'true'}
                info = json.loads(urllib.request.urlopen(urllib.request.Request(
                    f'http://localhost:23119/api/users/{USER_ID}/items/{att}',
                    headers=LH), timeout=15).read())
                fn = info['data'].get('filename') or 'summary.html'
                shutil.copy(final, os.path.join(dd, fn))
                print(f'  附件已更新（{fn}）', flush=True)
            set_state_tag(key, USER_ID, TAG_FULL)
            ok += 1
        except Exception as e:
            print(f'  回写失败: {e}', flush=True); fail += 1
        time.sleep(0.5)
    print(f'\n完成：成功 {ok}，失败 {fail}', flush=True)


if __name__ == '__main__':
    main()
