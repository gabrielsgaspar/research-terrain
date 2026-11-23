"""Decision 0021, build side: contradictions inside a task, and waiting for main.

Plain code, never a model. agent-build's workflow runs this file as a script
(`python3 -I contradiction.py <command>`), from a copy taken from main before
the builder starts, so the builder's commits cannot change the check. It uses
only the standard library for that reason.

Commands (see `main`):
- `check-result`: the builder's structured result, the quote check (point 4
  of the decision), Comment C and the PR body's contradiction section.
- `failing-ids`: the failing pytest node ids of a log.
- `decide-waiting`: "waiting_for_main" or "task_fault" (point 6).
- `render-waiting`: Comment W.

The two comments are read by the tick (decision 0021, session D2). Their
formats are part of the interface and are pinned byte for byte by
tests/test_contradiction.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CONTRADICTION_HEADING = "## Agent build: contradiction (decision 0021)"
WAITING_HEADING = "## Agent build: waiting for main (decision 0021)"
SECTION_HEADING = "## Contradiction (decision 0021)"

MAX_QUOTE_CHARS = 5000
MAX_ID_CHARS = 200
MAX_SOURCE_CHARS = 200
LEVELS = range(1, 7)  # point 2 of the decision: 1 (AGENTS.md, decisions) to 6 (agent notes)
NAMED_SOURCES = ("issue", "plan", "review")

# The same prefixes the workflows scan for before anything is posted.
TOKEN_PREFIX = re.compile(r"sk-ant-|lsv2_|gh[pousr]_|github_pat_|-----BEGIN|ya29\.|olp_")
RUN_ID = re.compile(r"^[0-9]{1,15}$")
SHA12 = re.compile(r"^[0-9a-f]{12}$")
PATH_SOURCE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
# A pytest node id: no whitespace, no comma, no leading dash, never a comment marker.
NODE_ID = re.compile(r"^[A-Za-z0-9_.][^\s,]*$")
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S.*)$")


# --- quotes -----------------------------------------------------------------


def collapse(text: str) -> str:
    """Whitespace collapsed to single spaces, the only normalisation a quote gets."""
    return " ".join(str(text).split())


def valid_source(source: object) -> bool:
    """issue, plan, review, or a repository path (no `..`, no absolute path)."""
    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        return False
    if source in NAMED_SOURCES:
        return True
    return (
        bool(PATH_SOURCE.match(source))
        and ".." not in source.split("/")
        and not source.endswith("/")
    )


def quote_problem(quote: object, read_source) -> str | None:
    """None if the quote is well formed and appears word for word in its source."""
    if not isinstance(quote, dict):
        return "a quote is not an object with text, source and level"
    text, source, level = quote.get("text"), quote.get("source"), quote.get("level")
    if not isinstance(text, str) or not collapse(text):
        return "a quote has no text"
    if len(text) > MAX_QUOTE_CHARS:
        return f"a quote is longer than {MAX_QUOTE_CHARS} characters"
    if not valid_source(source):
        shown = json.dumps(source)[:120]
        return f"a quote names a source that is not issue, plan, review or a repo path: {shown}"
    if isinstance(level, bool) or not isinstance(level, int) or level not in LEVELS:
        return f"the quote from {source} has a level that is not an integer from 1 to 6"
    shown = collapse(text)[:80]
    body = read_source(source)
    if body is None:
        return f"the quote {json.dumps(shown)} names the source {source}, which could not be read"
    if collapse(text) not in collapse(body):
        return f"the quote {json.dumps(shown)} is not word for word in its named source, {source}"
    return None


def quote_lines(quote: dict) -> list[str]:
    """One quote as Markdown: its text in a fenced block that no line of the text can close."""
    text = str(quote["text"]).strip("\n")
    # HTML comment markers are defused, so only the workflow's own marker is one.
    text = text.replace("<!--", "< !--").replace("-->", "-- >")
    fence = "~" * max([4, *(len(m) + 1 for m in re.findall(r"~+", text))])
    return [f"{fence}text", text, fence]


def render_contradiction(quotes: list[dict], run_id: str) -> str:
    """Comment C. First line and last line are fixed; the tick reads the last line."""
    if len(quotes) != 2:
        raise ValueError("a contradiction has exactly two quotes")
    if not RUN_ID.match(str(run_id)):
        raise ValueError("run id must be a number")
    lines = [CONTRADICTION_HEADING, ""]
    for number, quote in enumerate(quotes, 1):
        lines += [f"Quote {number}. Source: {quote['source']}. Level: {quote['level']}.", ""]
        lines += quote_lines(quote) + [""]
    lines.append(f"<!-- agent-build-contradiction: run {run_id} -->")
    return "\n".join(lines)


def render_section(resolved: list[dict]) -> str:
    """The PR body's "## Contradiction (decision 0021)" section (point 3 of the decision)."""
    lines = [SECTION_HEADING, ""]
    lines += [
        "The builder met instructions that cannot both hold, applied the winner and tested it.",
        "",
    ]
    for number, item in enumerate(resolved, 1):
        winner, loser = item["winner"], item["loser"]
        lines += [f"### Contradiction {number}", ""]
        for label, quote in (("Winner", winner), ("Loser", loser)):
            lines += [f"**{label}** (source: {quote['source']}, level {quote['level']}):", ""]
            lines += quote_lines(quote) + [""]
        higher = winner["level"] < loser["level"]
        rule = "higher level" if higher else "same level, the stricter"
        lines += [f"**Why it won** ({rule}): {collapse(item['why'])}", ""]
        tests = item["tests"]
        lines += ["**Tests written for the winner:**", ""]
        lines += [f"- `{collapse(t)}`" for t in tests] or ["- none listed"]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


@dataclass
class Outcome:
    """What the quote check decided. kind: ok, contradiction or blocked."""

    kind: str
    reason: str = ""
    comment: str = ""
    section: str = ""
    quotes: list[dict] = field(default_factory=list)


def _blocked(reason: str) -> Outcome:
    return Outcome("blocked", reason)


def check_result(result: object, read_source, run_id: str) -> Outcome:
    """Point 4 of the decision: every quote must appear word for word in its source.

    A `done` result without contradictions is ok. A `done` result with
    `contradictions_resolved` is ok only if all its quotes pass. A
    `contradiction` result needs exactly two quotes, both passing; it then
    carries Comment C. Anything else that fails is `blocked`, so decision
    0019's fix round applies, and the reason names the quote that failed.
    """
    if not isinstance(result, dict):
        return _blocked("The builder's result is not an object.")
    status = result.get("status")
    if status == "contradiction":
        quotes = result.get("quotes")
        if not isinstance(quotes, list) or len(quotes) != 2:
            count = len(quotes) if isinstance(quotes, list) else 0
            return _blocked(
                f"The builder returned contradiction with {count} quotes; it needs exactly two."
            )
        for quote in quotes:
            problem = quote_problem(quote, read_source)
            if problem:
                return _blocked(f"The builder returned contradiction, but {problem}.")
        if (quotes[0]["text"], quotes[0]["source"]) == (quotes[1]["text"], quotes[1]["source"]):
            return _blocked(
                "The builder returned contradiction, but both quotes are the same text and source."
            )
        comment = render_contradiction(quotes, run_id)
        if TOKEN_PREFIX.search(comment):
            return _blocked(
                "The builder returned contradiction, but its quotes looked like a token."
            )
        reason = "The builder found a contradiction where neither is stricter (decision 0021)."
        return Outcome("contradiction", reason, comment=comment, quotes=quotes)
    if status != "done":
        return _blocked("The builder did not return done or contradiction.")
    resolved = result.get("contradictions_resolved") or []
    if not isinstance(resolved, list):
        return _blocked("contradictions_resolved is not a list.")
    for number, item in enumerate(resolved, 1):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("why"), str)
            or not collapse(item["why"])
        ):
            return _blocked(f"contradictions_resolved item {number} has no `why`.")
        tests = item.get("tests")
        if not isinstance(tests, list) or not all(isinstance(t, str) for t in tests):
            return _blocked(f"contradictions_resolved item {number} has no list of tests.")
        for side in ("winner", "loser"):
            problem = quote_problem(item.get(side), read_source)
            if problem:
                return _blocked(f"contradictions_resolved item {number}: {problem} ({side}).")
        if item["winner"]["level"] > item["loser"]["level"]:
            return _blocked(
                f"contradictions_resolved item {number}: the winner ranks below the loser."
            )
    if not resolved:
        return Outcome("ok")
    section = render_section(resolved)
    if TOKEN_PREFIX.search(section):
        return _blocked("The contradiction section looked like it contained a token.")
    return Outcome("ok", section=section)


def make_reader(issue: Path, plan: Path, review: Path, base: str, git_dir: str = "."):
    """read_source(name) -> text or None: issue, plan, review, or a file on main (`base`)."""

    def read(source: str) -> str | None:
        files = {"issue": issue, "plan": plan, "review": review}
        if source in files:
            try:
                return files[source].read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        if not re.fullmatch(r"[0-9a-f]{40}", base or ""):
            return None
        cmd = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "submodule.recurse=false",
            "cat-file",
            "blob",
            f"{base}:{source}",
        ]
        done = subprocess.run(cmd, cwd=git_dir, capture_output=True, check=False)
        return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None

    return read


# --- waiting for main -------------------------------------------------------


def failing_ids(log: str) -> list[str] | None:
    """The failing node ids of a pytest log (its short summary), in order, without repeats.

    None when there is nothing usable: no failing id, or an id that cannot be
    carried (a space or comma in it, over 200 characters, an unclosed
    bracket). The caller then treats the failure as the task's.
    """
    found: list[str] = []
    for line in log.splitlines():
        match = FAILED_LINE.match(line.rstrip())
        if not match:
            continue
        node = _node_id(match.group(1))
        if node is None:
            return None
        if not valid_node_id(node):
            return None
        if node not in found:
            found.append(node)
    return found or None


def _node_id(rest: str) -> str | None:
    """The id at the start of `rest`: it ends at the first " - " outside square brackets."""
    depth = 0
    for i, char in enumerate(rest):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif depth == 0 and rest.startswith(" - ", i):
            return rest[:i].strip()
    return rest.strip() if depth == 0 else None


def valid_node_id(node: str) -> bool:
    return (
        bool(NODE_ID.match(node))
        and len(node) <= MAX_ID_CHARS
        and "<!--" not in node
        and "-->" not in node
    )


def decide_waiting(task_ids: list[str], main_log: str) -> str:
    """waiting_for_main if every id also fails on main, otherwise task_fault (point 6)."""
    if not task_ids:
        return "task_fault"
    on_main = failing_ids(main_log)
    if on_main is None:
        return "task_fault"
    return "waiting_for_main" if all(node in on_main for node in task_ids) else "task_fault"


def render_waiting(ids: list[str], run_id: str, main_sha: str) -> str:
    """Comment W. First line and last line are fixed; the tick reads the last line."""
    if not ids or not all(valid_node_id(i) for i in ids):
        raise ValueError("test ids must be non-empty node ids without spaces or commas")
    if not RUN_ID.match(str(run_id)):
        raise ValueError("run id must be a number")
    if not SHA12.match(main_sha[:12]) or len(main_sha) < 12:
        raise ValueError("main sha must start with 12 hex characters")
    lines = [WAITING_HEADING, ""] + list(ids) + [""]
    lines.append(
        f"<!-- agent-build-waiting-for-main: run {run_id} sha {main_sha[:12]} "
        f"tests {','.join(ids)} -->"
    )
    return "\n".join(lines)


# --- GitHub step outputs ----------------------------------------------------


def write_outputs(path: str, values: dict[str, str]) -> None:
    """Append name=value (or a delimited block, if the value has a newline) to $GITHUB_OUTPUT."""
    with open(path, "a", encoding="utf-8") as out:
        for name, value in values.items():
            if "\n" in value:
                delimiter = f"EOF_{secrets.token_hex(16)}"
                out.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
            else:
                out.write(f"{name}={value}\n")


# --- command line -----------------------------------------------------------


def _cmd_check_result(args) -> int:
    try:
        result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result = None
    reader = make_reader(Path(args.issue), Path(args.plan), Path(args.review), args.base)
    outcome = check_result(result, reader, args.run)
    out: dict[str, str] = {"kind": outcome.kind}
    if outcome.kind == "ok":
        if outcome.section:
            Path(args.section_out).write_text(outcome.section, encoding="utf-8")
            print("The builder's contradictions all quote their sources word for word.")
        write_outputs(os.environ["GITHUB_OUTPUT"], out)
        return 0
    out["reason"] = outcome.reason
    if outcome.kind == "contradiction":
        out["contradiction_comment"] = outcome.comment
    else:
        out["fixable"] = "fresh"  # decision 0019: blocked, so its fix round starts from main
    write_outputs(os.environ["GITHUB_OUTPUT"], out)
    print(f"::error::{outcome.reason}")
    return 1


def _cmd_failing_ids(args) -> int:
    ids = failing_ids(Path(args.log).read_text(encoding="utf-8", errors="replace"))
    if not ids:
        return 1
    print("\n".join(ids))
    return 0


def _cmd_decide_waiting(args) -> int:
    ids = [line for line in Path(args.ids).read_text(encoding="utf-8").splitlines() if line]
    log = Path(args.main_log).read_text(encoding="utf-8", errors="replace")
    print(decide_waiting(ids, log))
    return 0


def _cmd_render_waiting(args) -> int:
    ids = [line for line in Path(args.ids).read_text(encoding="utf-8").splitlines() if line]
    comment = render_waiting(ids, args.run, args.sha)
    if args.github_output:
        write_outputs(os.environ["GITHUB_OUTPUT"], {"waiting": "true", "waiting_comment": comment})
    else:
        print(comment)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-result")
    for name in ("result", "issue", "plan", "review", "base", "run", "section-out"):
        p.add_argument(f"--{name}", required=True)
    p.set_defaults(func=_cmd_check_result)
    p = sub.add_parser("failing-ids")
    p.add_argument("log")
    p.set_defaults(func=_cmd_failing_ids)
    p = sub.add_parser("decide-waiting")
    p.add_argument("--ids", required=True)
    p.add_argument("--main-log", required=True)
    p.set_defaults(func=_cmd_decide_waiting)
    p = sub.add_parser("render-waiting")
    for name in ("ids", "run", "sha"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--github-output", action="store_true")
    p.set_defaults(func=_cmd_render_waiting)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
