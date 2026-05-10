from __future__ import annotations
import inspect
import functools
from typing import Any, Callable, get_type_hints, get_origin, get_args
from agent.models import ToolSchema, ToolFunction, ToolCall

_registry: dict[str, _ToolEntry] = {}


class _ToolEntry:
    def __init__(self, fn: Callable, name: str, schema: ToolSchema):
        self.fn = fn
        self.name = name
        self.schema = schema


def _type_to_json_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        items = _type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": items}
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean"}
    return {"type": mapping.get(annotation, "string")}


def _extract_param_doc(docstring: str, param_name: str) -> str:
    for line in docstring.splitlines():
        line = line.strip()
        if line.startswith(f"{param_name}:"):
            return line[len(param_name) + 1:].strip()
    return ""


def tool(name: str | None = None, description: str = "") -> Callable:
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        hints = get_type_hints(fn)
        sig = inspect.signature(fn)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            annotation = hints.get(param_name, str)
            prop = _type_to_json_schema(annotation)
            doc_line = _extract_param_doc(fn.__doc__ or "", param_name)
            if doc_line:
                prop["description"] = doc_line
            properties[param_name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        schema = ToolSchema(
            function=ToolFunction(
                name=tool_name,
                description=description,
                parameters={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            )
        )
        _registry[tool_name] = _ToolEntry(fn=fn, name=tool_name, schema=schema)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper

    return decorator


class ToolDispatcher:
    def __init__(self, tool_names: list[str] | None = None):
        if tool_names is None:
            self._tools = dict(_registry)
        else:
            self._tools = {n: _registry[n] for n in tool_names if n in _registry}

    def get_schemas(self) -> list[ToolSchema]:
        return [entry.schema for entry in self._tools.values()]

    def dispatch(self, tool_call: ToolCall) -> str:
        entry = self._tools.get(tool_call.name)
        if entry is None:
            return f"Error: unknown tool '{tool_call.name}'"
        try:
            result = entry.fn(**tool_call.arguments)
            return str(result) if result is not None else ""
        except TypeError as e:
            return f"Error: invalid arguments for '{tool_call.name}': {e}"
        except Exception as e:
            return f"Error: {e}"
