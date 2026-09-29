import json

from app.agent.llm import OpenAILLM, _query, parse_view
from app.agent.tools import TOOLS
from app.browser.page_state import Element, PageState


def test_render_marks_untrusted_text_and_warnings():
    state = PageState(url="http://x/", title="T", elements=[Element(id=1, tag="button", text="Go")], text="hi")
    out = state.render(["asks to ignore instructions"])
    assert '[1] button "Go"' in out
    assert "<<<PAGE\nhi\nPAGE>>>" in out
    assert "SECURITY WARNING" in out


def test_render_truncates_long_pages():
    out = PageState(url="u", text="a" * 5000).render(max_text=100)
    assert "[... truncated]" in out and len(out) < 400


def test_parse_view_round_trip():
    state = PageState(
        url="http://x/p",
        title="Shoes · Acme",
        elements=[Element(id=4, tag="input", type="search", name="q", placeholder="Search")],
        text="Price: $10.00",
    )
    content = json.dumps({"ok": False, "result": "Blocked"}) + "\n\nCurrent page:\n" + state.render()
    view = parse_view(content)
    assert view.url == "http://x/p" and view.text == "Price: $10.00"
    assert view.find("input(search)") == 4
    assert not view.last_ok and view.last_result == "Blocked"


def test_query_extraction():
    assert _query('Search the Acme store for "running shoes" and tell me') == "running shoes"
    assert _query("What is the price of the Aurora Headphones?") == "Aurora Headphones"
    assert _query("Summarize the customer reviews of the Trail Runner Pro.") == "Trail Runner Pro"
    assert _query("What's the price of the Nimbus Earbuds?") == "Nimbus Earbuds"


def test_openai_translation_keeps_tool_calls_and_results():
    messages = [
        {"role": "user", "content": "Task: x"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "click", "input": {"element_id": 2}}],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    ]
    out, fns = OpenAILLM.to_openai(["sys"], messages, TOOLS)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"] == {"name": "click", "arguments": '{"element_id": 2}'}
    assert out[3] == {"role": "tool", "tool_call_id": "t1", "content": "ok"}
    assert {f["function"]["name"] for f in fns} == {t["name"] for t in TOOLS}
