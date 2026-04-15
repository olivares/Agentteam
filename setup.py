"""
ONE-TIME SETUP — Run this once to create the agent team infrastructure.
Saves IDs to agents_config.json for use by run.py.

Usage:
    ANTHROPIC_API_KEY=<key> python setup.py
"""

import anthropic
import json
import sys
from pathlib import Path

CONFIG_FILE = Path("agents_config.json")


def setup() -> None:
    client = anthropic.Anthropic()
    print("Setting up Agent Team infrastructure...\n")

    # Shared execution environment
    print("Creating environment...")
    environment = client.beta.environments.create(
        name="agentteam-env",
        config={
            "type": "cloud",
            "networking": {"type": "unrestricted"},
        },
    )
    print(f"  Environment: {environment.id}")

    print("\nCreating agents...")

    # Researcher — web research specialist
    researcher = client.beta.agents.create(
        name="Researcher",
        model="claude-opus-4-6",
        system=(
            "You are a research specialist. Gather accurate, comprehensive information "
            "using web search and web fetch tools. Always cite sources and organize your "
            "findings clearly with key takeaways at the end."
        ),
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "web_search", "enabled": True},
                    {"name": "web_fetch", "enabled": True},
                    {"name": "write", "enabled": True},
                ],
            }
        ],
    )
    print(f"  Researcher:  {researcher.id}")

    # Coder — software engineer
    coder = client.beta.agents.create(
        name="Coder",
        model="claude-opus-4-6",
        system=(
            "You are an expert software engineer. Write clean, efficient, well-documented "
            "code with proper error handling. Follow language-specific best practices and "
            "include concise usage examples."
        ),
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": True},
                "configs": [
                    {"name": "web_search", "enabled": False},
                ],
            }
        ],
    )
    print(f"  Coder:       {coder.id}")

    # Reviewer — quality assurance
    reviewer = client.beta.agents.create(
        name="Reviewer",
        model="claude-opus-4-6",
        system=(
            "You are a meticulous code and content reviewer. Identify bugs, security issues, "
            "style violations, and logic errors. Provide specific, actionable feedback with "
            "suggested improvements and a clear verdict at the end."
        ),
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "read", "enabled": True},
                    {"name": "glob", "enabled": True},
                    {"name": "grep", "enabled": True},
                    {"name": "web_fetch", "enabled": True},
                ],
            }
        ],
    )
    print(f"  Reviewer:    {reviewer.id}")

    config = {
        "environment_id": environment.id,
        "agents": {
            "researcher": researcher.id,
            "coder": coder.id,
            "reviewer": reviewer.id,
        },
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2))

    print(f"\nConfiguration saved to {CONFIG_FILE}")
    print("Agent team is ready. Run tasks with:\n  python run.py '<task>'")


if __name__ == "__main__":
    if CONFIG_FILE.exists():
        print(f"Error: {CONFIG_FILE} already exists. Delete it to re-run setup.")
        sys.exit(1)
    setup()
