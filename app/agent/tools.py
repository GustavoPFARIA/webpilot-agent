"""The browser actions the model can call (JSON Schema, Anthropic tool format).

Small, explicit verbs referencing element ids from the page state. One action
per step: the model always decides the next move from a fresh page state.
"""

TOOLS = [
    {
        "name": "navigate",
        "description": "Open a URL in the current tab. Only allowed domains can be opened.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Absolute http(s) URL."}},
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click an interactive element (link, button, checkbox) by its [id] from the page state.",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "integer"}},
            "required": ["element_id"],
        },
    },
    {
        "name": "type_text",
        "description": (
            "Replace the content of an input or textarea. For credentials write a placeholder like "
            "{{secret:store_password}}; the real value is filled in outside the model. "
            "Set submit=true to press Enter afterwards."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer"},
                "text": {"type": "string"},
                "submit": {"type": "boolean", "default": False},
            },
            "required": ["element_id", "text"],
        },
    },
    {
        "name": "select_option",
        "description": "Choose an option in a <select> element.",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "integer"}, "value": {"type": "string"}},
            "required": ["element_id", "value"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the page to reveal more content.",
        "input_schema": {
            "type": "object",
            "properties": {"direction": {"type": "string", "enum": ["up", "down"]}},
            "required": ["direction"],
        },
    },
    {
        "name": "done",
        "description": (
            "Finish the task. `answer` is what the user reads: the requested information or a short "
            "report of what was done. Set success=false if the task could not be completed, and say why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}, "success": {"type": "boolean"}},
            "required": ["answer", "success"],
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}
