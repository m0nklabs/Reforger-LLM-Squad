#!/usr/bin/env python3
"""RCON client for Arma Reforger dedicated server.
Usage: python scripts/rcon_test.py [command]
  No args = run test sequence (#players, #roles, #say)
  With arg = send that command (e.g. python scripts/rcon_test.py "#players")
"""
import asyncio
import sys
import berconpy

HOST = "127.0.0.1"
PORT = 19999
PASSWORD = "llmsquad"

async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else None

    client = berconpy.RCONClient()
    print(f"[RCON] Connecting to {HOST}:{PORT}...")

    async with client.connect(ip=HOST, port=PORT, password=PASSWORD):
        print("[RCON] CONNECTED OK")

        if cmd:
            resp = await client.send_command(cmd)
            print(f"[RCON] {cmd}: {resp}")
        else:
            # Test sequence
            resp = await client.send_command("#players")
            print(f"[RCON] #players: {resp}")

            resp2 = await client.send_command("#roles")
            print(f"[RCON] #roles: {resp2}")

            resp3 = await client.send_command("#say Hello from the LLM Squad RCON client!")
            print(f"[RCON] #say: {resp3}")

    print("[RCON] DISCONNECTED")

if __name__ == "__main__":
    asyncio.run(main())
