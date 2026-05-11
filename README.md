# StandAlone LLM Agent

完全オフライン環境で動作する Claude Code ライクな AI エージェント。
ローカル LLM（Ollama）を使い、ファイル操作・シェル実行・コード検索などのツールを
ReAct ループで繰り返し呼び出しながら複雑なタスクを自律的に解決します。

## 特徴

- **完全オフライン** — インターネット接続不要
- **ReAct ループ** — Think → Act → Observe を繰り返して複雑なタスクを解決
- **拡張可能なツール** — `@tool` デコレータで簡単に追加可能
- **Windows / Mac / Linux 対応** — PowerShell / bash を自動切り替え
- **Ollama / LAN サーバー対応** — `base_url` を変えるだけで切り替え
- **複数行プロンプト入力** — Shift+Enter で改行、Enter で送信
- **会話の継続** — 追加プロンプトで生成したアプリをそのまま修正可能
- **自動実行モード** — Shift+Tab でトグル。確認プロンプトをスキップして全ツールを自動実行
- **権限確認プロンプト** — シェル実行・ファイル書き込みの前に確認を求められる（自動実行モード OFF 時）

## 必要環境

- Python 3.11 以上
- [Ollama](https://ollama.com) （同一マシンまたは LAN 内のサーバー）

## セットアップ

```bash
# 1. リポジトリのクローン
git clone <repo-url>
cd StandAloneLlmAgent

# 2. 仮想環境の作成と依存パッケージのインストール
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt

# Mac / Linux
.venv/bin/pip install -r requirements.txt

# 3. Ollama のインストールとモデルの取得
ollama pull qwen2.5-coder:7b   # 推奨（コーディング特化、Function Calling 対応）

# 4. PATH に追加（一度だけ）― どこからでも agent コマンドで起動できるようにする
#
# Windows: システム環境変数の Path にプロジェクトディレクトリを追加
#   例: C:\Users\yourname\work\StandAloneLlmAgent
#   追加後、新しいターミナルを開くと有効になる
#
# Mac / Linux: ~/.bashrc または ~/.zshrc に追記
#   export PATH="$HOME/path/to/StandAloneLlmAgent:$PATH"
#   追記後: source ~/.bashrc  （または新しいターミナルを開く）
#   chmod +x ~/path/to/StandAloneLlmAgent/agent.sh
```

## 起動方法

```bash
# Ollama を起動（別ターミナルで）
ollama serve

# どこからでも起動（PATH 設定済みの場合）
agent          # Windows
./agent.sh     # Mac / Linux（PATH 未設定の場合）

# PATH 未設定の場合はプロジェクトディレクトリから
python -m cli.app
```

```
╔══════════════════════════════════════════╗
║  StandAlone LLM Agent  [qwen2.5-coder:7b] ║
╚══════════════════════════════════════════╝

Enter で送信  Shift+Enter で改行  Shift+Tab で自動実行モード切替
追加プロンプトで生成したアプリを修正可能  '/reset' でリセット  'exit' で終了

> このディレクトリの Python ファイルを一覧して   ← Enter で送信
  ● glob(pattern='**/*.py', path='.')
  │ agent/__init__.py
  │ agent/core.py
  │ ...

> さっき作ったアプリにエラーハンドリングを追加して  ← 会話を継続して修正

[AUTO] > Shift+Tab を押すと自動実行モードに切り替わる（確認なし）

> /reset     ← 会話をリセット
> exit       ← 終了
```

## 設定

`settings.yaml` を編集して動作をカスタマイズできます。

```yaml
backend: ollama

ollama:
  # ローカル:     http://localhost:11434
  # LAN サーバー: http://192.168.1.100:11434
  base_url: http://localhost:11434
  model: qwen2.5-coder:7b
  temperature: 0.2
  context_window: 32768

agent:
  max_steps: 30         # 1 タスクあたりの最大ツール呼び出し回数

permissions:
  require_confirm_before_write: true   # write_file / edit_file 前に確認
  require_confirm_before_shell: false  # bash 前に確認（true にすると有効）
```

### 推奨モデル

| モデル | 提供元 | 用途 | VRAM | Tool Calling |
|---|---|---|---|---|
| `mistral-nemo:12b` | Mistral AI / NVIDIA（仏・米） | 汎用・デフォルト（推奨） | 8 GB | ◎ |
| `llama3.1:8b` | Meta（米） | 汎用・軽量代替 | 6 GB | ○ |
| `mistral:7b` | Mistral AI（仏） | 軽量（ツール呼び出し不安定） | 6 GB | △ |
| `phi4:14b` | Microsoft（米） | 高精度（tools API 非対応） | 10 GB | × |
| `qwen2.5-coder:7b` | Alibaba（中） | コーディング特化 | 6 GB | ◎ |

> **Tool Calling について**: このエージェントはツール呼び出し（Function Calling）に依存しています。
> `mistral-nemo:12b` が非中国製モデルで最も安定しており推奨です。
> `phi4:14b` は Ollama の tools API に非対応のため動作しません。

## 組み込みツール

| ツール | 説明 |
|---|---|
| `read_file` | ファイルを行番号付きで読み込む |
| `write_file` | ファイルを新規作成または上書き |
| `edit_file` | ファイル内の文字列を置換（`replace_all=true` で全箇所置換） |
| `list_dir` | ディレクトリ内容を一覧表示 |
| `glob` | glob パターンでファイルを検索 |
| `grep` | 正規表現でファイル内容を検索 |
| `bash` | シェルコマンドを実行（Windows: PowerShell） |
| `task_done` | タスク完了を宣言してループを終了 |

## カスタムツールの追加

`tools/` 以下に新しいファイルを作り `@tool` デコレータで定義します。

```python
# tools/my_tools.py
from tools.registry import tool

@tool(name="fetch_url", description="URL からテキストを取得する")
def fetch_url(url: str) -> str:
    """url: 取得する URL"""
    import urllib.request
    with urllib.request.urlopen(url) as r:
        return r.read().decode()
```

`tools/__init__.py` に `import tools.my_tools` を追加すれば自動登録されます。

## 開発

```bash
# ユニットテスト（Ollama 不要）
python -m pytest tests/ --ignore=tests/test_integration.py -v

# 結合テスト（Ollama 起動が必要）
python -m pytest tests/test_integration.py -v

# 結合テストのみを選択実行
python -m pytest -m integration -v

# 手動評価スクリプト（全出力を目視確認）
python scripts/eval_agent.py
python scripts/eval_agent.py --cases "fizzbuzz,edit"   # テストケースを絞り込む
```

## アーキテクチャ

```
cli/app.py          — エントリポイント・rich UI・権限確認プロンプト
agent/core.py       — ReAct ループ・on_confirm コールバック
agent/context.py    — スライディングウィンドウ式コンテキスト管理
backends/ollama.py  — Ollama HTTP バックエンド（<tool_call> 3段階フォールバック付き）
tools/registry.py   — @tool デコレータ・ToolDispatcher
tools/filesystem.py — ファイル操作ツール
tools/shell.py      — シェル実行ツール（cd 追跡付き）
tools/search.py     — grep ツール
config/settings.py  — settings.yaml の読み込み
scripts/eval_agent.py — 手動評価スクリプト
```

## ロードマップ

- **Phase 1 (完了)** — Ollama バックエンド・基本ツール・ReAct ループ・CLI
- **Phase 2 (完了)** — ストリーミング表示・権限確認プロンプト・`edit_file` の `replace_all` 対応・統合テスト・複数行入力・自動実行モード（Shift+Tab）
- **Phase 3** — llama-cpp-python バックエンド・要約ベースのコンテキスト圧縮・MLX バックエンド・セッション保存

## ライセンス

MIT
