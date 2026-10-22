def print_menu():
    print("\nOptions:")
    print("  1 - DB")
    print("  2 - Endpoints")
    print("  3 - Architecture")
    print("  4 - DevOps")
    print("  5 - MCP")
    print("  6 - RAG")
    print("  7 - Multi-Agent Workflow")
    print("  8 - Testing Report")
    print("  9 - Cloud Deployment Report")
    print("  0 - Exit")


def print_prompt_map(prompt_map: dict[str, str]) -> None:
    print("\nPrompt files by mode:")
    for key, value in prompt_map.items():
        print(f"  {key}: {value}")
