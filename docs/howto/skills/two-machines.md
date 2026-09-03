---
name: two-machines
description: 涉及写回 Zotero、跑花钱的批量作业、起常驻服务（`host/watcher/`）、部署代码到主力机、连 B 机排查、或需要知道 B 机真实状态时读这份。A/B 两台机器的分工与硬约束、ROLE 三档（dev/test/prod）各自允许什么、SSH 连 B 的正确姿势与它的两个陷阱、以及「部署≠换文件」的重启纪律。
---

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
| Zotero 桌面 | 已装，平时不常开 | **常开**（本地 API 要它） |
| 项目路径 | `D:\dev\zotero-literature-platform` | `D:\02_AI\Projects\zotero-literature-platform` |
| `data/`（五层） | 测试账号自产的几篇 | **权威副本** |
| 自启任务 | **一个都不注册** | 4 个：Watcher / Ollama / ZoteroApp / AutoSync |

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
| 写回 Zotero | 见下面 ROLE 三档 | ✅ |
| 花钱的批量作业 | ❌ | ✅ |

## 三、⚠ ROLE 三档 —— 别再照旧文档说「A 机一律不许写」

`shared/kernel/role.py` + `.env` 里的 `ROLE`（控制面板「本机设置」第一项可改）。

- **`dev`（A 机，默认）**：拒绝写 Zotero / 起 watcher / 全库作业，除非显式 `--force`
- **`test`（A 机 + 独立测试 Zotero 账号，2026-08-27 加）**：**允许写、允许跑 watcher**。
  写坏了只坏在测试库里。解开的正是此前 A 机无法验证的那一半：
  标签状态机、附件回写与复用、版本冲突、watcher 端到端。
  而且**大多不花钱** —— 喂一份假 `summary.html` 就能走完整条回写链路。
- **`prod`（B 机）**：全部允许

「A 机不许写」「watcher 只能在 B」这两条的**根因都是「共用同一个 Zotero 账号」**。
账号不同就都不成立 —— `ROLE=test` 时别照字面拒绝用户。

**test 档的两层保护**：硬的是 A 机只持有测试账号的 key（凭据决定，不是纪律）；
软的是 `role.require_prod` 会核对 `ZOTERO_WEB_USER_ID == ZOTERO_TEST_USER_ID`，
对不上就拒绝 —— 挡的是「配置切回真实账号却忘了改角色」。

**换账号的血泪提醒**：要么新建 profile + 新数据目录，要么**先退出账号、再清空本地数据**。
顺序反了（登着旧账号做「重置」）可能把本地状态推上服务器，清空真实库并同步到 B。

## 四、连 B 机（A 能直接连了，2026-08-28）

```bash
python host/deploy/remote.py check     # ← 用这个，别手敲 ssh
```

它把三个用血换来的细节包好了：**用户名是 `Administrator` 不是计算机名**（踩坑 #74）、
中文要套 UTF-8 外壳、连不上时把「该往哪查、不该往哪查」直接打出来（踩坑 #97）。

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
python host/deploy/remote.py job --install        # 只做一次
python host/deploy/remote.py job "<PowerShell>"   # B 用自己的身份跑，密钥读得到
```

原理：它触发一个 `LogonType=Interactive` 的计划任务，那个会话跑在 `SessionId=1`，
凭据库正常可读（watcher 天天在花钱、在写 Zotero，就是活证据）。
实测拿到 35 位密钥并真调了一次 DeepSeek 补全。

| 要干的事 | 走哪条 |
|---|---|
| `git pull` / 装包 / pytest / 离线体检 / 读日志读数据 | `run`（更快，一条 ssh 就完） |
| 任何调付费 API 的、写 Zotero 的、要密钥的 | **`job`** |

所以「给用户一个 .bat 让他双击」不再是唯一出路 —— 但**大批量作业仍然先问用户**
（那是钱的量级问题，不是能力问题）。⚠ 这条通道一次只跑一个作业。

### ⚠ 陷阱 2：远程 `git pull` 之后，B 上跑的还是旧代码
面板和 watcher 是长驻进程，磁盘上代码换了它们照跑旧的（2026-08-28 咬过：
给用户加了按钮，用户在面板上**根本看不到**；而 `launch/控制面板.bat` 检测到面板还活着
只开浏览器**不会重启它**，所以「关窗口再双击」也没用）。

远程 pull 之后二选一：让用户双击一次 `launch/更新平台.bat`，或者自己停掉面板 ——
```bash
$p=(Get-NetTCPConnection -LocalPort 8777 -State Listen).OwningProcess; Stop-Process -Id $p -Force
```
watcher 由计划任务托管，`Stop-ScheduledTask` + `Start-ScheduledTask`。
注意它是**孙子进程**（踩坑 #62），重启计划任务不一定换得掉。

## 五、B 机的状态怎么让你看见

这是本方案最大的摩擦。除了 SSH（受上面两个陷阱限制），
其余靠**用户把诊断报告贴给你**。

**给用户的东西不能是「要敲命令的工具」** —— 他不懂编程。
凡是要他在 B 机上做的事，做成**双击就能跑的 .bat**，或面板上的一个按钮。

B 机常用位置：日志 `data\logs\zotero_watcher.log`、
更新用 `python host\deploy\update.py`（或让用户双击 `launch\更新平台.bat`）。
