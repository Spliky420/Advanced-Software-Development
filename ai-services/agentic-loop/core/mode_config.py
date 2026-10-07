from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModeConfig:
    key: str
    label: str
    prompt_family: str
    implementation_prompts: tuple[str, ...]
    review_prompts: tuple[str, ...] = field(default_factory=tuple)


def build_mode_config() -> dict[str, ModeConfig]:
    """Single source of truth for what prompt files every review mode
    needs, replacing the old one-flat-file-per-mode convention
    (prompts/{mode}.txt). Every mode now declares an ordered
    implementation_prompts sequence (system/task/context, concatenated
    for Observe) and an optional review_prompts sequence (Adapt) -- a
    mode with no review_prompts gets no second pass, same as "mcp" gets
    a real one today via core/mcp_pipeline.py while the others didn't.
    """
    return {
        "db": ModeConfig(
            key="db",
            label="DB",
            prompt_family="service",
            implementation_prompts=(
                "implementation/system_prompt.txt",
                "implementation/task_prompt.txt",
                "implementation/context_prompt.txt",
            ),
        ),
        "endpoints": ModeConfig(
            key="endpoints",
            label="Endpoints",
            prompt_family="service",
            implementation_prompts=(
                "implementation/system_prompt.txt",
                "implementation/task_prompt.txt",
                "implementation/context_prompt.txt",
            ),
        ),
        "architecture": ModeConfig(
            key="architecture",
            label="Architecture",
            prompt_family="lab4",
            implementation_prompts=(
                "implementation/architecture_system_prompt.txt",
                "implementation/architecture_task_prompt.txt",
            ),
            review_prompts=("review/agent_review_prompt.txt",),
        ),
        "devops": ModeConfig(
            key="devops",
            label="DevOps",
            prompt_family="lab5",
            implementation_prompts=("implementation/devops_pipeline_review_prompt.txt",),
            review_prompts=("review/devops_evidence_review_prompt.txt",),
        ),
        "mcp": ModeConfig(
            key="mcp",
            label="MCP",
            prompt_family="lab7",
            # NOT tool_selection_prompt.txt: that file is written for
            # mcp_pipeline.run_mcp_review's placeholder-substituting,
            # pick-a-tool-for-a-live-question flow (see its own
            # "{{USER_REQUEST}}" and "Selected Tool:" output format,
            # which fights with this mode's generic validation prompt).
            # This mode gets its own dedicated task prompt instead.
            implementation_prompts=("implementation/mcp_task_prompt.txt",),
            review_prompts=("review/integration_review_prompt.txt",),
        ),
        "rag": ModeConfig(
            key="rag",
            label="RAG",
            prompt_family="lab8",
            # Follow same pattern as mcp mode - gets dedicated task prompt
            implementation_prompts=("implementation/rag_task_prompt.txt",),
            review_prompts=("review/integration_review_prompt.txt",),
        ),
    }
