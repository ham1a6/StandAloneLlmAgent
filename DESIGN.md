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
│              (入力・出力・ストリーミング表示)           │
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
│  (Ollama / llama   │        │  ┌───────────────┐   │   │  settings.yaml    │
│   .cpp / MLX)      │        │  │ FileSystem    │   │   └───────────────────┘
│                    │        │  │ Shell         │   │
│  - モデル管理      │        │  │ CodeExecutor  │   │
│  - プロンプト変換  │        │  │ SearchGrep    │   │
│  - ストリーミング  │        │  │ (拡張可能)    │   │
└────────────────────┘        │  └───────────────┘   │
                              └─────────────────────-─┘
```

---

## 4. コンポーネント詳細

### 4.1 LLM Backend

ローカル LLM とのインタフェース層。複数バックエンドを抽象化する。

| バックエンド | 用途 | Function Calling |
|---|---|---|
| Ollama | 最も簡単なセットアップ | ネイティブ対応 (Llama 3.x, Qwen 2.5) |
| llama.cpp (llama-cpp-python) | GPU不要、軽量 | GGUF モデル + grammar |
| MLX (Apple Silicon) | Mac で高速 | MLX-LM 経由 |

**抽象インタフェース:**
```python
class LLMBackend(ABC):
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        stream: bool,
    ) -> ChatResponse | Iterator[ChatChunk]: ...
```

**推奨モデル:**
- Qwen2.5-Coder-7B / 14B (コーディング特化)
- Llama-3.1-8B (汎用)
- DeepSeek-Coder-V2-Lite (コーディング、軽量)

### 4.2 Tool System

ツールは `@tool` デコレータで定義し、JSON Schema を自動生成する。

```python
@tool(name="read_file", description="ファイルを読み込む")
def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    ...

@tool(name="bash", description="シェルコマンドを実行する")
def bash(command: str, timeout: int = 30) -> str:
    ...
```

**組み込みツール一覧:**

| ツール名 | 説明 |
|---|---|
| `read_file` | ファイル読み込み (行番号付き) |
| `write_file` | ファイル書き込み |
| `edit_file` | 差分ベースの文字列置換 |
| `list_dir` | ディレクトリ一覧 |
| `glob` | glob パターンでファイル検索 |
| `grep` | 正規表現でコード検索 |
| `bash` | シェルコマンド実行 |
| `task_done` | タスク完了を宣言しループを終了 |

### 4.3 Agent Core (ReAct ループ)

```
while not done:
    1. [Think]  LLM にメッセージ + ツール定義を送信
    2. [Act]    LLM がツール呼び出しを返す
    3. [Observe] ツールを実行し結果をコンテキストに追加
    4. done = LLM が task_done を呼んだ or 最大ステップ超過
```

```python
class Agent:
    max_steps: int = 30           # 無限ループ防止
    context: ContextManager
    backend: LLMBackend
    dispatcher: ToolDispatcher

    def run(self, user_prompt: str) -> str: ...
```

**停止条件:**
- LLM が `task_done` ツールを呼び出す
- ツール呼び出しなしのテキスト応答（最終回答）
- `max_steps` 超過（エラーとして報告）

### 4.4 Context Manager

トークン上限を管理しながら会話履歴を保持する。

```python
class ContextManager:
    max_tokens: int = 8192        # モデルの context window に合わせる
    strategy: "sliding" | "summarize"
```

**スライディングウィンドウ戦略:**
- System prompt + 最新 N メッセージを保持
- 古いメッセージを切り捨てる（シンプルで高速）

**要約戦略 (将来拡張):**
- 古い会話を LLM で要約してトークンを節約

### 4.5 CLI Interface

`rich` ライブラリを使ったターミナル UI。

```
╔══════════════════════════════════════╗
║  StandAlone LLM Agent  [Qwen2.5-7B] ║
╚══════════════════════════════════════╝

> ユーザー入力

[Thinking...]
[Tool: read_file("src/main.py")]
  → 42 lines read

[Tool: bash("python -m pytest")]
  → 3 passed, 1 failed

回答テキスト...

>
```

---

## 5. ディレクトリ構成

```
StandAloneLlmAgent/
├── agent/
│   ├── __init__.py
│   ├── core.py          # Agent クラス・ReAct ループ
│   ├── context.py       # ContextManager
│   ├── models.py        # Message, ToolSchema, ChatResponse など型定義
│   └── prompt.py        # System prompt テンプレート
├── backends/
│   ├── __init__.py
│   ├── base.py          # LLMBackend 抽象基底クラス
│   ├── ollama.py        # Ollama バックエンド
│   └── llamacpp.py      # llama-cpp-python バックエンド
├── tools/
│   ├── __init__.py
│   ├── registry.py      # @tool デコレータ・ToolDispatcher
│   ├── filesystem.py    # read_file, write_file, edit_file, glob, list_dir
│   ├── shell.py         # bash
│   └── search.py        # grep
├── cli/
│   ├── __init__.py
│   └── app.py           # エントリポイント・rich UI
├── config/
│   ├── __init__.py
│   └── settings.py      # 設定読み込み
├── settings.yaml        # ユーザー設定ファイル
├── pyproject.toml
└── README.md
```

---

## 6. 設定ファイル (`settings.yaml`)

```yaml
backend: ollama               # ollama | llamacpp

ollama:
  # Ollama は HTTP で通信するため、base_url を変えるだけでローカル・別サーバーを切り替えられる
  # ローカル動作 (同一マシン):  http://localhost:11434
  # LAN 内の別サーバー:         http://192.168.1.100:11434  ← インターネット不要
  # ※ クラウドサーバーはオフライン運用の対象外
  base_url: http://localhost:11434
  model: qwen2.5-coder:7b
  temperature: 0.2
  context_window: 32768

llamacpp:
  model_path: ./models/qwen2.5-coder-7b.Q4_K_M.gguf
  n_gpu_layers: -1            # -1 = すべてGPUに乗せる
  n_ctx: 32768
  temperature: 0.2

agent:
  max_steps: 30
  context_strategy: sliding   # sliding | summarize

tools:
  shell:
    enabled: true
    timeout: 60               # 秒
    allowed_commands: []      # 空 = すべて許可

permissions:
  require_confirm_before_write: true   # ファイル書き込み前に確認
  require_confirm_before_shell: false
```

---

## 7. System Prompt 設計

```
あなたは自律的に動作するAIアシスタントです。
ユーザーのタスクを解決するために、与えられたツールを繰り返し呼び出してください。

## ルール
- タスクが完了したら必ず task_done を呼び出してください
- ファイルを編集する前に必ず read_file で内容を確認してください
- **ファイルの新規作成・上書きは必ず write_file ツールを使うこと。bash のリダイレクト（>）は文字化けするため絶対に使わないこと**
- シェルコマンド（bash）はファイル実行や外部コマンドの呼び出しにのみ使用してください
- エラーが発生した場合は必ずエラー内容を読み、原因を特定して修正を試みてください。エラーを無視して task_done を呼んではいけません
- 同じツールを同じ引数で繰り返し呼び出さないでください

## 作業ディレクトリ
{cwd}

## 現在の日時
{datetime}
```

---

## 8. 実装ロードマップ

### Phase 1 — MVP (最小動作版)
- [ ] `backends/ollama.py` — Ollama との HTTP 通信・ストリーミング
- [ ] `tools/registry.py` — `@tool` デコレータと JSON Schema 生成
- [ ] `tools/filesystem.py` — read_file, write_file, edit_file
- [ ] `tools/shell.py` — bash 実行
- [ ] `agent/core.py` — ReAct ループ基本実装
- [ ] `cli/app.py` — シンプルな REPL

### Phase 2 — 品質向上
- [ ] `backends/llamacpp.py` — llama-cpp-python サポート
- [ ] `agent/context.py` — トークン管理・スライディングウィンドウ
- [ ] `tools/search.py` — grep, glob
- [ ] 権限確認プロンプト (ファイル書き込み・シェル実行前)
- [ ] ストリーミング表示

### Phase 3 — 拡張
- [ ] 要約ベースのコンテキスト圧縮
- [ ] MLX バックエンド (Apple Silicon)
- [ ] カスタムツールプラグイン
- [ ] セッション保存・再開

---

## 9. 技術スタック

| 用途 | ライブラリ | バージョン |
|---|---|---|
| LLM (Ollama) | `httpx` (HTTP) | ≥0.27 |
| LLM (llama.cpp) | `llama-cpp-python` | ≥0.3 |
| CLI UI | `rich` | ≥13 |
| 設定ファイル | `pyyaml` | ≥6 |
| 型定義 | `pydantic` | ≥2 |
| ビルド | `uv` + `pyproject.toml` | — |

Python バージョン: **3.11 以上**

---

## 10. Function Calling の実装方針

### Ollama (ネイティブ対応)
Ollama API の `/api/chat` エンドポイントは OpenAI 互換の `tools` フィールドをサポート。
JSON Schema を渡すだけで Function Calling が動作する。

### llama.cpp (grammar ベース)
`llama-cpp-python` は GBNF grammar を使って出力を JSON に強制できる。
ツールスキーマから grammar を生成し、確実に構造化出力を得る。

### フォールバック (grammar 非対応モデル)
System prompt にツール呼び出し形式を埋め込み、XML/JSON タグで出力させる。
```
<tool_call>{"name": "read_file", "arguments": {"path": "src/main.py"}}</tool_call>
```
出力をパースしてツール呼び出しとして処理する。

---

## 11. リスクと対策

| リスク | 対策 |
|---|---|
| LLM が無限ループする | `max_steps` で強制終了 |
| シェルコマンドで危険な操作 | `allowed_commands` ホワイトリスト + 確認プロンプト |
| コンテキスト超過 | スライディングウィンドウで古いメッセージを削除 |
| ツール呼び出し JSON パースエラー | エラーをコンテキストに戻し LLM に再試行させる |
| モデルが Function Calling 非対応 | XML タグ方式にフォールバック |
