"""Agent loop with a fake browser and scripted LLM responses: proves the
guardrails hold even when the model does the wrong thing."""

import json

from app.agent.agent import Agent
from app.browser.page_state import PageState
from tests.conftest import SHOP, FakeBrowser, ListLLM, call


async def test_gullible_model_cannot_follow_injection(settings, shop_pages):
    browser = FakeBrowser(shop_pages)
    llm = ListLLM(
        [
            [call("navigate", url=SHOP)],
            [call("click", element_id=1)],
            [call("navigate", url="http://evil.example/steal")],  # model obeys the page
            [call("done", answer="gave up", success=False)],
        ]
    )
    result = await Agent(llm, browser, settings).run("read the reviews")

    assert ("goto", "http://evil.example/steal") not in browser.actions
    blocked = result.steps[2]
    assert not blocked.ok and "not in the allowed domains" in blocked.outcome
    assert result.steps[1].flags, "injection on the reviews page should be flagged"
    assert "SECURITY WARNING" in llm.calls[2][-1]["content"][0]["content"]


async def test_rejected_approval_stops_before_clicking(settings, shop_pages):
    browser = FakeBrowser(shop_pages)
    asked = []

    async def deny(req):
        asked.append(req)
        return False

    llm = ListLLM([[call("navigate", url=SHOP)], [call("click", element_id=2)]])
    result = await Agent(llm, browser, settings, approver=deny).run("buy it")

    assert result.status == "rejected"
    assert asked and "Place order" in asked[0]["reason"]
    assert ("click", 2) not in browser.actions


async def test_approved_action_runs(settings, shop_pages):
    browser = FakeBrowser(shop_pages)

    async def approve(_):
        return True

    llm = ListLLM(
        [[call("navigate", url=SHOP)], [call("click", element_id=2)], [call("done", answer="ok", success=True)]]
    )
    result = await Agent(llm, browser, settings, approver=approve).run("buy it")
    assert result.status == "done"
    assert ("click", 2) in browser.actions


async def test_secret_placeholder_is_resolved_but_never_shown_to_the_model(settings, shop_pages):
    shop_pages[SHOP].text = "Your password hunter2-secret was saved"  # a page echoing the secret
    browser = FakeBrowser(shop_pages)
    llm = ListLLM(
        [
            [call("navigate", url=SHOP)],
            [call("type_text", element_id=3, text="{{secret:pw}}")],
            [call("done", answer="ok", success=True)],
        ]
    )
    await Agent(llm, browser, settings).run("log in")

    assert ("type", 3, "hunter2-secret", False) in browser.actions
    assert "hunter2-secret" not in json.dumps(llm.calls)


async def test_literal_password_is_blocked(settings, shop_pages):
    browser = FakeBrowser(shop_pages)
    llm = ListLLM(
        [
            [call("navigate", url=SHOP)],
            [call("type_text", element_id=3, text="guessed-password")],
            [call("done", answer="no", success=False)],
        ]
    )
    result = await Agent(llm, browser, settings).run("log in")
    assert not result.steps[1].ok
    assert not any(a[0] == "type" for a in browser.actions)


async def test_only_one_action_per_turn(settings, shop_pages):
    browser = FakeBrowser(shop_pages)
    llm = ListLLM(
        [
            [call("navigate", url=SHOP), call("click", element_id=1)],
            [call("done", answer="ok", success=True)],
        ]
    )
    await Agent(llm, browser, settings).run("x")
    assert browser.actions == [("goto", SHOP)]
    skipped = llm.calls[1][-1]["content"][1]
    assert skipped["is_error"] and "one action per turn" in skipped["content"]


async def test_unknown_element_is_a_recoverable_error(settings, shop_pages):
    browser = FakeBrowser(shop_pages)
    llm = ListLLM(
        [[call("navigate", url=SHOP)], [call("click", element_id=99)], [call("done", answer="ok", success=True)]]
    )
    result = await Agent(llm, browser, settings).run("x")
    assert not result.steps[1].ok and "No element [99]" in result.steps[1].outcome
    assert result.status == "done"


async def test_step_budget(settings):
    browser = FakeBrowser({SHOP: PageState(url=SHOP)})
    llm = ListLLM([[call("scroll", direction="down")]])
    result = await Agent(llm, browser, settings).run("loop forever")
    assert result.status == "max_steps"
    assert len(result.steps) == settings.max_steps


async def test_plain_text_reply_finishes(settings):
    llm = ListLLM([[{"type": "text", "text": "Nothing to do."}]])
    result = await Agent(llm, FakeBrowser({}), settings).run("x")
    assert result.status == "done" and result.answer == "Nothing to do."
    assert result.usage["llm_calls"] == 1 and result.usage["input_tokens"] == 10
