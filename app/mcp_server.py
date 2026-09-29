"""MCP server: lets any Model Context Protocol client (Claude Desktop, Claude Code,
IDE agents) delegate a web task to WebPilot as a single tool call.

Same guardrails as the web app. There is no human watching an MCP call, so
sensitive actions (purchases, payments, deletions) are always rejected here.

    python -m app.mcp_server
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.agent.agent import Agent, deny_all
from app.agent.guardrails import url_policy
from app.agent.llm import get_llm
from app.browser.driver import PlaywrightBrowser
from app.config import get_settings


def build_server() -> MCPServer:
    server = MCPServer(
        name="webpilot",
        instructions=(
            "Run a task in a real, sandboxed web browser and get back the answer plus a step-by-step trace. "
            "Only allowed domains can be opened; purchases and other sensitive actions are refused."
        ),
    )

    @server.tool()
    async def run_browser_task(task: str) -> dict[str, Any]:
        """Complete a task in a web browser (search, read, compare, fill forms) and return the result."""
        s = get_settings()
        policy = url_policy(s.allowed_domains, s.browser_denied_paths)
        async with PlaywrightBrowser.launch(True, s.browser_channel, policy) as browser:
            result = await Agent(get_llm(), browser, s, approver=deny_all).run(task)
        return {
            "status": result.status,
            "answer": result.answer,
            "steps": [f"{st.n}. {st.action} {st.args} -> {st.outcome}" for st in result.steps],
        }

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
