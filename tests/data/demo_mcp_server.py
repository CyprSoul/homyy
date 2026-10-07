"""Крихітний MCP-сервер для тестів (працює з mcp 1.x і 2.x)."""
try:
    from mcp.server.mcpserver import MCPServer as Server      # mcp 2.x
except ImportError:
    from mcp.server.fastmcp import FastMCP as Server           # mcp 1.x
app = Server("demo")

@app.tool()
def add(a: int, b: int) -> int:
    """Скласти два числа."""
    return a + b

@app.tool()
def greet(name: str) -> str:
    """Привітати людину."""
    return f"Привіт, {name}!"

if __name__ == "__main__":
    app.run()
