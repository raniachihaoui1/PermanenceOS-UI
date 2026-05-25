from __future__ import annotations

import argparse

from _runtime.bootstrap import bootstrap
from graph import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PermanenceOS structural design agent (LM Studio + local Python)"
    )
    parser.add_argument("prompt", help="Your instruction, e.g. 'add a structural grid'")
    args = parser.parse_args()

    ctx = bootstrap()
    print(f"LLM endpoint : {ctx.llm.openai_api_base}")
    print(f"Model        : {ctx.llm.model_name}")
    print(f"Output file  : {ctx.edited_layout_path}\n")

    response = run_agent(args.prompt, ctx)
    print("\n" + response)


if __name__ == "__main__":
    main()
