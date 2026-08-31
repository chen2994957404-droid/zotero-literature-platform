# -*- coding: utf-8 -*-
"""精读的 Zotero 状态标签状态机（用户 2026-07-25 定）。

**策略在这一层，写实现在 `shared.adapters.zotero_client`。**
哪些标签互斥、做成了什么该打哪个标签，是本工具的业务规则；
而「怎么安全地写进 Zotero」（鉴权、版本冲突、机器角色守卫）是适配层的事。

为什么单独一个文件（R2 窗，2026-08-30）：这套标签常量原来长在
`zotero_watcher.py` 里，批量补 SI 的脚本要用就得 `from zotero_watcher import ...`
—— 于是「跑一批 SI」会顺带把常驻服务那一整套（心跳、单实例锁、密钥自检）
拖进来。规则本身是纯数据，谁都能拿，不该藏在服务里。

状态互斥：**一篇文献同一时间只有一个状态标签。**
"""
from shared.adapters import zotero_client as zotero

TRIGGER_TAG = '待处理'                     # 打这个标签就触发（原「待精读」）
# 触发别名：用户不该被迫记住我们改过的词。任一个都算触发（踩坑 #29）。
# Zotero API 的 tag 参数支持 "A || B" 表示或。
TRIGGER_TAGS = ['待处理', '待精读']
TAG_MAIN = '正文精读'                      # 只有正文被精读
TAG_SI = 'SI精读'                          # 只有SI被精读（罕见，备用）
TAG_FULL = '全文精读'                      # 正文+SI 都精读了
TAG_NOPDF = '无附件'                       # 没找到可精读的PDF（提示用户，而非静默跳过）
ALL_STATE_TAGS = [TRIGGER_TAG, TAG_MAIN, TAG_SI, TAG_FULL, TAG_NOPDF, '待精读', '已精读']

# 「实际做成了什么」→ Zotero 状态标签。**这个映射只能在这一层**：
# 编排（`tools.deepread.run`）不知道 Zotero 有什么标签，它只陈述事实。
STATE_TAG = {'full': TAG_FULL, 'main': TAG_MAIN, 'si': TAG_SI, 'nopdf': TAG_NOPDF}


def set_state_tag(item_key, new_state, log=print):
    """设置状态标签（互斥）：移除所有旧状态标签，只留 new_state。

    保留用户自己的其它标签。写操作走适配层，机器角色守卫在那里。
    """
    try:
        cur = zotero.get_item(item_key)
        old = [t.get('tag') for t in cur['data'].get('tags', [])
               if t.get('tag') in ALL_STATE_TAGS]
        tags = [t for t in cur['data'].get('tags', [])
                if t.get('tag') not in ALL_STATE_TAGS]
        if new_state:
            tags.append({'tag': new_state})
        zotero.replace_tags(item_key, tags, action=f'把状态标签改成「{new_state}」')
        log(f'  [状态] {"/".join(old) or "无"} → {new_state}')
        return True
    except Exception as e:
        log(f'  [标签更新失败] {e}')
        return False
