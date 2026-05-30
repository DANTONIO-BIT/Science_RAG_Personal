#!/usr/bin/env python3
"""
Gated Bridge: formats a complex query for cloud escalation via Terminal 2.
Usage:
  python3 bridge_cloud.py "problem summary"
  python3 bridge_cloud.py "problem summary" --mode secure
"""
import sys
import argparse


def ask_permission(query, mode):
    print("\n" + "=" * 55)
    if mode == "secure":
        print("🔒 SECURE MODE — PRIVATE RAG BRIDGE")
        print("=" * 55)
        print("⚠️  Verify this summary contains NO private data.")
        print("   Content from data/private/ must NEVER be included.\n")
    else:
        print("☁️  BRIDGE TO CLOUD — Digital Lab")
        print("=" * 55)

    print(f"Query to escalate:\n\n  {query}\n")

    while True:
        response = input("Send to cloud in Terminal 2? [y/N]: ").strip().lower()
        if response in ["y", "yes", "s", "si"]:
            return True
        elif response in ["n", "no", ""]:
            return False


def format_for_terminal2(query, mode):
    label = "PUBLIC CONTEXT ONLY" if mode == "secure" else "CONTEXT"
    separator = "=" * 55

    print(f"\n{separator}")
    print("✅  COPY THIS TO TERMINAL 2 (OpenCode + cloud model)")
    print(separator)
    print(f"\n[{label}]\n\n{query}\n")
    if mode == "secure":
        print("🔒 Reminder: do not paste data/private/ content in Terminal 2.")
    print(separator)
    print("\nOpen Terminal 2 → OpenCode → select cloud model → paste above.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gated bridge to cloud model")
    parser.add_argument("query", help="Problem summary to escalate")
    parser.add_argument(
        "--mode",
        choices=["digital-lab", "secure"],
        default="digital-lab",
        help="digital-lab (default) or secure (private RAG, public context only)",
    )
    args = parser.parse_args()

    if ask_permission(args.query, args.mode):
        format_for_terminal2(args.query, args.mode)
    else:
        print("\n[DENIED] Cloud escalation rejected. Resolve locally.\n")
        sys.exit(0)
