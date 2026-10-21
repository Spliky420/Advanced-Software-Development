from datetime import datetime, timezone
from pathlib import Path

from core import (
    db_collector,
    endpoints_collector,
    architecture_collector,
    devops_collector,
    mcp_collector,
    rag_collector,
    mcp_pipeline,
)
from core.mode_config import build_mode_config


MODE_CONFIG = build_mode_config()

# One module per mode, each exposing collect(repo_root, student) -> str.
# "mcp" lets mode="mcp" run through this same generic orchestrator, in
# addition to the bespoke question-answering flow in mcp_pipeline.py.
COLLECTORS = {
    "db": db_collector.collect,
    "endpoints": endpoints_collector.collect,
    "architecture": architecture_collector.collect,
    "devops": devops_collector.collect,
    "mcp": mcp_collector.collect,
    "rag": rag_collector.collect,
}


def load_prompt_files(
    app_dir: Path,
    relative_paths: tuple[str, ...]
) -> str:
    """Concatenates a mode's ordered prompt files (e.g. system, task,
    context) into one prompt -- replaces the old one-flat-file-per-mode
    convention (prompts/{mode}.txt), which gave every mode a single file
    mixing persona, checklist, and evidence-reading instructions together.
    """

    return "\n\n".join(
        (app_dir / "prompts" / relative_path).read_text(encoding="utf-8")
        for relative_path in relative_paths
    )


def collect_evidence(
    mode: str,
    repo_root: Path,
    student: str
) -> str:

    collector = COLLECTORS[mode]

    return collector(
        repo_root,
        student
    )


def run_agentic_review(
    mode: str,
    app_dir: Path,
    repo_root: Path,
    ai,
    student: str = "all",
    student_label: str = "All Students",
):
    config = MODE_CONFIG[mode]

    print()
    print("======================================")
    print(f"REVIEW TARGET: {config.label.upper()}")
    print(f"TARGET: {student_label}")
    print("======================================")

    # =====================================
    # PLAN
    # =====================================

    print()
    print("[PLAN]")

    print(
        f"Plan a {config.label} review for "
        f"{student_label}."
    )

    review_prompt = load_prompt_files(
        app_dir,
        config.implementation_prompts
    )

    # =====================================
    # ACT
    # =====================================

    print()
    print("[ACT]")

    print(
        f"Collecting {config.label} evidence "
        f"for {student_label}..."
    )

    evidence = collect_evidence(
        mode,
        repo_root,
        student
    )

    if mode == "mcp":
        return _run_mcp_mode(
            config,
            app_dir,
            ai,
            evidence,
            student_label,
        )

    full_prompt = f"""
{review_prompt}

========================================
REVIEW TARGET
========================================

{student_label}

========================================
PROJECT EVIDENCE
========================================

{evidence}
"""

    # =====================================
    # OBSERVE
    # =====================================

    print()
    print("[OBSERVE]")

    print(
        "Sending repository evidence "
        "to Ollama for review..."
    )

    result = ai.run(
        full_prompt
    )

    print(result)

    # =====================================
    # ADAPT
    # =====================================

    print()
    print("[ADAPT]")

    if not config.review_prompts:
        print(
            "No review pass configured for this mode -- "
            "use the findings above to determine whether changes are required."
        )
        return result

    review_instructions = load_prompt_files(
        app_dir,
        config.review_prompts
    )

    adapt_prompt = f"""
{review_instructions}

Implementation Findings:
{result}

Observed Evidence:
{evidence}
"""

    print("Asking Ollama to validate those findings against the evidence...")

    review_result = ai.run(adapt_prompt)

    print(review_result)

    _write_review_report(
        app_dir,
        config,
        student_label,
        result,
        review_result,
    )

    return review_result


def _run_mcp_mode(
    config,
    app_dir: Path,
    ai,
    evidence: str,
    student_label: str,
) -> str:
    """MCP's own Observe/Adapt shape, distinct from the generic
    concatenate-every-prompt-file-and-call-once path every other mode
    uses. tool_selection_prompt.txt and integration_review_prompt.txt
    are written for mcp_pipeline.py's placeholder-substituting flow
    (`.replace("{{...}}", ...)`), not raw concatenation -- loading them
    through load_prompt_files() would leave literal "{{USER_REQUEST}}"
    text sitting in the prompt sent to the model. This calls
    mcp_pipeline.build_implementation_prompt/build_review_prompt
    directly instead -- the same two functions run_mcp_integration_review
    already uses -- so MCP evidence gets the assembly it was actually
    designed for.
    """
    print()
    print("[PLAN]")
    print(f"Loading prompt family: {config.prompt_family}")

    task_prompt = (
        app_dir / "prompts" / config.implementation_prompts[0]
    ).read_text(encoding="utf-8")

    system_prompt = (
        "You are a precise MCP integration validator. "
        "Use only supplied evidence and reply in at most 40 words."
    )

    implementation_user_prompt = mcp_pipeline.build_implementation_prompt(
        task_prompt, evidence
    )

    print()
    print("[OBSERVE]")
    print("Running MCP implementation model...")

    implementation_output = ai.run(f"{system_prompt}\n\n{implementation_user_prompt}")

    if implementation_output.startswith("REVIEW ERROR:"):
        print("MCP implementation model failed.")
        return f"MODEL FAILED: {implementation_output}"

    print(implementation_output)

    print()
    print("[ADAPT]")

    review_system_prompt = (
        app_dir / "prompts" / config.review_prompts[0]
    ).read_text(encoding="utf-8")

    review_user_prompt = mcp_pipeline.build_review_prompt(implementation_output, evidence)

    print("Running MCP review model...")

    review_output = ai.run(f"{review_system_prompt}\n\n{review_user_prompt}")

    print(review_output)

    _write_review_report(
        app_dir,
        config,
        student_label,
        implementation_output,
        review_output,
    )

    return (
        f"OBSERVE: {evidence}\n\n"
        f"IMPLEMENTATION: {implementation_output}\n"
        f"REVIEW: {review_output}"
    )


def _write_review_report(
    app_dir: Path,
    config,
    student_label: str,
    implementation_output: str,
    review_output: str,
) -> None:
    report_path = app_dir / "reports" / f"{config.key}-review.md"
    report_path.write_text(
        f"""# {config.label} Review

Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
Target: {student_label}

## Implementation Findings (Observe)
{implementation_output}

## Review (Adapt)
{review_output}
""",
        encoding="utf-8",
    )