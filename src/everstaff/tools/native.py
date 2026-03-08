"""Native tool decorator and NativeTool implementation."""

from __future__ import annotations

import functools
import inspect
import json
import re
from typing import Any, Callable, get_type_hints

from everstaff.schema.tool_spec import ToolDefinition, ToolParameter


def _parse_docstring_args(doc: str) -> dict[str, str]:
    """Extract {param_name: description} from a Google-style docstring Args section."""
    result: dict[str, str] = {}
    if not doc:
        return result

    in_args = False
    base_indent: int | None = None
    current_name: str = ""
    current_parts: list[str] = []

    for line in doc.splitlines():
        if re.match(r"\s*Args:\s*$", line):
            in_args = True
            base_indent = None
            continue
        if not in_args:
            continue
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if base_indent is None:
            base_indent = indent
        if indent < base_indent:
            break  # left the Args section
        if indent == base_indent:
            m = re.match(r"(\w+):\s*(.*)", line.strip())
            if m:
                if current_name:
                    result[current_name] = " ".join(current_parts).strip()
                current_name = m.group(1)
                current_parts = [m.group(2)] if m.group(2) else []
        elif current_name:
            current_parts.append(line.strip())

    if current_name:
        result[current_name] = " ".join(current_parts).strip()

    return result


_PYTHON_TYPE_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_type_to_json_schema_type(py_type: type) -> str:
    """Convert a Python type hint to a JSON Schema type string."""
    origin = getattr(py_type, "__origin__", None)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    return _PYTHON_TYPE_TO_JSON.get(py_type, "string")


class NativeTool:
    """A native Python function wrapped as a tool."""

    def __init__(self, func: Callable, definition_: ToolDefinition, permission_hint_fn: Callable | None = None):
        self._func = func
        self._definition = definition_
        self._permission_hint_fn = permission_hint_fn
        functools.update_wrapper(self, func)

    @property
    def name(self) -> str:
        return self._definition.name

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any]) -> str:
        result = self._func(**arguments)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, str):
            return result
        return json.dumps(result, default=str)

    def permission_hint(self, args: dict[str, Any]) -> "PermissionHint | None":
        """Return a hint for generating permission patterns, or None."""
        if self._permission_hint_fn is not None:
            return self._permission_hint_fn(args)
        return None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._func(*args, **kwargs)


def tool(
    name: str | None = None,
    description: str | None = None,
    permission_hint: Callable[[dict[str, Any]], Any] | None = None,
) -> Callable[[Callable], NativeTool]:
    """Decorator to register a Python function as a native tool.

    Usage:
        @tool(name="read_file", description="Read contents of a file")
        async def read_file(path: str, encoding: str = "utf-8") -> str:
            ...
    """

    def decorator(func: Callable) -> NativeTool:
        tool_name = name or func.__name__
        tool_desc = description or (inspect.getdoc(func) or "")

        try:
            hints = get_type_hints(func)
        except Exception:
            hints = {}

        sig = inspect.signature(func)
        param_descs = _parse_docstring_args(inspect.getdoc(func) or "")
        params: list[ToolParameter] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            py_type = hints.get(param_name, str)
            # Skip return type annotation
            if param_name == "return":
                continue
            json_type = _python_type_to_json_schema_type(py_type)
            params.append(
                ToolParameter(
                    name=param_name,
                    type=json_type,
                    description=param_descs.get(param_name, ""),
                    required=param.default is inspect.Parameter.empty,
                    default=None if param.default is inspect.Parameter.empty else param.default,
                )
            )

        defn = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            parameters=params,
            source="native",
        )

        return NativeTool(func=func, definition_=defn, permission_hint_fn=permission_hint)

    return decorator
