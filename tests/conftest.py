import pytest


@pytest.fixture
def clean_registry():
    """テスト間でグローバルなツールレジストリを隔離する。"""
    import tools.registry as m
    saved = dict(m._registry)
    yield
    m._registry.clear()
    m._registry.update(saved)
