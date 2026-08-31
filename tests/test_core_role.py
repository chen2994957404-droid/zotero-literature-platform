# -*- coding: utf-8 -*-
"""shared.kernel.role 的单元测试 —— 机器角色守卫。

这道闸挡的是**真实数据被污染**：两台机器共用同一个 Zotero 账号，
编程端一旦回写，改的就是用户的真实文献库，而且立刻同步到主力机。
所以这里的重点不是「函数能不能跑」，是**默认行为必须站在安全那一侧**。
"""
import pytest

from shared.kernel import errors, role


@pytest.fixture
def as_role(monkeypatch):
    """把本机角色临时改成指定值（不碰真实 .env）。"""
    def _set(value):
        monkeypatch.setattr(role, 'current', lambda: value)
        monkeypatch.setattr(role, 'is_configured', lambda: value in role.VALID)
    return _set


class TestDefault:
    def test_未设置时按dev处理(self, monkeypatch):
        """两种默认的代价不对称：默认 prod 会让编程端静默污染真实数据，
        默认 dev 只会让主力机响亮地拒绝一次。所以必须默认 dev。"""
        monkeypatch.setattr('shared.kernel.config.get_site', lambda name: '')
        assert role.current() == role.DEV

    @pytest.mark.parametrize('bad', ['production', '主力机', 'true', '1', 'PRD'])
    def test_值非法时也按dev处理(self, monkeypatch, bad):
        """写错值不能变成「放行」—— 那是最危险的失败方式。"""
        monkeypatch.setattr('shared.kernel.config.get_site', lambda name: bad if name == 'ROLE' else '')
        assert role.current() == role.DEV

    def test_读配置抛异常时仍按dev处理(self, monkeypatch):
        def boom(name):
            raise RuntimeError('凭据库炸了')
        monkeypatch.setattr('shared.kernel.config.get_site', boom)
        assert role.current() == role.DEV

    def test_大小写和空白不影响识别(self, monkeypatch):
        monkeypatch.setattr('shared.kernel.config.get_site', lambda name: '  PROD \n')
        assert role.current() == role.PROD


class TestRequireProd:
    def test_运行端放行(self, as_role):
        as_role(role.PROD)
        role.require_prod('写回 Zotero')        # 不抛异常即通过

    def test_编程端拦截(self, as_role):
        as_role(role.DEV)
        with pytest.raises(errors.WrongMachineError):
            role.require_prod('写回 Zotero')

    def test_报错里要说清是什么操作和怎么办(self, as_role):
        """报错最终是给一个不懂编程的人看的，必须能自解。"""
        as_role(role.DEV)
        with pytest.raises(errors.WrongMachineError) as e:
            role.require_prod('删除 Zotero 条目')
        msg = str(e.value)
        assert '删除 Zotero 条目' in msg          # 是什么操作
        assert '控制面板' in msg                   # 怎么改
        assert '--force' in msg                    # 怎么越过
        assert '两台机器的分工' in msg              # 去哪看详情

    def test_force可以越过(self, as_role, capsys):
        as_role(role.DEV)
        role.require_prod('写回 Zotero', force=True)
        assert '--force' in capsys.readouterr().out, '越过时必须留一行警告，不能悄悄放行'

    def test_没配过角色时报错要点出这一点(self, monkeypatch):
        monkeypatch.setattr(role, 'current', lambda: role.DEV)
        monkeypatch.setattr(role, 'is_configured', lambda: False)
        with pytest.raises(errors.WrongMachineError) as e:
            role.require_prod('全库重抽')
        assert '没设置角色' in str(e.value)


class TestClassification:
    def test_归入不可重试(self):
        """换台机器才能解决的事，重试一万次也没用。"""
        assert not errors.is_retryable(errors.WrongMachineError('x'))

    def test_归在平台异常之下(self):
        assert issubclass(errors.WrongMachineError, errors.PlatformError)


class TestConfigured:
    def test_吃默认值不算配过(self, monkeypatch):
        """get_site 会把内置默认值 'dev' 一起返回，
        用它判断就永远分不清「配成了 dev」和「压根没配」。"""
        monkeypatch.setattr('shared.kernel.config.get_key',
                            lambda name, default='': default)
        assert role.is_configured() is False

    def test_显式配过才算(self, monkeypatch):
        monkeypatch.setattr('shared.kernel.config.get_key',
                            lambda name, default='': 'prod' if name == 'ROLE' else default)
        assert role.is_configured() is True


def test_角色名给人看的是中文(as_role):
    as_role(role.DEV)
    assert '编程端' in role.label()
    as_role(role.PROD)
    assert '运行端' in role.label()


class TestTestRole:
    """test 档：编程端接测试 Zotero 账号（2026-08-27 加）。

    这一档的要害是：**放行的条件不是「角色写着 test」，而是「写回目标确实是测试库」**。
    角色是人填的一个字，指着哪个库才是客观事实 —— 闸门要挡在事实那一侧。
    """

    @pytest.fixture
    def site(self, monkeypatch):
        """伪造本机设置（不碰真实 .env / 凭据库）。"""
        cfg = {}

        def _set(**kw):
            cfg.clear()
            cfg.update(kw)
            monkeypatch.setattr('shared.kernel.config.get_site', lambda name: cfg.get(name, ''))
        return _set

    def test_目标是测试库才放行(self, as_role, site):
        as_role(role.TEST)
        site(ZOTERO_TEST_USER_ID='88888888', ZOTERO_WEB_USER_ID='88888888')
        role.require_prod('写回 Zotero')          # 不抛即通过

    def test_写回目标不是测试库就拒绝(self, as_role, site):
        """最要防的那一下：配置切回真实账号，角色却还写着 test。"""
        as_role(role.TEST)
        site(ZOTERO_TEST_USER_ID='88888888', ZOTERO_WEB_USER_ID='12345')
        with pytest.raises(errors.WrongMachineError) as e:
            role.require_prod('写回 Zotero')
        assert '不是测试库' in str(e.value)

    def test_没填测试账号id时一律拒绝(self, as_role, site):
        """留空不能等于「随便写」—— 空配置必须落在安全那一侧。"""
        as_role(role.TEST)
        site(ZOTERO_WEB_USER_ID='12345')
        with pytest.raises(errors.WrongMachineError):
            role.require_prod('写回 Zotero')

    def test_两个都空也拒绝(self, as_role, site):
        as_role(role.TEST)
        site()
        assert role.test_library_ok() is False
        with pytest.raises(errors.WrongMachineError):
            role.require_prod('写回 Zotero')

    def test_test不是dev也不是prod(self, as_role):
        as_role(role.TEST)
        assert role.is_test() and not role.is_dev() and not role.is_prod()

    def test_角色名要看得出是测试库(self, as_role):
        as_role(role.TEST)
        assert '测试' in role.label()


class TestWebUserId:
    """写 zotero.org 的 id 与本地 API 的 id 不是一回事（拆分于 2026-08-27）。"""

    def test_没单独配时沿用旧值(self, monkeypatch):
        monkeypatch.setattr('shared.kernel.config.get_site',
                            lambda n: '12345' if n == 'ZOTERO_USER_ID' else '')
        from shared.kernel.config import web_user_id
        assert web_user_id() == '12345'

    def test_配了就以它为准(self, monkeypatch):
        vals = {'ZOTERO_USER_ID': '0', 'ZOTERO_WEB_USER_ID': '12345'}
        monkeypatch.setattr('shared.kernel.config.get_site', lambda n: vals.get(n, ''))
        from shared.kernel.config import web_user_id
        assert web_user_id() == '12345'
