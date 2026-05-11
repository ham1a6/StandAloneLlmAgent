# テスト仕様書

## 概要

本ドキュメントはすべてのテストの目的・前提条件・検証内容を記載する。
テストは **単体テスト**（Ollama 不要、高速）と **結合テスト**（Ollama 起動が必要）に分類される。

---

## テスト実行方法

```bash
# 単体テストのみ（CI などで利用）
python -m pytest tests/ --ignore=tests/test_integration.py -v

# 結合テストのみ
python -m pytest -m integration -v

# 全テスト（単体 + 結合）
python -m pytest tests/ -v

# ファイル単位
python -m pytest tests/test_filesystem.py -v
```

---

## 1. 単体テスト

### 1.1 `test_models.py` — データモデル

**対象ファイル:** `agent/models.py`

| テスト名 | 検証内容 |
|---|---|
| `test_toolcall_auto_id` | `ToolCall` 生成時に `id` が自動付与され `"call_"` で始まること |
| `test_toolcall_distinct_ids` | 複数の `ToolCall` が異なる `id` を持つこと |
| `test_message_defaults` | `Message` の `tool_calls`・`tool_call_id` がデフォルト `None` であること |
| `test_message_with_tool_calls` | `Message` に `tool_calls` を含められること |
| `test_chatresponse_done_defaults_to_true` | `ChatResponse.done` のデフォルト値が `True` であること |
| `test_toolschema_type_is_function` | `ToolSchema.type` が `"function"` であること |

---

### 1.2 `test_registry.py` — ツール登録・ディスパッチ

**対象ファイル:** `tools/registry.py`

**前提条件:** `clean_registry` フィクスチャでテスト間のレジストリ汚染を防止する。

| テスト名 | 検証内容 |
|---|---|
| `test_tool_registered` | `@tool` デコレータで定義した関数がレジストリに登録されること |
| `test_schema_required_params` | 型注釈に基づいて必須パラメータの JSON Schema が生成されること |
| `test_schema_optional_params` | デフォルト値のあるパラメータが `required` に含まれないこと |
| `test_schema_string_type` | `str` 型が JSON Schema で `"string"` にマップされること |
| `test_schema_bool_type` | `bool` 型が JSON Schema で `"boolean"` にマップされること |
| `test_dispatcher_dispatch_success` | 登録済みツールを正常に呼び出せること |
| `test_dispatcher_unknown_tool` | 未登録ツール名には `"unknown tool"` エラーが返ること |
| `test_dispatcher_exception_returns_error` | ツール内で例外が発生しても `"Error"` 文字列が返りクラッシュしないこと |
| `test_dispatcher_invalid_args_returns_error` | 引数キーが誤っていても `"Error"` 文字列が返ること |
| `test_dispatcher_get_schemas` | `get_schemas()` が指定ツールのスキーマを返すこと |
| `test_dispatcher_filters_tool_names` | `tool_names` 指定時に対象外ツールが含まれないこと |

---

### 1.3 `test_filesystem.py` — ファイル操作ツール

**対象ファイル:** `tools/filesystem.py`

**前提条件:** 各テストは `tmp_path` フィクスチャの独立した一時ディレクトリで動作する。

| テスト名 | 検証内容 |
|---|---|
| `test_read_file` | ファイルを行番号付きで読み込めること |
| `test_read_file_not_found` | 存在しないパスに `Error` が返ること |
| `test_read_file_offset` | `offset` で開始行を指定できること |
| `test_read_file_truncation_notice` | `limit` を超えた行数の場合に `"more lines"` 通知が付くこと |
| `test_write_file_creates_and_reads_back` | ファイルを作成して内容を確認できること |
| `test_write_file_creates_parent_dirs` | 親ディレクトリが存在しない場合に自動生成されること |
| `test_write_file_overwrites` | 既存ファイルを上書きできること |
| `test_edit_file_success` | `old_string` が一意な場合に置換が成功し `"Replaced"` が返ること |
| `test_edit_file_replace_all` | `replace_all=True` で全出現箇所を一括置換できること |
| `test_edit_file_not_found` | 存在しないファイルに `Error` が返ること |
| `test_edit_file_old_string_not_found` | `old_string` が見つからない場合に `"not found"` エラーが返ること |
| `test_edit_file_multiple_matches` | `replace_all=False` (デフォルト) で複数マッチの場合に回数を示すエラーが返りファイルが変更されないこと |
| `test_list_dir_shows_files_and_dirs` | ファイルとサブディレクトリが一覧に含まれること |
| `test_list_dir_not_found` | 存在しないパスに `Error` が返ること |
| `test_list_dir_empty` | 空ディレクトリが `"(empty)"` を返すこと |
| `test_glob_matches_pattern` | パターンに一致するファイルのみが返ること |
| `test_glob_no_matches` | マッチなしの場合に `"no matches"` が返ること |
| `test_glob_recursive` | `**/*.py` のような再帰パターンが動作すること |

---

### 1.4 `test_shell.py` — シェル実行ツール

**対象ファイル:** `tools/shell.py`

**前提条件:** Python インタープリタへのパスが利用可能であること。Windows では PowerShell、Unix では bash で実行される。

| テスト名 | 検証内容 |
|---|---|
| `test_bash_basic_output` | コマンドの標準出力が返ること |
| `test_bash_nonzero_exit_code` | 終了コード非 0 時に `"exit code: N"` が付くこと |
| `test_bash_no_output` | 出力なしのコマンドが `"(no output)"` を返すこと |
| `test_bash_stderr_captured` | 標準エラー出力が結果に含まれること |
| `test_bash_timeout` | タイムアウトした場合に `"timed out"` が返ること |
| `test_bash_multiline_output` | 複数行の出力が正しく取得されること |

---

### 1.5 `test_search.py` — grep ツール

**対象ファイル:** `tools/search.py`

| テスト名 | 検証内容 |
|---|---|
| `test_grep_finds_match` | マッチするファイル名と内容が返ること |
| `test_grep_no_match` | マッチなしの場合に `"no matches"` が返ること |
| `test_grep_on_single_file` | ファイルを直接指定できること |
| `test_grep_reports_line_numbers` | 一致した行番号が結果に含まれること（`":N:"` 形式）|
| `test_grep_invalid_regex` | 無効な正規表現に `Error` が返ること |
| `test_grep_glob_filter` | `glob` 引数で拡張子フィルタが動作すること |
| `test_grep_multiple_files` | 複数ファイルにまたがる結果が返ること |

---

### 1.6 `test_context.py` — コンテキスト管理

**対象ファイル:** `agent/context.py`

| テスト名 | 検証内容 |
|---|---|
| `test_empty_context_no_system` | System prompt なしの初期状態が空リストであること |
| `test_system_message_prepended` | `set_system()` で先頭に system メッセージが追加されること |
| `test_add_and_retrieve` | メッセージの追加と取得が正しく動作すること |
| `test_trim_keeps_latest` | `max_messages` を超えると古いメッセージが削除されること |
| `test_clear_removes_messages_keeps_system` | `clear()` でユーザー/アシスタントメッセージが消えるが system は残ること |
| `test_system_update` | `set_system()` を複数回呼ぶと最後の値になること |

---

### 1.7 `test_ollama.py` — Ollama バックエンド

**対象ファイル:** `backends/ollama.py`

**前提条件:** `httpx.Client` をモックしており、実際の Ollama サーバーは不要。

| テスト名 | 検証内容 |
|---|---|
| `test_chat_text_response` | テキスト応答が `ChatResponse.message.content` に格納されること |
| `test_chat_tool_call_response` | ネイティブ `tool_calls` フィールドのパースが動作すること |
| `test_chat_tool_call_args_as_json_string` | `arguments` が JSON 文字列で返ってきた場合に dict に変換されること |
| `test_to_dict_user_message` | user メッセージが正しい辞書形式に変換されること |
| `test_to_dict_tool_message` | tool メッセージが正しい辞書形式に変換されること |
| `test_to_dict_assistant_with_tool_calls` | tool_calls を持つ assistant メッセージが正しく変換されること |
| `test_to_dict_tool_message_no_content_defaults_empty` | content が None の tool メッセージが空文字に変換されること |
| `test_is_available_true` | HTTP 200 返却時に `is_available()` が `True` を返すこと |
| `test_is_available_false_on_exception` | 接続例外発生時に `is_available()` が `False` を返すこと |

---

### 1.8 `test_core.py` — Agent ReAct ループ

**対象ファイル:** `agent/core.py`

**前提条件:** バックエンドとディスパッチャを mock で差し替えて動作させる。

| テスト名 | 検証内容 |
|---|---|
| `test_run_returns_text_response` | テキスト応答がそのまま `run()` の戻り値になること |
| `test_run_task_done_stops_loop` | `task_done` の `result` 引数が `run()` の戻り値になること |
| `test_run_task_done_not_dispatched` | `task_done` はディスパッチャに渡されないこと |
| `test_run_tool_then_text` | ツール呼び出し → テキスト応答の2ターンが正しく動作すること |
| `test_run_max_steps_exceeded` | `max_steps` を超えた場合にエラーメッセージが返ること |
| `test_on_tool_call_callback_fired` | `on_tool_call` コールバックが呼び出されること |
| `test_on_tool_result_callback_fired` | `on_tool_result` コールバックが呼び出されること |
| `test_task_done_fires_result_callback` | `task_done` でも `on_tool_result` が呼び出されること |
| `test_reset_clears_conversation` | `reset()` でメッセージが消え system のみ残ること |
| `test_user_message_added_to_context` | `run()` 時にユーザーメッセージがコンテキストに追加されること |

---

### 1.9 `test_confirm.py` — 実行前確認コールバック

**対象ファイル:** `agent/core.py`（`on_confirm` パラメータ）

**前提条件:** バックエンドとディスパッチャを mock で差し替えて動作させる。

| テスト名 | 検証内容 |
|---|---|
| `test_no_confirm_runs_tool` | `on_confirm=None` のとき全ツールが確認なしで実行されること |
| `test_confirm_approved_runs_tool` | `on_confirm` が `True` を返した場合にツールが実行されること |
| `test_confirm_approved_result_passed_to_context` | 承認されたツールの結果が `on_tool_result` に渡されること |
| `test_confirm_denied_does_not_dispatch` | `on_confirm` が `False` を返した場合にディスパッチャが呼ばれないこと |
| `test_confirm_denied_returns_cancelled_message` | 拒否されたツールの結果として `"Cancelled"` が `on_tool_result` に渡されること |
| `test_confirm_denied_agent_continues` | キャンセル後もエージェントがループを継続し最終的に終了すること |
| `test_confirm_only_bash_not_read_file` | `bash` のみ拒否する選択的確認が動作すること |
| `test_task_done_not_passed_to_confirm` | `task_done` は `on_confirm` の対象外であること |
| `test_multiple_tools_each_confirmed` | 1レスポンス内の複数ツールが個別に確認されること |

---

### 1.10 `test_settings.py` — 設定読み込み

**対象ファイル:** `config/settings.py`

| テスト名 | 検証内容 |
|---|---|
| `test_defaults_when_no_file` | ファイルなしの場合にデフォルト値（`backend=ollama`、`model=qwen2.5-coder:7b` など）が使われること |
| `test_load_from_yaml` | YAML から正しく設定が読み込まれること |
| `test_partial_yaml_uses_defaults` | 一部のキーのみの YAML で残りはデフォルト値になること |
| `test_empty_yaml_uses_defaults` | 空の YAML ファイルでデフォルト値になること |
| `test_permissions_defaults` | `require_confirm_before_write=True`・`require_confirm_before_shell=False` がデフォルト値であること |

---

## 2. 結合テスト

**対象ファイル:** `tests/test_integration.py`

**前提条件:**
- Ollama が起動済み（`ollama serve`）
- `qwen2.5-coder:7b` モデルが取得済み（`ollama pull qwen2.5-coder:7b`）
- 起動していない場合は自動的にスキップされる
- `workdir` フィクスチャが `os.getcwd()` と `tools.shell._cwd` の両方を一時ディレクトリに同期する

**実行コマンド:**
```bash
pytest tests/test_integration.py -v
pytest -m integration -v
```

---

### 2.1 基本動作テスト

| テスト名 | シナリオ | 合格条件 |
|---|---|---|
| `test_ollama_connection` | Ollama サーバーへの接続確認 | `is_available()` が `True` を返すこと |
| `test_agent_creates_file` | `write_file` で `hello.txt` を作成させる | ファイルが存在し `"Hello"` を含む内容であること |
| `test_agent_generates_and_runs_python` | `fizzbuzz.py` を生成・実行させる | ファイルが存在し 20 バイト以上であること |
| `test_agent_reads_and_edits_file` | `read_file` → `edit_file` で `COUNT` を `42` に変更させる | ファイル内に `"42"` が含まれること |

---

### 2.2 ファイル修正・改修テスト

| テスト名 | シナリオ | 合格条件 |
|---|---|---|
| `test_agent_fixes_runtime_bug` | `ZeroDivisionError` のある `calc.py` を修正させる | `python calc.py` が exit code 0 で完了すること |
| `test_agent_adds_function_to_existing` | `add`/`subtract` のある `math_utils.py` に `multiply` を追加させる | `multiply` が追加され既存関数が残り、`multiply(3, 4) == 12` であること |
| `test_agent_fixes_syntax_error` | 閉じ括弧が抜けた `greeting.py` の構文エラーを修正させる | `python greeting.py` が exit code 0 で `"Hello"` を出力すること |
| `test_agent_renames_variable_consistently` | `config.py` の `MAX_SIZE` をすべて `MAX_LIMIT` にリネームさせる | ファイル内に `"MAX_LIMIT"` が含まれ、`python config.py` が exit code 0 で完了すること |

---

### 2.3 複雑なアプリ作成テスト

| テスト名 | シナリオ | 合格条件 |
|---|---|---|
| `test_agent_creates_bank_account_class` | `BankAccount` クラス（`deposit`/`withdraw`/`get_balance`）を一から作成させる。`deposit`・`withdraw` は `amount <= 0` で `ValueError`、`withdraw` は残高不足でも `ValueError` | `get_balance()` が正しい残高を返し、不正な `deposit(-1)` で `ValueError` が発生すること |
| `test_agent_creates_word_counter` | `count_words(text)`・`top_n(text, n)` を持つ `word_counter.py` を作成させる（小文字統一） | `count_words` が正しい出現回数を返し、`top_n` が頻度順リストを返すこと |

---

### 2.4 長い指示による改修テスト

| テスト名 | シナリオ | 合格条件 |
|---|---|---|
| `test_agent_refactors_with_long_instructions` | バリデーションなし・新関数なしの `stats.py`（`mean`/`minimum`/`maximum`）に対して、①全関数に空リスト検証（`ValueError`）を追加、②`summary()` 関数（`mean`/`min`/`max` を含む dict を返す）を追加 | `summary([1,2,3])` が正しい dict を返し、`mean([])` で `ValueError` が発生すること |

---

### 2.5 複数ファイル改修テスト

| テスト名 | シナリオ | 合格条件 |
|---|---|---|
| `test_agent_adds_feature_across_two_files` | `geometry.py`（`circle_area`/`rectangle_area`）と `report.py`（両関数を呼び出す）が既存。`geometry.py` に `triangle_area(base, height)` を追加し、`report.py` からも呼び出すよう修正させる | `triangle_area` が両ファイルに含まれ、`report.py` が 3 行以上出力し、`triangle_area(6, 8) == 24.0` であること |
| `test_agent_renames_function_across_multiple_files` | `utils.py`（`calc_tax` 定義）と `invoice.py`（`calc_tax` をインポートして呼び出し）が既存。`calc_tax` → `calculate_tax` にリネームさせる | 両ファイルに `calculate_tax` が含まれ古い名前が残らず、`invoice.py` が exit code 0 で `"total="` を出力すること |

---

## 3. フィクスチャ

**定義ファイル:** `tests/conftest.py`

| フィクスチャ名 | スコープ | 説明 |
|---|---|---|
| `clean_registry` | function | テスト間でグローバルなツールレジストリを隔離する。`@tool` デコレータを使うテストで必須 |
| `workdir` | function | `tmp_path` を `os.getcwd()` と `tools.shell._cwd` の両方に設定する。`write_file`（os.getcwd() 参照）と `bash`（`_cwd` 参照）のパスを一致させるために必要 |

---

## 4. テスト設計上の注意点

### 単体テストと結合テストの分離

- 単体テストは Ollama・ファイルシステム・ネットワークなどの外部依存を持たない（またはモックする）
- 結合テストは `@pytest.mark.integration` でマークし、`conftest.py` の `ollama_backend` フィクスチャが自動スキップを行う

### `workdir` フィクスチャの必要性

`write_file` は `Path(relative)` を `os.getcwd()` 相対で解決し、`bash` は `tools.shell._cwd` モジュール変数を作業ディレクトリとして使用する。両者を同期しないと、ファイルを作成したディレクトリと bash の実行ディレクトリが異なり、`python foo.py` が `FileNotFoundError` になる。

### `on_confirm` のテスト設計

`on_confirm` コールバックは `task_done` に対して呼ばれない（agent.core の task_done 早期 return より前に処理される）。この非対称性は `test_task_done_not_passed_to_confirm` で明示的に検証している。
