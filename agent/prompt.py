from datetime import datetime
import json
import os

SYSTEM_TEMPLATE = """\
You are an autonomous agent. Complete every task by calling tools. Never write text explanations.

# Available tools

<tools>
{tool_schemas}
</tools>

# How to call a tool

You MUST use this exact format. Never output code blocks (```).

<tool_call>
{{"name": "TOOL_NAME", "arguments": {{"param": "value"}}}}
</tool_call>

# Rules
- To create or write a file → call write_file (forbidden to output code blocks)
- To run a command → call bash
- When the task is complete → call task_done
- On error → read the output, fix the problem, retry
- Read files with read_file before editing them
- Multiple independent operations can be called at the same time

# Working directory
{cwd}

# Current datetime
{datetime}
"""


def build_system_prompt() -> str:
    from tools.registry import _registry  # imported here to avoid circular import at load time
    schemas = [
        json.dumps(entry.schema.model_dump(), ensure_ascii=False)
        for entry in _registry.values()
    ]
    return SYSTEM_TEMPLATE.format(
        tool_schemas="\n".join(schemas),
        cwd=os.getcwd(),
        datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
