#!/bin/bash
# Start both shared local services
# Usage: ./start_services.sh [mcp-port] [rag-port]

MCP_PORT=${1:-8090}
RAG_PORT=${2:-8091}

echo "Starting Shared Local Services..."
echo "MCP Server will run on port $MCP_PORT"
echo("RAG Server will run on port $RAG_PORT"
echo "Press Ctrl+C to stop both services"
echo ""

# Start MCP server in background
python mcp_server.py &
MCP_PID=$!

# Start RAG server in background
python rag_server.py &
RAG_PID=$!

# Function to cleanup on exit
cleanup() {
    echo "Stopping services..."
    kill $MCP_PID 2>/dev/null
    kill $RAG_PID 2>/dev/null
    wait $MCP_PID 2>/dev/null
    wait $RAG_PID 2>/dev/null
    echo "Services stopped."
}

# Trap Ctrl+C and call cleanup
trap cleanup SIGINT SIGTERM

# Wait for both processes
wait $MCP_PID $RAG_PID