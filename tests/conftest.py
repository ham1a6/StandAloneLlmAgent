import pytest


@pytest.fixture
def clean_registry():
    """テスト間でグローバルなツールレジストリを隔離する。"""
    import tools.registry as m
    saved = dict(m._registry)
    yield
    m._registry.clear()
    m._registry.update(saved)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """tmp_path を os.getcwd() と tools.shell._cwd の両方に設定する。

    write_file は Path(relative) → os.getcwd() 相対で解決する。
    bash は tools.shell._cwd を使う。
    両者を揃えないと bash の実行ディレクトリとファイル生成先がずれる。
    """
    import tools.shell as _shell
    monkeypatch.chdir(tmp_path)
    _shell._set_cwd(str(tmp_path))
    yield tmp_path
    # モジュール変数を元に戻す（他テストへの漏れ防止）
    import os
    _shell._set_cwd(os.getcwd())
