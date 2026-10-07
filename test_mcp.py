import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "http://localhost:5002/mcp"


async def main():
    print(f"Connecting to MCP server: {MCP_URL}")

    async with streamable_http_client(MCP_URL) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:

            # Establish MCP connection
            await session.initialize()
            print("Connected to MCP server!\n")

            # List registered MCP tools
            tools = await session.list_tools()

            print("Available MCP tools:")
            for tool in tools.tools:
                print(f" - {tool.name}")

            # Call Thomas's transaction tool
            print("\nCalling transaction_summary...\n")

            result = await session.call_tool(
                "transaction_summary",
                arguments={}
            )

            print("MCP RESULT:")
            print(result)


if __name__ == "__main__":
    asyncio.run(main())