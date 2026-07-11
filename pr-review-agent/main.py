import argparse
import os
import sys

from github_client import fetch_pr_diff, get_pr_head_sha
from agent import review_pr
from tools import configure_tools


def _print_banner(repo: str, pr_number: int, dry_run: bool) -> None:
    print("=" * 60)
    print(f"  PR Review Agent — {repo} PR #{pr_number}")
    if dry_run:
        print()
        print("  *** DRY-RUN MODE: no comments will be posted ***")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous PR Review Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python main.py --repo owner/repo --pr 42 --token ghp_...",
    )
    parser.add_argument("--repo", required=True, help="Repository in 'owner/repo' format")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number")
    parser.add_argument("--token", required=True, help="GitHub Personal Access Token (PAT)")
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Skip agentic tool-calling; always run ruff and bandit before prompting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the review verdict without posting a GitHub comment",
    )
    args = parser.parse_args()

    is_dry_run = args.dry_run or os.environ.get("DRY_RUN", "").lower() == "true"
    _print_banner(args.repo, args.pr, is_dry_run)

    try:
        print("Fetching PR metadata...")
        head_sha = get_pr_head_sha(args.repo, args.pr, args.token)
        print(f"Head SHA: {head_sha}")

        configure_tools(repo=args.repo, token=args.token, pr_number=args.pr, head_sha=head_sha)

        print("Fetching PR diff...")
        diff_files = fetch_pr_diff(args.repo, args.pr, args.token)

        if not diff_files:
            print("No modified files found in this PR. Exiting.")
            sys.exit(0)

        print(f"\nModified files ({len(diff_files)}):")
        for f in diff_files:
            size = len(f["patch_text"])
            truncated = " [truncated]" if size >= 4000 else ""
            print(f"  • {f['file_path']}  ({size} chars{truncated})")

        print("\nRunning LLM review (model: qwen2.5-coder:7b)...")
        verdict = review_pr(diff_files, use_tool_calling=not args.no_tools, repo=args.repo, token=args.token)

        print("\n" + "=" * 60)
        print("VERDICT")
        print("=" * 60)
        print(f"Decision : {verdict.get('decision')}")
        print(f"Summary  : {verdict.get('summary')}")
        print("-" * 60)
        print("Reasoning:")
        print(verdict.get("reason"))
        print("=" * 60)

    except PermissionError as exc:
        print(f"\n[Access Denied] {exc}", file=sys.stderr)
        print("Check your PAT is valid and has the required 'repo' scope.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as exc:
        print(f"\n[Not Found] {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"\n[Invalid Input] {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"\n[Runtime Error] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n[Unexpected Error] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
