# スタンドアロン LLM Agent 設計書

## 1. 概要

完全オフライン環境で動作する Claude Code ライクな AI エージェント。
ローカル LLM を使用し、ファイル操作・シェル実行・コード解析などのツールを
ReAct ループで繰り返し呼び出しながら複雑なタスクを自律的に解決する。

## 2. 目標・非目標

### 目標
- インターネット接続なしで完全動作
- ツール呼び出し（Function Calling）によるコード・ファイル操作
- 複数ターンの会話と文脈保持
- CLI から対話的に使用可能
- 拡張可能なツールシステム

### 非目標
- クラウド LLM との互換性維持
- Web ブラウザ UI
- マルチユーザー対応

---

## 3. アーキテクチャ

```
┌─────────────────────────────────────────────────────┐
│                    CLI Interface                     │
│       (入力・出力・ストリーミング・権限確認UI)         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   Agent Core                         │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ Context     │  │  ReAct Loop  │  │  Tool      │  │
│  │ Manager     │◄─►  (Think→Act  │◄─►  Dispatcher│  │
│  │             │  │  →Observe)   │  │            │  │
│  └─────────────┘  └──────────────┘  └─────┬──────┘  │
└──────────────────────────────────────────-│─────────┘
                                            │
              ┌─────────────────────────────┼──────────────────────────┐
              │                             │                          │
┌─────────────▼──────┐        ┌────────────▼────────┐   ┌────────────▼──────┐
│   LLM Backend      │        │    Tool Registry     │   │  Config Manager   │
│  (Ollama)          │        │  ┌───────────────┐   │   │  settings.yaml    │
│                    │        │  │ FileSystem    │   │   └───────────────────┘
│  - モデル管理      │        │  │ Shell         │   │
│  - プロンプト変換  │        │  │ SearchGrep    │   │
│  - ストリーミング  │        │  │ (拡張可能)    │   │
└────────────────────┘        │  └───────────────┘   │
                              └─────────────────────-─┘
```

---

## 4. コンポーネント詳細

### 4.1 LLM Backend

ローカル LLM とのインタフェース層。複数バックエンドを抽象化する。

| バックエンド | 状態 | Function Calling |
|---|---|---|
| Ollama | 実装済み | ネイティブ + `<tool_call>` フォールバック |
| llama.cpp (llama-cpp-python) | Phase 3 予定 | GGUF モデル + grammar |
| MLX (Apple Silicon) | Phase 3 予定 | MLX-LM 経由 |

**抽象インタフェース:**
```python
class LLMBackend(ABC):
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ChatResponse: ...

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> ChatResponse: ...  # デフォルト実装は chat() に委譲
```

**推奨モデル:**
- Qwen2.5-Coder-7B / 14B（コーディング特化、Function Calling 対応）
- DeepSeek-Coder-V2-Lite（コーディング、軽量）

> **注意**: `llama3.1:8b` は Ollama の Function Calling API に非対応のため、
> このエージェントでは正常に動作しない。`qwen2.5-coder` 系を推奨する。

### 4.2 Tool System

ツールは `@tool` デコレータで定義し、JSON Schema を自動生成する。

```python
@tool(name="read_file", description="Read a file with line numbers")
def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    ...

@tool(name="bash", description="Run a shell command")
def bash(command: str, timeout: int = 60) -> str:
    ...
```

**組み込みツール一覧:**

| ツール名 | 説明 |
|---|---|
| `read_file` | ファイル読み込み (行番号付き) |
| `write_file` | ファイル書き込み |
| `edit_file` | 文字列置換（デフォルトは一意な1箇所、`replace_all=true` で全箇所） |
| `list_dir` | ディレクトリ一覧 |
| `glob` | glob パターンでファイル検索 |
| `grep` | 正規表現でコード検索 |
| `bash` | シェルコマンド実行（Windows: PowerShell、cd は次の呼び出しに引き継がれる） |
| `task_done` | タスク完了を宣言しループを終了 |

### 4.3 Agent Core (ReAct ループ)

```
while not done:
    1. [Think]   LLM にメッセージ + ツール定義を送信
    2. [Confirm] on_confirm が設定されていれば各ツール呼び出しをユーザーに確認
    3. [Act]     承認されたツールを実行（拒否されたものは "Cancelled by user." をコンテキストへ）
    4. [Observe] 実行結果をコンテキストに追加
    5. done = LLM が task_done を呼んだ or 最大ステップ超過
```

```python
class Agent:
    max_steps: int = 30           # 無限ループ防止
    context: ContextManager
    backend: LLMBackend
    dispatcher: ToolDispatcher
    on_tool_call: Callable[[str, dict], None] | None   # ツール呼び出し通知
    on_tool_result: Callable[[str, str], None] | None  # ツール結果通知
    on_confirm: Callable[[str, dict], bool] | None     # 実行前確認（False でキャンセル）

    def run(
        self,
        user_prompt: str,
        on_text_chunk: Callable[[str], None] | None = None,
    ) -> str: ...
```

**停止条件:**
- LLM が `task_done` ツールを呼び出す
- ツール呼び出しなしのテキスト応答（最終回答）
- `max_steps` 超過（エラーとして報告）

**`on_confirm` の動作:**
- `task_done` は確認対象外（常に実行）
- `False` を返すとそのツールはスキップされ `"Cancelled by user."` がコンテキストに入る
- エージェントはキャンセルを見て別の手段を試みるか、諦めてテキスト応答を返す

### 4.4 Context Manager

メッセージ数の上限を管理しながら会話履歴を保持する（スライディングウィンドウ）。

```python
class ContextManager:
    max_messages: int = 40        # 保持するメッセージ数の上限
```

**スライディングウィンドウ戦略:**
- System prompt + 最新 `max_messages` 件を保持
- 古いメッセージをメッセージ単位で切り捨てる

**要約戦略 (Phase 3):**
- 古い会話を LLM で要約してトークンを節約

### 4.5 CLI Interface

`rich` + `prompt_toolkit` を使ったターミナル UI。

**通常モード:**
```
╔══════════════════════════════════════════╗
║  StandAlone LLM Agent  [qwen2.5-coder:7b] ║
╚══════════════════════════════════════════╝

Enter で送信  Shift+Enter で改行  Shift+Tab で自動実行モード切替
追加プロンプトで生成したアプリを修正可能  '/reset' でリセット  'exit' で終了

> fizzbuzz.py を作成して実行して
  ● write_file(path='fizzbuzz.py', content='...')
  │ Written 120 chars to fizzbuzz.py

  ● bash(command='python fizzbuzz.py')
  │ 1
  │ 2
  │ Fizz
  │ ...

> さっきのスクリプトに引数で上限を指定できる機能を追加して  ← 追加プロンプトで修正
```

**自動実行モード（Shift+Tab で ON/OFF）:**
```
  ⚡ Edit automatically: ON  (確認なしで自動実行)

[AUTO] > tmp/ に家計簿アプリを作って
  ● write_file(path='tmp/models.py', ...)   ← 確認なしで即実行
  ...
```

**確認プロンプト（`require_confirm_before_shell: true` かつ自動実行 OFF 時）:**
```
  ● bash(command='rm -rf tmp/')
  ? bash: rm -rf tmp/
  実行しますか? [y/N]
```

**キーバインド一覧:**

| キー | 動作 |
|---|---|
| `Enter` | プロンプト送信 |
| `Shift+Enter` | 改行（複数行入力） |
| `Alt+Enter` | 改行（Shift+Enter が効かない環境でのフォールバック） |
| `Shift+Tab` | 自動実行モード ON/OFF 切替 |
| `Ctrl+C` | 入力キャンセル・終了 |

---

## 5. ディレクトリ構成

```
StandAloneLlmAgent/
├── agent/
│   ├── __init__.py
│   ├── core.py          # Agent クラス・ReAct ループ・on_confirm
│   ├── context.py       # ContextManager（スライディングウィンドウ）
│   ├── models.py        # Message, ToolSchema, ChatResponse など型定義
│   └── prompt.py        # System prompt テンプレート（英語）
├── backends/
│   ├── __init__.py
│   ├── base.py          # LLMBackend 抽象基底クラス
│   ├── ollama.py        # Ollama バックエンド（3段階フォールバック付き）
│   └── llamacpp.py      # llama-cpp-python バックエンド（Phase 3 予定・現在スタブ）
├── tools/
│   ├── __init__.py
│   ├── registry.py      # @tool デコレータ・ToolDispatcher
│   ├── builtin.py       # task_done ツール
│   ├── filesystem.py    # read_file, write_file, edit_file, glob, list_dir
│   ├── shell.py         # bash（cd 追跡・Windows/Unix 自動切り替え）
│   └── search.py        # grep
├── cli/
│   ├── __init__.py
│   └── app.py           # エントリポイント・rich UI・権限確認プロンプト
├── config/
│   ├── __init__.py
│   └── settings.py      # 設定読み込み（Pydantic）
├── tests/
│   ├── conftest.py      # workdir フィクスチャなど共通設定
│   ├── test_core.py
│   ├── test_confirm.py  # on_confirm の動作テスト
│   ├── test_filesystem.py
│   ├── test_shell.py
│   ├── test_ollama.py
│   ├── test_registry.py
│   ├── test_context.py
│   ├── test_models.py
│   ├── test_settings.py
│   ├── test_search.py
│   └── test_integration.py  # 結合テスト（Ollama 必要、@pytest.mark.integration）
├── scripts/
│   └── eval_agent.py    # 手動評価スクリプト（全出力を目視確認）
├── docs/
│   ├── DESIGN.md        # 設計書（本ファイル）
│   ├── TEST_SPEC.md     # テスト仕様書
│   └── TECHNICAL.md     # 技術解説
├── settings.yaml        # ユーザー設定ファイル
├── pyproject.toml
└── README.md
```

---

## 6. 設定ファイル (`settings.yaml`)

```yaml
backend: ollama               # ollama | llamacpp（llamacpp は Phase 3）

ollama:
  base_url: http://localhost:11434
  model: qwen2.5-coder:7b
  temperature: 0.2
  context_window: 32768

llamacpp:
  model_path: ./models/qwen2.5-coder-7b.Q4_K_M.gguf
  n_gpu_layers: -1            # -1 = すべて GPU に乗せる
  n_ctx: 32768
  temperature: 0.2

agent:
  max_steps: 30
  context_strategy: sliding   # sliding | summarize（summarize は Phase 3）

tools:
  shell:
    enabled: true
    timeout: 60               # 秒
    allowed_commands: []      # 空 = すべて許可

permissions:
  require_confirm_before_write: true   # write_file / edit_file 前に確認
  require_confirm_before_shell: false  # bash 前に確認
```

---

## 7. System Prompt 設計

System prompt は英語で記述する（日本語プロンプトはモデルを"説明モード"にしてツール呼び出しを妨げることがある）。

```
You are an autonomous agent. Complete every task by calling tools. Never write text explanations.

# Available tools
<tools>
{tool_schemas}
</tools>

# How to call a tool
You MUST use this exact format. Never output code blocks (```).

<tool_call>
{"name": "TOOL_NAME", "arguments": {"param": "value"}}
</tool_call>

# Rules
- To create or write a file → call write_file (forbidden to output code blocks)
- To run a multi-line script → ALWAYS write_file first, then bash to execute it.
  Never use `python -c "..."` for scripts longer than one line.
- To run a command → call bash
- When the task is complete → call task_done
- On error → read the output carefully, fix the root cause, then retry with a DIFFERENT approach.
  Never call the exact same tool with the exact same arguments again.
- Read files with read_file before editing them
- To rename a variable or symbol everywhere → use edit_file with replace_all=true
- After editing, verify changes were applied with read_file before calling task_done
- Multiple independent operations can be called at the same time

# Working directory
{cwd}

# Current datetime
{datetime}
```

---

## 8. 実装ロードマップ

### Phase 1 — MVP (完了)
- [x] `backends/ollama.py` — Ollama との HTTP 通信・ストリーミング
- [x] `tools/registry.py` — `@tool` デコレータと JSON Schema 生成
- [x] `tools/filesystem.py` — read_file, write_file, edit_file
- [x] `tools/shell.py` — bash 実行（cd 追跡、Windows/Unix 自動切り替え）
- [x] `agent/core.py` — ReAct ループ基本実装
- [x] `cli/app.py` — シンプルな REPL

### Phase 2 — 品質向上 (完了)
- [x] `agent/context.py` — メッセージ数管理・スライディングウィンドウ
- [x] `tools/search.py` — grep
- [x] ストリーミング表示（`on_text_chunk` コールバック）
- [x] 権限確認プロンプト（`on_confirm` コールバック、ファイル書き込み・シェル実行前）
- [x] `edit_file` の `replace_all` 対応（変数リネームなど）
- [x] テストスイート（ユニットテスト + 結合テスト）
- [x] 手動評価スクリプト (`scripts/eval_agent.py`)
- [x] 複数行プロンプト入力（Shift+Enter で改行、Enter で送信）
- [x] 自動実行モード（Shift+Tab でトグル、`on_confirm` をバイパス）
- [x] 会話継続による生成アプリの追加修正

### Phase 3 — 拡張
- [ ] `backends/llamacpp.py` — llama-cpp-python サポート
- [ ] 要約ベースのコンテキスト圧縮
- [ ] MLX バックエンド (Apple Silicon)
- [ ] カスタムツールプラグイン
- [ ] セッション保存・再開

---

## 9. 技術スタック

| 用途 | ライブラリ | バージョン |
|---|---|---|
| LLM (Ollama) | `httpx` (HTTP) | ≥0.27 |
| CLI UI | `rich` | ≥13 |
| 対話入力 | `prompt_toolkit` | ≥3.0 |
| 設定ファイル | `pyyaml` | ≥6 |
| 型定義 | `pydantic` | ≥2 |
| ビルド | `uv` + `pyproject.toml` | — |

Python バージョン: **3.11 以上**

---

## 10. Function Calling の実装方針

### Ollama（3段階フォールバック）

Ollama API は `/api/chat` エンドポイントで `tools` フィールドをサポートするが、
バージョンやモデルによって挙動が異なる。以下の優先順位で解析する。

1. **ネイティブ `tool_calls` フィールド** — 新しい Ollama バージョンで動作する OpenAI 互換形式
2. **`<tool_call>...</tool_call>` XML ブロック** — Qwen2.5 がデフォルトで使うトレーニング済み形式
   （Ollama 0.23.x では `tool_calls` フィールドへの変換が行われないため必須）
3. **JSON 単一行 / JSON オブジェクト全体** — その他モデルのフォールバック

また、Qwen2.5 のチャットテンプレートトークン（`<|im_start|>` など）がレスポンスの
`content` に漏れ込むケースがあるため、`_TEMPLATE_TOKEN_RE` で除去している。

### llama.cpp (Phase 3 予定)
`llama-cpp-python` は GBNF grammar を使って出力を JSON に強制できる。
ツールスキーマから grammar を生成し、確実に構造化出力を得る。

---

## 11. リスクと対策

| リスク | 対策 |
|---|---|
| LLM が無限ループする | `max_steps` で強制終了 |
| シェルコマンドで危険な操作 | `require_confirm_before_shell: true` + 確認プロンプト |
| コンテキスト超過 | スライディングウィンドウで古いメッセージを削除 |
| ツール呼び出し JSON パースエラー | エラーをコンテキストに戻し LLM に再試行させる |
| モデルが Function Calling 非対応 | `<tool_call>` XML 形式にフォールバック |
| モデルがコードブロックを出力してファイル作成しない | System prompt で明示的に禁止・`write_file` 使用を義務付け |
| `python -c "..."` で複数行スクリプトが SyntaxError | System prompt で `write_file` 後に `bash` するよう指示 |
