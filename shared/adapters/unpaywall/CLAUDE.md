# unpaywall · 合法开放获取全文

> 你可能是被单独选中这个模块文件夹打开的。本文件是你的全部上下文。

## 这是什么

一个原子模块：DOI → 这篇有没有合法免费的全文（出版社 OA / 机构库 / 作者存档），有就下回来。
取件流程里**先问它再走浏览器**：不碰出版商、不占机构权限、零风控风险。

## 对外接口

| 函数 | 说明 |
|---|---|
| `lookup(doi)` | → `{is_oa, pdf_url, version, host, license}` 或 `None` |
| `fetch_pdf(doi)` | → `(bytes, info)`；不是 PDF 或下载失败 `(None, info)` |
| `to_info(record)` | 原始 JSON → 上面的字典（纯函数） |

没配 `UNPAYWALL_EMAIL`（本机设置，真实邮箱即可，不用注册）→ 一律返回 None，调用方照常走别的路。

## 谁在用

- `tools/getpdf`：`fetch_one` / `fetch_pair` 取正文前先问它

## 改完必须做

```
python shared/adapters/unpaywall/selftest.py
python -m pytest -q
```
