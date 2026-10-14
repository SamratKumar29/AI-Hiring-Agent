"""Synthetic career-ops reports shaped like real model output."""

BLOCKS = "\n".join(f"## {c}) Block {c}\n" + ("Some analysis text about the role and the candidate. " * 12) for c in "ABCDEFG")


def report(score="4.2", legit="High Confidence", fence=True, url="https://x.com/jobs/1", extra_ms="", company="Acme"):
    head = (f"**URL:** {url}\n**Date:** 2026-10-12\n**Archetype:** Agentic\n**Score:** {score}/5\n"
            f"**Legitimacy:** {legit}\n**Work Auth:** unstated\n\n---\n\n")
    ms = ""
    if fence:
        ms = ("## Machine Summary\n\n```yaml\n"
              f'company: "{company}"\nrole: "AI Engineer"\nscore: {score}\nlegitimacy_tier: "{legit}"\n'
              'archetype: "Agentic"\nfinal_decision: "Apply"\nhard_stops: []\nsoft_gaps:\n  - "no cloud"\n'
              'top_strengths:\n  - "RAG"\nrisk_level: "Low"\nconfidence: "High"\nnext_action: "apply"\n'
              f'work_auth: "unstated"\nadvertised_comp: "Rs 20-30 LPA"\n{extra_ms}```\n\n')
    return head + ms + BLOCKS


TOOL_CALL = ('<tool_call><function=bash><parameter=command>ls /Users/dev/reports</parameter></function></tool_call>' * 3)
