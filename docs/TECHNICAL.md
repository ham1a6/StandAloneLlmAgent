# 技術解説

このドキュメントはコードを読む人・拡張する人向けに、実装上の判断・設計の背景・ハマりどころを解説する。

---

## 1. ReAct ループの実装

### パターン概要

ReAct（Reasoning + Acting）は LLM にツール呼び出しを繰り返させるループパターン。

```
[Think]   LLM へメッセージを送り、次のアクションを決定させる
[Act]     LLM が返した tool_call を実行する
[Observe] 実行結果をコンテキストに追加し、再度 Think へ
```

LLM は「何をすべきか考え（Think）、ツールを呼び（Act）、結果を見て（Observe）、また考える」を繰り返す。
`task_done` ツールを呼ぶか、ツール呼び出しなしのテキスト応答を返したタイミングでループを抜ける。

### `agent/core.py` の構造

```python
for _ in range(self.max_steps):
    response = self.backend.chat_stream(messages, tools, on_chunk=on_text_chunk)

    if response.message.tool_calls:
        # task_done は早期リターン
        for tc in response.message.tool_calls:
            if tc.name == "task_done":
                return tc.arguments.get("result", "完了")

        # on_confirm で各ツールを承認/拒否
        confirmed = []
        for tc in response.message.tool_calls:
            if self.on_confirm and not self.on_confirm(tc.name, tc.arguments):
                confirmed.append(None)  # キャンセル
            else:
                confirmed.append(tc)

        # 並列実行（複数ツールの場合 ThreadPoolExecutor）
        results = dispatch_all(confirmed)

        # 結果をコンテキストに追加して次の Think へ
        for tc in response.message.tool_calls:
            self.context.add(Message(role="tool", content=results[tc.id]))
    else:
        # テキスト応答 = 最終回答
        return response.message.content
```

### なぜ並列実行するのか

LLM が1レスポンスで複数のツール呼び出しを返す場合がある（例: `read_file("a.py")` と `read_file("b.py")` を同時に）。これらは独立しているため `ThreadPoolExecutor` で並列実行することで待ち時間を削減できる。

---

## 2. Function Calling の3段階フォールバック

### 背景：Ollama 0.23.x のバグ

Ollama は `/api/chat` の `tools` フィールドで Function Calling をサポートするが、**Ollama 0.23.x では Qwen2.5 の `<tool_call>` 出力を `message.tool_calls` フィールドに変換しない**。

つまりモデルは正しくツール呼び出しを生成しているのに、API が `tool_calls: []`、`content: "<tool_call>...</tool_call>"` という形で返してくる。

### 解析の優先順位（`backends/ollama.py`）

```python
# 1. ネイティブ tool_calls（新バージョン Ollama で動作）
raw_tcs = msg_data.get("tool_calls")
if raw_tcs:
    tool_calls = parse_native(raw_tcs)

# 2. <tool_call>...</tool_call> XML ブロック（Qwen2.5 の訓練済み形式）
if not tool_calls and content:
    parsed, remaining = self._extract_tool_calls(content)
    if parsed:
        tool_calls = parsed
        content = remaining or None
```

`_extract_tool_calls()` の内部では3段階でパースを試みる：

| 優先度 | 形式 | 例 |
|---|---|---|
| 1位 | `<tool_call>JSON</tool_call>` | Qwen2.5 のデフォルト出力形式 |
| 2位 | JSON 単一行 | `{"name": "bash", "arguments": {...}}` |
| 3位 | コンテンツ全体が JSON | モデルによっては全体を JSON として返す |

### Qwen2.5 チャットテンプレートトークンの除去

Qwen2.5 は `<|im_start|>user\n` のようなチャットテンプレートトークンをレスポンスの `content` に漏らすことがある。`_TEMPLATE_TOKEN_RE` でこれを除去している。

```python
_TEMPLATE_TOKEN_RE = re.compile(r"<\|im_(start|end)\|>(\w+\n)?", re.DOTALL)
content = _TEMPLATE_TOKEN_RE.sub("", raw).strip() or None
```

### なぜ System Prompt を英語にするか

日本語で System Prompt を書くと、Qwen2.5 が「役立つアシスタント」モードに入り、ツールを呼び出す代わりに Markdown コードブロックで説明文を生成し始める。英語プロンプトにすることでツール呼び出しモードを維持できる。

---

## 3. ツールレジストリと JSON Schema 自動生成

### `@tool` デコレータのしくみ（`tools/registry.py`）

```python
@tool(name="read_file", description="Read a file with line numbers")
def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    ...
```

デコレータは関数のシグネチャを `inspect.signature()` で解析し、OpenAI 互換の JSON Schema を自動生成する。

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read a file with line numbers",
    "parameters": {
      "type": "object",
      "properties": {
        "path":   {"type": "string"},
        "offset": {"type": "integer"},
        "limit":  {"type": "integer"}
      },
      "required": ["path"]
    }
  }
}
```

Python 型 → JSON Schema 型のマッピング:

| Python 型 | JSON Schema 型 |
|---|---|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| その他 | `"string"` |

デフォルト値のあるパラメータは `required` に含まれない。

### ツールの追加方法

`tools/__init__.py` に `import tools.my_module` を追加するだけ。インポート時に `@tool` デコレータが `_registry` グローバル辞書に登録する。

---

## 4. コンテキスト管理（スライディングウィンドウ）

### 問題：LLM のコンテキストウィンドウは有限

長い会話でコンテキストが溢れると HTTP エラーまたは劣化した応答になる。

### 実装：メッセージ数ベースのスライディングウィンドウ（`agent/context.py`）

```python
def _trim(self) -> None:
    if len(self._messages) > self.max_messages:
        self._messages = self._messages[-self.max_messages:]
```

- System prompt は常に先頭に保持（削除されない）
- ユーザー・アシスタント・ツールのメッセージを最新 40 件に制限
- トークン数ではなくメッセージ数で管理する（実装が単純で十分に機能する）

### トークン数管理にしない理由

トークン数の正確な計算にはモデルのトークナイザが必要。Ollama は外部から取得しにくく、実装コストが高い。メッセージ数での制限は粗いが、平均的なメッセージ長を考慮すればコンテキスト溢れを十分に防げる。

---

## 5. `bash` ツールの `cd` 追跡

### 問題：subprocess の `cwd` は呼び出しごとにリセットされる

```python
bash("cd /tmp")
bash("ls")  # /tmp ではなく初期ディレクトリが表示される
```

### 解決策：CWD マーカーを stdout に埋め込む（`tools/shell.py`）

各コマンドの末尾に CWD を stdout に出力するコードを追記する：

**Windows (PowerShell):**
```powershell
{command}; $__e = $LASTEXITCODE;
Write-Output "`n__AGENT_CWD__:$((Get-Location).Path)";
exit $__e
```

**Unix (bash):**
```bash
{command}
__exit_code=$?
printf "\n__AGENT_CWD__:%s\n" "$(pwd)"
exit $__exit_code
```

`_split_cwd_marker()` がこのマーカー行を stdout から取り除き、新しい CWD を `_cwd` モジュール変数に保存する。次の呼び出しでは保存された `_cwd` を `subprocess.run(cwd=...)` に渡す。

### テストでの注意点

`write_file` は `os.getcwd()` を基準にパスを解決し、`bash` は `tools.shell._cwd` を使う。テストではこの2つが異なるディレクトリを指すため、`workdir` フィクスチャが両方を同期している。

---

## 6. `on_confirm` コールバックの設計

### 設計方針

「確認が必要かどうか」を Agent が知る必要はない。Agent は `on_confirm` が設定されていれば呼ぶだけで、ポリシー判断はコールバック側（CLI）が行う。

```
CLI（ポリシー判断） ─── on_confirm ───► Agent（機構）
                           │
                    False を返すと
                     ツールをキャンセル
```

### 自動実行モードとの関係

```python
# _run_with_ui の中
_original_confirm = agent.on_confirm       # 設定ベースのコールバックを保存
_effective_confirm = None if auto_mode[0] else _original_confirm  # AUTO 時は None

agent.on_confirm = on_confirm_in_live if _effective_confirm else None

try:
    agent.run(user_input, ...)
finally:
    agent.on_confirm = _original_confirm    # 必ず元に戻す
```

自動実行モードは `on_confirm = None` にするだけで実現できる。Agent は `on_confirm is None` の場合すべてのツールを実行する。

### Live 表示との競合

`rich.Live` が動いている間に `console.input()` を呼ぶと表示が崩れる。`on_confirm_in_live` は `live.stop()` → 確認プロンプト → `live.start()` の順で回避している。

---

## 7. 複数行入力の実装

### 問題：Shift+Enter のエスケープシーケンスは端末依存

`prompt_toolkit 3.0.52` では `Keys.ShiftEnter` が存在しない。端末ごとに異なるエスケープシーケンスを送信する：

| 端末 | Shift+Enter のシーケンス |
|---|---|
| Windows Terminal | `\x1b[27;2;13~` (modifyOtherKeys) |
| Kitty / その他 | `\x1b[13;2u` (Kitty keyboard protocol) |
| macOS Terminal | サポート外（Alt+Enter を代替に使用） |

### 実装（`cli/app.py`）

```python
# 両方のシーケンスにバインド（対応していない方は例外を無視）
for _seq in ("\x1b[27;2;13~", "\x1b[13;2u"):
    try:
        kb.add(_seq)(_insert_newline)
    except Exception:
        pass

# Alt+Enter を確実なフォールバックとして追加
@kb.add("escape", "enter")
def _newline_alt(event):
    event.current_buffer.insert_text("\n")
```

### Enter で送信するために `eager=True` が必要な理由

`multiline=True` を設定すると prompt_toolkit はデフォルトで Enter をキー発行（改行）として処理する。`eager=True` を付けることで、このデフォルトバインディングより先に評価されるようになる。

```python
@kb.add("enter", eager=True)  # デフォルトの multiline Enter より優先
def _submit(event):
    event.current_buffer.validate_and_handle()
```

### Shift+Tab（`Keys.BackTab`）

`Keys.BackTab` は `prompt_toolkit 3.0.52` に存在する。`BackTab` は Shift+Tab の標準的なエスケープシーケンス（`\x1b[Z`）に対応している。

```python
@kb.add(Keys.BackTab)
def _toggle_auto(event):
    auto_mode[0] = not auto_mode[0]
    ...
    event.app.invalidate()  # プロンプト表示を即座に更新
```

---

## 8. ストリーミング表示の実装

### 問題：ツール呼び出しを含むレスポンスを途中表示できない

ストリームを逐次表示していると、最後に `<tool_call>` タグが現れたときに既に表示した内容を消す必要がある。

### 解決策：全ストリームをバッファリングしてからパース

```python
# chat_stream() の実装
accumulated = []
for line in response.iter_lines():
    data = json.loads(line)
    chunk = data.get("message", {}).get("content", "")
    if chunk:
        accumulated.append(chunk)

full_text = "".join(accumulated)

# ツール呼び出しが含まれる場合 → on_chunk を呼ばない
parsed, remaining = self._extract_tool_calls(full_text)
if parsed:
    result.message.tool_calls = parsed
    result.message.content = remaining or None
else:
    # 純テキスト応答のみ on_chunk で通知
    if on_chunk:
        on_chunk(full_text)
```

ユーザーへのストリーミング表示は純テキスト応答のときのみ行い、ツール呼び出しの場合は表示しない（生の `<tool_call>` XML がユーザーに見えないようにする）。

---

## 9. System Prompt の設計

### 「ツール呼び出しフォーマットを明示する」理由

Ollama の `tools` フィールドで JSON Schema を渡しても、モデルが実際にどの形式でツールを呼び出すかは保証されない。System Prompt に `<tool_call>` XML 形式を明示することで、モデルがこの形式を使うように誘導できる（Qwen2.5 の訓練済みフォーマットと一致するため効果的）。

### `python -c "..."` を禁止する理由

モデルが複数行 Python を `-c` オプションで実行しようとすると `\n` がリテラル文字列として扱われ SyntaxError になる。System Prompt で「複数行スクリプトは必ず `write_file` で保存してから `bash` で実行する」と明示することで、このループを防げる。

### ツールスキーマを System Prompt に埋め込む理由

Ollama の `tools` フィールドは Function Calling をサポートするが、モデルが実際にこれを参照するかどうかはモデル依存。System Prompt に直接 JSON Schema を埋め込むことでモデルが確実に参照できる。

---

## 10. 拡張ポイント

### 新しいバックエンドを追加する

`backends/base.py` の `LLMBackend` を継承し、`chat()` と `is_available()` を実装する。

```python
class MyBackend(LLMBackend):
    def chat(self, messages, tools=None) -> ChatResponse:
        ...
    def is_available(self) -> bool:
        ...
```

`chat_stream()` はデフォルト実装（`chat()` に委譲）があるため、ストリーミング不要なら実装不要。

### 新しいツールを追加する

```python
# tools/my_tools.py
from tools.registry import tool

@tool(name="fetch_url", description="Fetch text content from a URL")
def fetch_url(url: str, timeout: int = 10) -> str:
    """url: URL to fetch; timeout: seconds"""
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode()
```

`tools/__init__.py` に `import tools.my_tools` を追加すれば、System Prompt への自動追加・`ToolDispatcher` への登録が行われる。

### コンテキスト圧縮を実装する（Phase 3）

`ContextManager._trim()` をオーバーライドし、古いメッセージを削除する代わりに LLM で要約する。`agent/core.py` は `ContextManager.get_messages()` を呼ぶだけなので、この部分の変更は Agent に影響しない。
