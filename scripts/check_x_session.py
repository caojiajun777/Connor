"""Quick X session check for collect readiness."""

from __future__ import annotations

import asyncio
import json

from app.x_watchlist.mcp_client import MCPClientError, XNewsMCPClient


async def main() -> int:
    try:
        async with XNewsMCPClient() as client:
            status = await client.session_status()
    except MCPClientError as exc:
        print(json.dumps({"ok": False, "reason_code": exc.reason_code, "reason": str(exc)}, ensure_ascii=False, indent=2))
        print("\nNext: close any Chrome using the X agent profile, then run: npm run build && npm run login")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        print("\nIf profile is locked: close the dedicated login Chrome window and retry.")
        return 1

    ok = bool(status.get("authenticated"))
    print(json.dumps({"ok": ok, **status}, ensure_ascii=False, indent=2, default=str))
    if ok:
        print("\nSession OK — tell the assistant to continue to the next step.")
        return 0
    print("\nSession NOT ready.")
    for action in status.get("recommended_actions") or []:
        print(f"- {action}")
    print("\nTypical fix: npm run build && npm run login")
    print("Then finish login in the Chrome window, wait for Home, close the window, and re-run this script.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
