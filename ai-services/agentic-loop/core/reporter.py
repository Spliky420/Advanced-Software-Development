def print_menu() -> None:
    print("\nOptions:")
    print("  1 - DB")
    print("  2 - Endpoints")
    print("  3 - Architecture")
    print("  4 - DevOps")
    print("  5 - MCP")
    print("  0 - Exit")


def print_prompt_map(prompt_map: dict[str, str]) -> None:
    print("\nPrompt files by mode:")
    for key, value in prompt_map.items():
        print(f"  {key}: {value}")
