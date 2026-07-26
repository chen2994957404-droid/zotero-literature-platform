# -*- coding: utf-8 -*-
"""config · 配置/密钥加载基础件（公理：统一、可靠地拿到密钥）

解决的真实问题（踩坑 #17/#19 反复出现三次）：
密钥只放环境变量时，setx 设的值**只对之后新建的进程生效**，长驻进程/子进程常拿不到，
导致 401、"未设置 MINERU_TOKEN" 等静默失败。

加载顺序（后者不覆盖前者）：
  1. 进程环境变量（os.environ）—— 优先，便于临时覆盖
  2. 项目根目录的 .env 文件 —— 兜底，保证任何启动方式都能拿到

用法：
    from modules.config import get_key
    key = get_key('DEEPSEEK_KEY')            # 拿不到返回 ''
    key = get_key('DEEPSEEK_KEY', required=True)   # 拿不到直接报错，避免静默失败

.env 格式（该文件已在 .gitignore，不进版本库）：
    DEEPSEEK_KEY=sk-xxx
    ZOTERO_API_KEY=xxx
    MINERU_TOKEN=sk-xxx
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_FILE = os.path.join(ROOT, '.env')

_cache = None


def _load_env_file():
    """读 .env（KEY=value，支持 # 注释、去引号）。文件不存在返回空 dict。"""
    data = {}
    if not os.path.exists(ENV_FILE):
        return data
    try:
        with open(ENV_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return data


def get_key(name, required=False, default=''):
    """取配置：先环境变量，再 .env 文件。required=True 时拿不到直接报错。"""
    global _cache
    v = os.environ.get(name, '')
    if not v:
        if _cache is None:
            _cache = _load_env_file()
        v = _cache.get(name, '')
    if not v:
        if required:
            raise RuntimeError(
                f'缺少配置 {name}。请任选其一：\n'
                f'  1) 设环境变量：setx {name} "你的密钥"（需重开终端/重启进程）\n'
                f'  2) 在项目根目录 .env 里写：{name}=你的密钥（推荐，任何启动方式都生效）')
        return default
    return v


def all_keys():
    """当前可用的配置键（用于自检，不返回值本身）。"""
    global _cache
    if _cache is None:
        _cache = _load_env_file()
    names = set(_cache.keys())
    for n in ('DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN', 'SILICONFLOW_KEY'):
        if os.environ.get(n):
            names.add(n)
    return sorted(names)
