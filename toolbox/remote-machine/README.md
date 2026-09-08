# remote-machine · 从这台机器操作另一台 Windows

**一台机器改代码，另一台机器干活。** 这个仓库装的就是「怎么隔空指挥那一台」——
跟任何具体项目都无关，配一次，所有项目都能用。

原本它长在一个文献科研平台里，但里面攒下的东西没有一条跟文献有关：
连不上时该往哪查、为什么 SSH 里读不到密钥、为什么「更新了代码」不等于「新代码生效了」。
所以拆出来单过。

## 装（两步，一次性）

```bash
python install.py
```

把「怎么操作另一台机器」这份说明装到 `~/.claude/skills/remote-machine/`，
**之后在任何项目里，Claude Code 都能直接用**。

然后照着 `machines.example.toml` 抄一份到 `~/.remote-machine/machines.toml`，
填上地址、账号、私钥路径。**这份配置在仓库之外**，不会被提交上去。

## 用

```bash
python remote.py check                # 连得上吗、是谁、代码到哪一版、任务活着没
python remote.py logs                 # 看日志尾部
python remote.py run "<PowerShell>"   # 跑一条只读命令
python remote.py deploy               # 上线：跑对面项目自己的上线脚本
python remote.py job "<PowerShell>"   # 让对面用自己的身份跑（**能读密钥**）
python remote.py push a.ps1 tmp/a.ps1 # 传个脚本过去
python remote.py --machine other ...  # 操作另一台
```

**在哪个项目目录里跑，就自动选中那台机器**（按配置里的 `local` 匹配）。
不用装任何第三方库，Python 3.11+ 即可（用到 `tomllib`）。

## 三件它替你记着的事

1. **用户名是账号，不是计算机名。** 填错时 sshd 只回 `Permission denied (publickey,...)`
   —— 这句话对「账号不存在」和「公钥不对」是同一句，在本机怎么查都查不出来，
   能白查两轮密钥。
2. **中文要套 UTF-8 外壳**，而且编码会在**四个**地方分别咬人：控制台输出、
   Python 子进程、`Get-Content` 读文件、PowerShell 读 `.ps1` 脚本自身（要 BOM）。
3. **连不上时，把「该往哪查、不该往哪查」直接打出来。** 几种失败在本机看起来一模一样，
   根因却完全不同 —— 分错方向的诊断比没有诊断更贵。

## 几个陷阱（都是实测出来的，不是推断）

- **SSH 会话里读不到 Windows 凭据库。** 公钥登录建立的是*网络登录会话*，
  凭据管理器在这种会话里整个打不开。所以要密钥的作业从 `run` 发起会**跑到一半才废**。
  → 用 `job` 通道：它触发一个 `LogonType=Interactive` 的计划任务，那个会话读得到。
- **部署 ≠ 把文件换掉。** 常驻进程在代码被换掉之后照跑旧的，且**看不出来**。
  → 用 `deploy`，它跑的是项目自己的上线脚本（只有它知道该重启谁）。

## 测试

```bash
python -m pytest tests -q
```

全部离线，不连任何机器。测的主要是「几种失败分得开吗」——
这个工具存在的一半理由就在那儿。

## 传文件走不通时

内网穿透/端口映射那类通道**转发得了 ssh、扛不住 scp**（实测：同一时刻 ssh 正常、
scp 连着六次死在 banner exchange）。`push` 会先挨个地址试 scp，
全失败再改走 base64 经普通 ssh 直传。小文件够用，大文件仍需要一条能走 scp 的路。
