---
name: two-machines
description: 涉及跑花钱的批量作业、起常驻服务（`host/watcher/` 看门狗、`host/app` 文献库应用）、部署代码到主力机、连 B 机排查、或需要知道 B 机真实状态时读这份。A/B 两台机器的分工与硬约束、ROLE 三档（dev/test/prod）各自允许什么、SSH 连 B 的正确姿势与它的两个陷阱、以及「部署≠换文件」的重启纪律。（连机器的**机械细节**已拆到全局技能 `remote-machine`，那份任何项目都能用。）
---

<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。改源：docs/howto/skills/two-machines.md -->

# 两台机器

**A 机 = 编程端（改代码的唯一入口）· B 机 = 运行端（数据与服务的唯一权威）。**
代码单向 A→B（走 git）；数据单向 B→A（只流一小撮样本）。两个方向都不许反着来。
完整原文：`docs/howto/两台机器的分工.md`。

**你能读到这句话，说明你在 A 机。**

## 一、硬约束（不是偏好，是物理限制）

| | A · 编程端（本机） | B · 运行端（主力机） |
|---|---|---|
| Claude Code | **只在这里** | 没有 |
| Ollama | 无（MX450 只有 2 GB，跑不动 bge-m3） | 有，带保活任务 |
| Zotero | 2026-10-13 起移出平台，平台不再用它 | 同左 |
| 项目路径 | `D:\dev\literature-platform` | `D:\02_AI\Projects\literature-platform` |
| `data/`（五层） | 自产的几篇（金样本） | **权威副本** |
| 自启任务 | **只有一个例外**：`LiteraturePlatformTunnel`（SSH 隧道：把 B 的 8778 MCP 与 8780 文献库应用接到本机，只往外连、不花钱不写库；`host/deploy/tunnel_task.py`）| 2 个：`ZoteroLiteratureWatcher`（名字是历史遗留，跑的是看门狗）/ `OllamaService` |

## 二、谁干什么（有争议以此为准）

| 事项 | A | B |
|---|---|---|
| 改代码 / pytest / 离线体检 | ✅ **唯一入口** | ❌ 绝不在 B 上改代码 |
| 完整档体检 | 可跑（几项红是正常的） | ✅ **权威结论以 B 为准** |
| 单篇精读验证 | ✅ 可以 | ✅ |
| 全库作业（全库向量化/抽取/批量重跑） | ❌ | ✅ **唯一** |
| 库内问答 `python -m tools.ask` | ❌ 没向量库没 Ollama | ✅ |
| 找新文献 / 外部检索 | ✅ | ✅ |
| 常驻服务 / 自启任务 | ❌ **绝不注册** | ✅ **唯一** |
| 花钱的批量作业 | ❌ | ✅ |

## 三、⚠ ROLE 三档 —— 别再照旧文档说「A 机一律不许写」

`shared/kernel/role.py` + `.env` 里的 `ROLE`（控制面板「本机设置」第一项可改）。

- **`dev`（A 机默认）**：拒绝起常驻服务 / 全库作业 / 花钱的批量，除非显式 `--force`
- **`test`（A 机现在是这一档）**：放行，产物只在 A 本机的 `data/` 里。
  （原来的意思是「A 机接测试 Zotero 账号、允许写测试库」，还要核对写回目标；
  2026-10-13 Zotero 移出平台，那道核对没有对象了。）
- **`prod`（B 机）**：全部允许

## 四、连 B 机（A 能直接连了，2026-08-28）

工具在 `toolbox/remote-machine/remote.py`（2026-09-08 并回仓库，同时装成**全局技能 `remote-machine`**）。
连 B 的姿势、四种「连不上」怎么分、编码在哪四个地方咬人 —— **全在那份技能里，读它**。
本节只留下「本项目特有」的那部分。

**先说结论，别每次重新摸索**（2026-09-17 实测）：`check` 3.5 秒、`run` 1.5 秒、`job` 5 秒往返，
连接本身不慢；慢的从来是**人**在犹豫走哪条路、拼引号、等超时。照下面这张表走，一次到位：

| 要干的事 | 一条命令 |
|---|---|
| 看 B 现在什么状态 | `remote.py check` |
| 看某个日志尾巴 | `remote.py logs watchdog 40`（`ingest` / `daily` / `app_jobs` 同理）|
| 跑只读命令（已自动进项目目录） | `remote.py run "git log --oneline -3"` |
| **上线**（推完 git 之后） | `remote.py deploy` —— 走 job 通道，体检里的密钥项才是真的；它会停掉旧的干活进程 |
| 跑要密钥 / 花钱的活 | `remote.py job "python -m tools.xxx ..." --async` 然后 `job --tail` |

```bash
python toolbox/remote-machine/remote.py check     # ← 用这个，别手敲 ssh
```

它把三个实测得出的细节包好了：**用户名是 `Administrator` 不是计算机名**（踩坑 #74）、
中文要套 UTF-8 外壳、连不上时把「该往哪查、不该往哪查」直接打出来（踩坑 #97）。
B 机的地址、账号、任务名、日志位置都在 `~/.remote-machine/machines.toml` 里（机器名 `zotero-b`）。

底层就是这条，需要时可以自己敲：
```bash
ssh -i ~/.ssh/id_ed25519_zotero_b -o BatchMode=yes Administrator@192.168.123.216 "hostname"
```

中文输出会乱码（B 那边默认 GBK），套一层：
```bash
ssh -i ~/.ssh/id_ed25519_zotero_b -o BatchMode=yes Administrator@192.168.123.216 \
  "\$OutputEncoding=[System.Text.Encoding]::UTF8; \
   [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; \
   \$env:PYTHONIOENCODING='utf-8'; <你的 PowerShell 命令>"
```
复杂脚本别硬拼引号，**用 `scp` 传过去再执行**，跑完删掉临时文件。

### ⚠ 陷阱 1：SSH 会话里读不到密钥 —— 花钱的作业要走 `job` 通道

**ssh 直接跑**（`remote.py run`）：`get_key('DEEPSEEK_KEY')` **返回空串**。
不是权限问题 —— 公钥 SSH 建立的是**网络登录会话**，凭据管理器在这种会话里整个打不开
（真话是 `CredRead: 指定的登录会话不存在`，被 `get_key` 的静默降级盖住了，踩坑 #101）。
所以从 `run` 发起的重抽/精读/向量化会在第一次调模型时废掉，还是跑到一半才废。

**`job` 通道**（2026-09-03 打通，已实测）：**没有这个限制**。

```bash
python toolbox/remote-machine/remote.py job --install        # 只做一次（B 上已经装过了）
python toolbox/remote-machine/remote.py job "<PowerShell>"   # B 用自己的身份跑，密钥读得到
```

原理：它触发一个 `LogonType=Interactive` 的计划任务，那个会话跑在 `SessionId=1`，
凭据库正常可读。
实测拿到 35 位密钥并真调了一次 DeepSeek 补全。

| 要干的事 | 走哪条 |
|---|---|
| `git pull` / 装包 / pytest / 离线体检 / 读日志读数据 | `run`（更快，一条 ssh 就完） |
| 任何调付费 API 的、要密钥的、要跑超过几分钟的 | **`job`**（`--async` 不等它）|

所以「给用户一个 .bat 让他双击」不再是唯一出路 —— 但**大批量作业仍然先问用户**
（那是钱的量级问题，不是能力问题）。⚠ 这条通道一次只跑一个作业。

### ⚠ 陷阱 2：远程 `git pull` 之后，B 上跑的还是旧代码
面板、文献库应用（8780）、MCP 服务（8778）都是长驻进程，磁盘上代码换了它们照跑旧的（2026-08-28 咬过：
给用户加了按钮，用户在面板上**根本看不到**；而 `launch/控制面板.bat` 检测到面板还活着
只开浏览器**不会重启它**，所以「关窗口再双击」也没用）。

远程 pull 之后：`remote.py deploy`（会重启看门狗和它的孙子进程），或者按端口停掉那个进程、让看门狗一分钟内拉起新的 ——
```bash
$p=(Get-NetTCPConnection -LocalPort 8780 -State Listen).OwningProcess; Stop-Process -Id $p -Force   # 8777 面板 / 8778 MCP 同理
```
文献库应用的前台（`host/app/web/dist`）不进版本库：在 A 机 `npm run build`，用 `remote.py push` 逐个传过去。

## 五、B 机的状态怎么让你看见

这是本方案最大的摩擦。除了 SSH（受上面两个陷阱限制），
其余靠**用户把诊断报告贴给你**。

**给用户的东西不能是「要敲命令的工具」** —— 他不懂编程。
凡是要他在 B 机上做的事，做成**双击就能跑的 .bat**，或面板上的一个按钮。

B 机常用位置：日志 `data\logs\watchdog.log`、
更新用 `python host\deploy\update.py`（或让用户双击 `launch\更新平台.bat`）。
