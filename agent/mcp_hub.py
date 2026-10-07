"""MCP-конектори («плагіни» для ШІ): Хомі підключає готові сервери інструментів зі світу MCP.

Кожен сервер — окрема програма (часто `npx …` або `uvx …`), яка вміє щось своє: файли, браузер,
календар, Home Assistant, Spotify, GitHub… Хомі на старті запитує в кожного список інструментів і
додає їх до своїх (з префіксом назви сервера). Gemma кличе їх так само, як вбудовані.

Налаштування — у config.toml:
    [mcp.servers.files]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "C:\\\\Users\\\\igork\\\\Documents"]
    # env = { KEY = "…" }          — за потреби
    # allow = ["read_file", "list_directory"]   — лише ці інструменти (менше — розумніше Gemma)
"""
import asyncio
import json
import threading


class MCPHub:
    def __init__(self, servers: dict, log=print, timeout: float = 60.0):
        self.servers = servers or {}
        self.log = log
        self.timeout = timeout
        self.tools: dict[str, tuple[str, str, dict]] = {}     # повна назва → (сервер, назва, опис-схема)
        self.sessions: dict = {}
        self.loop = None
        self._ready = threading.Event()

    # ---- запуск -----------------------------------------------------------
    def start(self, wait: float = 30.0):
        if not self.servers:
            return
        t = threading.Thread(target=self._run_loop, daemon=True)
        t.start()
        self._ready.wait(wait)

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:  # noqa: BLE001
            self.log("MCP", f"зупинився: {e}")
        finally:
            self._ready.set()

    async def _main(self):
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            for name, conf in self.servers.items():
                try:
                    await self._connect(stack, name, conf)
                except Exception as e:  # noqa: BLE001 — один зламаний конектор не валить інші
                    self.log("MCP", f"«{name}» не підключився: {str(e)[:200]}")
            self._ready.set()
            await asyncio.Event().wait()            # тримаємо сесії живими

    async def _connect(self, stack, name: str, conf: dict):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=conf["command"], args=list(conf.get("args", [])),
                                       env=conf.get("env") or None, cwd=conf.get("cwd") or None)
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=self.timeout)
        listed = await session.list_tools()
        allow = set(conf.get("allow", []))
        added = []
        for tool in listed.tools:
            if allow and tool.name not in allow:
                continue
            full = f"{name}__{tool.name}"[:64]
            self.tools[full] = (name, tool.name, {
                "type": "function", "function": {
                    "name": full,
                    "description": f"[{name}] {(tool.description or tool.name)[:400]}",
                    # mcp 2.x — input_schema, 1.x — inputSchema
                    "parameters": (getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
                                   or {"type": "object", "properties": {}})}})
            added.append(tool.name)
        self.sessions[name] = session
        self.log("MCP", f"«{name}» підключено: {', '.join(added) or 'без інструментів'}")

    # ---- для Gemma ----------------------------------------------------------
    def schemas(self) -> list[dict]:
        return [schema for _, _, schema in self.tools.values()]

    def has(self, full: str) -> bool:
        return full in self.tools

    def call(self, full: str, args: dict) -> str:
        server, tool, _ = self.tools[full]
        session = self.sessions.get(server)
        if session is None or self.loop is None:
            return f"Конектор «{server}» зараз недоступний."
        fut = asyncio.run_coroutine_threadsafe(session.call_tool(tool, args or {}), self.loop)
        try:
            result = fut.result(timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            return f"Помилка конектора {server}: {e}"
        parts = []
        for c in getattr(result, "content", []) or []:
            text = getattr(c, "text", None)
            parts.append(text if text is not None else json.dumps(getattr(c, "model_dump", lambda: str(c))(),
                                                                  ensure_ascii=False)[:500])
        out = "\n".join(parts).strip() or "Готово."
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            out = "Помилка: " + out
        return out[:6000]
