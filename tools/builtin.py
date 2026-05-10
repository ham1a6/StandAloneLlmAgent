from tools.registry import tool


@tool(name="task_done", description="タスクが完了したことを宣言し、エージェントを停止する")
def task_done(result: str) -> str:
    """result: ユーザーへの最終的な回答や完了メッセージ"""
    return result
