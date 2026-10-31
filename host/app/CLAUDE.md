# host/app · 文献库应用 —— 给 LLM 的说明

> 你可能是被单独选中这个文件夹打开的。本文件是你的全部上下文。
> 用户是材料方向研究者，**不懂编程**。

## 是什么

直连证据库的**独立应用**（2026-10-11 用户定：不放进控制面板，以后做大成功能完善的客户端）。
技术路线（用户点头）：**FastAPI 后台 + Vue 3 前台（Vite 打包）**。第一版只有检索页。

```
浏览器（前台 web/）  ←→  server.py（127.0.0.1:8780）  ←→  tools.library（dbsearch / teams / oaindex）  ←→  证据库
```

## 铁律：后台一行业务逻辑都不写

同控制面板：检索、文献卡片在 `tools.library.dbsearch`，团队在 `tools.library.teams`。
后台只做「把它们开成 HTTP 接口 + 托管前台页面」。要加功能，先在工具层做，再开接口。

## 导入（2026-10-31 加，应用里唯一会写库的地方）

用户：「现在没有直接导入文献的功能」→ 定只做「贴 DOI 去取」（拖 PDF 进来以后再说）。

- 前台 `ImportPanel.vue`：贴一段文字（DOI / doi.org 链接 / 参考文献都行）→ `POST /api/import`；
  进度轮询 `GET /api/import/status`；没取到且可重试的，「重试」按钮再交一次。
- 后台**不另写取全文逻辑**：认 DOI 是 `getpdf.extract_dois`，库里已有正文的（`getpdf.in_library`）不再取，
  其余交给 `host.mcp.science._fulltext` —— 和 Claude Science 的 `paper_fulltext` **同一条队列、同一套闸**
  （一次 ≤25 篇、同时只一个作业、每篇隔 20 秒、撞验证码停、提交前问 Crossref 退回无效 DOI），取到后自动解析。
  所以「最近一批」可能是 Claude Science 交的，也显示在导入页上。
- 取完自动补作者 + 摘要、重挂研究团队（`host/mcp/fulltext_job.py` 收尾时做，只查新的那几篇），卡片上不会再是「没有作者数据」。
- 只新增，不删不覆盖。会动东西的请求另查 `Origin`（挡别的网站借浏览器偷发 POST）。

## 跑在哪、怎么打开

- 跑在**主力机**（数据在那边），看门狗按端口 8780 守着（`host/watcher/watchdog.py` 的 `port_services`），掉了一分钟内拉起。
- 只绑 127.0.0.1，Host 头必须是本机 + 本端口（挡 DNS 重绑定）。
- 编程机：隧道任务 `LiteraturePlatformTunnel` 把主力机 8780 接到本机，浏览器开 http://127.0.0.1:8780 。

## 前台怎么改、怎么上线

```bash
cd host/app/web
npm install          # 第一次
npm run dev          # 开发：5173 端口，接口转给本机 8780（先 python -m host.app.server）
npm run build        # 打包到 dist/
```

`node_modules/` 与 `dist/` **不进版本库**（生成物）。主力机没装 Node，所以**在编程机打包、把 dist/ 传过去**：
`python toolbox/remote-machine/remote.py push host/app/web/dist/<文件> host/app/web/dist/<文件>`（逐个文件），
再停掉 8780 上的进程让看门狗拉起新的。

## 改完怎么验证

```
python -m pytest -q host/app/tests      # 离线：接口在、只认本机 Host、文件接口不放任意路径
python -m host.app.server               # 然后浏览器开 http://127.0.0.1:8780 真点一遍
```
