# -*- coding: utf-8 -*-
"""shared.kernel.log 与 shared.kernel.errors 的单元测试 —— 纯离线。"""
import logging.handlers
import os

import pytest

from shared.kernel import errors, paths
from shared.kernel.log import Log, get_logger


# ══════════════════════════════════════════════════════════════════════
# shared.kernel.errors
# ══════════════════════════════════════════════════════════════════════
class TestErrorTaxonomy:
    """分类的唯一目的是让调用方能决定「该拿它怎么办」，所以只测这一点。"""

    @pytest.mark.parametrize('exc', [
        errors.ExternalServiceError('MineRU 超时', service='mineru'),
        errors.ServiceUnavailable('Ollama 没跑', service='ollama'),
        errors.RateLimited('限流', service='mineru', retry_after=30),
    ])
    def test_外部服务故障可重试(self, exc):
        assert errors.is_retryable(exc) is True

    @pytest.mark.parametrize('exc', [
        errors.BadInputError('key 不合法'),
        errors.ConfigError('没配密钥'),
        errors.DataError('full.md 不见了'),
        errors.AuthError('密钥过期'),
        ValueError('随便一个别的错'),
        RuntimeError('完全没见过的错'),
    ])
    def test_其余一律不重试(self, exc):
        assert errors.is_retryable(exc) is False

    def test_认证失败不算可重试(self):
        """密钥不对属于外部服务的问题，但重试一万次也不会好。"""
        assert not errors.is_retryable(errors.AuthError('key 无效'))

    def test_限流带建议等待时间(self):
        assert errors.retry_after(errors.RateLimited('x', retry_after=30)) == 30
        assert errors.retry_after(errors.ExternalServiceError('x'), default=5) == 5
        assert errors.retry_after(ValueError('x'), default=5) == 5

    def test_都归在同一个祖先下(self):
        for cls in (errors.BadInputError, errors.ConfigError, errors.DataError,
                    errors.AuthError, errors.ExternalServiceError,
                    errors.ServiceUnavailable, errors.RateLimited):
            assert issubclass(cls, errors.PlatformError), cls.__name__

    def test_BadInput仍是ValueError(self):
        """旧代码里到处是 except ValueError，不能因为分类而接不住了。"""
        assert issubclass(errors.BadInputError, ValueError)

    def test_非法key抛的是可分类的异常(self):
        with pytest.raises(errors.BadInputError):
            paths.check_key('不是key')
        assert not errors.is_retryable(paths.BadKeyError('x'))

    def test_服务名被带上(self):
        e = errors.RateLimited('限流', service='mineru', retry_after=12)
        assert e.service == 'mineru' and e.retry_after == 12


# ══════════════════════════════════════════════════════════════════════
# shared.kernel.log
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture
def tmp_logger(tmp_path, monkeypatch):
    """把日志目录指到临时目录，避免污染真实 data/logs。"""
    monkeypatch.setattr(paths, 'LOGS', str(tmp_path))
    monkeypatch.setattr(paths, 'log', lambda name, create_dir=True: str(tmp_path / (name + '.log')))
    lg = Log('测试日志', to_stdout=False)
    yield lg
    for h in list(lg._logger.handlers):
        h.close()
        lg._logger.removeHandler(h)


class TestLog:
    def test_像print一样调用(self, tmp_logger, tmp_path):
        tmp_logger('开始处理', '2T6H4S3D')
        content = (tmp_path / '测试日志.log').read_text(encoding='utf-8')
        assert '开始处理 2T6H4S3D' in content

    def test_每行带时间戳(self, tmp_logger, tmp_path):
        import re
        tmp_logger('一条消息')
        line = (tmp_path / '测试日志.log').read_text(encoding='utf-8').strip()
        assert re.match(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] 一条消息$', line), line

    def test_中文不乱码(self, tmp_logger, tmp_path):
        tmp_logger('聚硼硅氧烷 · 动态键')
        assert '聚硼硅氧烷 · 动态键' in (tmp_path / '测试日志.log').read_text(encoding='utf-8')

    def test_警告与错误有标记(self, tmp_logger, tmp_path):
        tmp_logger.warn('找不到 PDF')
        tmp_logger.error('MineRU 失败')
        content = (tmp_path / '测试日志.log').read_text(encoding='utf-8')
        assert '⚠ 找不到 PDF' in content
        assert '✗ MineRU 失败' in content

    def test_吃掉print的flush参数(self, tmp_logger):
        """老代码里有 print(..., flush=True)，替换后不能因此报错。"""
        tmp_logger('消息', flush=True)

    def test_写盘失败不能让主流程崩(self, tmp_logger, monkeypatch):
        def boom(*a, **k):
            raise OSError('磁盘满了')
        monkeypatch.setattr(tmp_logger._logger, 'log', boom)
        tmp_logger('这条写不进去')      # 不抛异常即通过

    def test_同名复用同一个日志器不重复挂handler(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, 'LOGS', str(tmp_path))
        monkeypatch.setattr(paths, 'log', lambda n, create_dir=True: str(tmp_path / (n + '.log')))
        a = get_logger('复用测试', to_stdout=False)
        b = get_logger('复用测试', to_stdout=False)
        assert a is b
        n = len(a._logger.handlers)
        get_logger('复用测试', to_stdout=False)
        assert len(a._logger.handlers) == n, '重复 get_logger 把 handler 挂重了，日志会写两遍'
        for h in list(a._logger.handlers):
            h.close(); a._logger.removeHandler(h)

    def test_会轮转不会无限长(self, tmp_logger):
        """常驻服务的日志此前只会一直长下去，这是引入 shared.kernel.log 的原因之一。"""
        fh = [h for h in tmp_logger._logger.handlers
              if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert fh, '没挂轮转 handler'
        assert fh[0].maxBytes > 0 and fh[0].backupCount > 0

    def test_知道自己写在哪(self, tmp_logger, tmp_path):
        assert tmp_logger.path == str(tmp_path / '测试日志.log')
