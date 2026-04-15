"""
Run a task through the agent team pipeline:
  1. Researcher gathers context
  2. Coder implements the solution
  3. Reviewer audits the result

Usage:
    ANTHROPIC_API_KEY=<key> python run.py '<task>'

Example:
    python run.py 'Build a Python CLI tool to monitor system resources'
"""

import anthropic
import json
import sys
import time
from pathlib import Path

CONFIG_FILE = Path("agents_config.json")
SEPARATOR = "=" * 60


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print(f"Error: {CONFIG_FILE} not found. Run setup.py first.")
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text())


def run_agent(
    client: anthropic.Anthropic,
    agent_id: str,
    environment_id: str,
    task: str,
) -> str:
    """Start a session, stream the agent's response, and return the full output."""
    session = client.beta.sessions.create(
        agent=agent_id,
        environment_id=environment_id,
    )

    result_parts: list[str] = []

    try:
        with client.beta.sessions.stream(session_id=session.id) as stream:
            # Stream-first: open the stream before sending the message
            client.beta.sessions.events.send(
                session_id=session.id,
                events=[{
                    "type": "user.message",
                    "content": [{"type": "text", "text": task}],
                }],
            )

            for event in stream:
                if event.type == "agent.message":
                    for block in event.content:
                        if block.type == "text":
                            print(block.text, end="", flush=True)
                            result_parts.append(block.text)

                elif event.type == "session.status_idle":
                    # Only break on terminal idle; loop back for requires_action
                    stop_type = (
                        event.stop_reason.type
                        if hasattr(event, "stop_reason") and event.stop_reason
                        else "end_turn"
                    )
                    if stop_type != "requires_action":
                        break

                elif event.type == "session.status_terminated":
                    break

    finally:
        print()  # newline after streamed output
        time.sleep(1)  # let session status settle before archiving
        try:
            client.beta.sessions.archive(session_id=session.id)
        except Exception:
            pass  # non-critical cleanup

    return "".join(result_parts)


def orchestrate(task: str) -> None:
    """Coordinate the three-agent pipeline for a given task."""
    client = anthropic.Anthropic()
    config = load_config()

    env_id = config["environment_id"]
    agents = config["agents"]

    print(f"\n{SEPARATOR}")
    print(f"AGENT TEAM  |  {task[:55]}")
    print(SEPARATOR)

    # ── Phase 1: Research ───────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("PHASE 1 — RESEARCHER")
    print(SEPARATOR + "\n")

    research_prompt = (
        f"Research the following topic and provide a structured summary "
        f"with key facts, available approaches, and concrete examples:\n\n{task}"
    )
    research_result = run_agent(client, agents["researcher"], env_id, research_prompt)

    # ── Phase 2: Implementation ─────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("PHASE 2 — CODER")
    print(SEPARATOR + "\n")

    code_prompt = (
        f"Task: {task}\n\n"
        f"Research context (use as background, not as requirements):\n"
        f"{research_result[:3000]}\n\n"
        f"Implement a complete, production-ready solution with:\n"
        f"- Clean, well-documented code\n"
        f"- Proper error handling\n"
        f"- Usage examples"
    )
    code_result = run_agent(client, agents["coder"], env_id, code_prompt)

    # ── Phase 3: Review ─────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("PHASE 3 — REVIEWER")
    print(SEPARATOR + "\n")

    review_prompt = (
        f"Review the following implementation for: {task}\n\n"
        f"```\n{code_result[:4000]}\n```\n\n"
        f"Evaluate:\n"
        f"- Correctness and completeness\n"
        f"- Code quality and best practices\n"
        f"- Security considerations\n"
        f"- Suggested improvements\n\n"
        f"End with a concise verdict."
    )
    run_agent(client, agents["reviewer"], env_id, review_prompt)

    print(f"\n{SEPARATOR}")
    print("AGENT TEAM — DONE")
    print(SEPARATOR)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    orchestrate(" ".join(sys.argv[1:]))
