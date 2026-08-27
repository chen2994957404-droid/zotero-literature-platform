# -*- coding: utf-8 -*-
"""domain —— 纯逻辑环：文献领域自己的算法与格式，**不跟外部世界打交道**。

判据：**只有「我们自己想法变了」才需要改它**（换个裁图算法、改个分档规则、
加个字段）。外部世界怎么变都影响不到它 —— 那些归 adapters。

三条禁令（`tests/test_architecture.py` 会强制）：
    ❌ 不许联网（urllib / requests / httpx / socket）
    ❌ 不许 import 数据库或外部服务客户端（chromadb 等），不许起子进程
    ❌ 不许 import `core.paths` —— **domain 永远不知道文件放在哪**，
       路径一律由调用方传进来

第三条最容易被忽略，但它才是关键：一旦 domain 知道了 `workflow_data` 的布局，
它就跟我们的数据组织方式绑死了，也就不能被独立测试和复用。

允许的例外：`figure_crop` 依赖 PyMuPDF 读传入的 PDF 文件。
理由是坐标换算这件事十年不变（宪法【首要判据】判定为「自己做」的部分），
而 PyMuPDF 只是它的计算工具，不是它要适配的外部世界。
"""
