#!/usr/bin/env python3
"""
Generate the RailCall community "cult kit" ENTIRELY on the local Groq cascade — zero Claude tokens.
Uses railcall_support_brain.groq_chat (stdlib + Groq, UA-fixed) to write each deliverable, then saves
them to ../community/. Run:  python3 bot/generate_community_kit.py

Deliverables (from the cult-following playbook):
  MANIFESTO.md          — the creed / identity + the enemy (surveillance-AI). The cornerstone.
  CONDUCTORS.md         — the elite champion program, designed per the ambassador research.
  privacy-support.md    — privacy-as-a-support-feature (provable trust page copy).
  rituals.md            — recurring community ritual prompts (feed to the Groq webhook poster).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import railcall_support_brain as brain

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "community")
os.makedirs(OUT, exist_ok=True)

# Shared grounding so every piece stays factually on-brand (never invents features/prices).
FACTS = brain.BASE_FACTS + "\nBrand voice: confident, direct, developer-native, zero corporate fluff, zero " \
        "hype clichés ('revolutionary', 'game-changing', 'unlock'). Rail/train metaphor is on-brand " \
        "(Conductors, the Crew, on the rails, all aboard, receipts). Never reveal HOW the product is built " \
        "internally — only WHAT it does + the proof."

JOBS = {
    "MANIFESTO.md": (
        "Write RailCall's community MANIFESTO — a short, punchy creed developers would pin and rally around. "
        "It must name an enemy and an identity: the surveillance-AI status quo (a Stanford study found all six "
        "leading AI vendors train on users' chat data by default, with humans reading transcripts) vs. RailCall "
        "(you own 100% of your code; your keys, files and data never leave your machine; we never train on you; "
        "every agent action is gated, approved, logged, and sealed in a signed receipt you can verify offline). "
        "Make a reader feel they're joining something with a spine. 150–230 words. Output ONLY the manifesto "
        "(a title line + the creed). No preamble."),
    "CONDUCTORS.md": (
        "Design RailCall's community champion program, called 'Conductors' (rail theme). Follow these hard rules "
        "from 2025 ambassador-program research: intrinsic motivation beats swag — the real rewards are ACCESS, "
        "INFLUENCE (roadmap input), early features, and a private channel with the team, plus genuine status; "
        "criteria must be ruthlessly clear; it's an ONGOING commitment, never a one-time badge; rewards scale "
        "with contribution; keep it SMALL and hard to earn (chasing size dilutes the status and kills it). "
        "Write a concise spec with sections: What a Conductor is · How you earn it · What Conductors get · How "
        "it stays elite (ongoing, not a destination) · What we will NEVER do (no rigid quotas, no optimizing for "
        "headcount, no points/leaderboards). ~260 words."),
    "privacy-support.md": (
        "Write the copy for a short trust page titled 'Your data, in support and everywhere else'. Facts to use "
        "(do not exceed them): RailCall is local-first — keys, files, workflow data and generated code never "
        "leave the user's machine; the billing gateway is a transaction register, not a data sink (it only ever "
        "sees a hashed key + a one-time nonce); every governed flow mints an Ed25519 signed receipt verifiable "
        "offline; and our support AI runs on an API that does NOT train on your data by default and offers Zero "
        "Data Retention — versus the industry default where leading vendors train on user chats and humans read "
        "the transcripts. Make it a confident, provable trust statement (WHAT + benefit + the proof). Do NOT "
        "describe how the product is engineered internally. ~200 words."),
    "rituals.md": (
        "Write 6 short recurring RailCall community-ritual prompts for Discord, punchy and rail-themed, no "
        "hashtags, each 1–2 sentences: (1) weekly 'what did you ship — drop the receipt' showcase, (2) 'Receipt "
        "of the Week' recognition, (3) a values/ownership reminder (you own your code, nobody trains on you), "
        "(4) a warm 'welcome aboard, new Crew' nudge, (5) a build-in-public hot-take prompt, (6) a 'stuck? the "
        "assistant answers in seconds, humans follow up' support nudge. Output as a numbered list, prompts only."),
}


def main():
    if not brain.GROQ_API_KEY:
        sys.exit("No GROQ key (env or ~/.railcall/groq_key).")
    print("Generating the community kit on the local Groq cascade (%s)...\n" % ", ".join(brain.GROQ_MODELS))
    for fname, prompt in JOBS.items():
        msgs = [{"role": "system", "content": FACTS}, {"role": "user", "content": prompt}]
        text = brain.groq_chat(msgs, max_tokens=900, temperature=0.55)
        if not text:
            print("  ✗ %-20s Groq returned nothing (skipped)" % fname)
            continue
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
            f.write(text.strip() + "\n")
        print("  ✓ %-20s %d chars" % (fname, len(text)))
    print("\nWrote to %s" % OUT)


if __name__ == "__main__":
    main()
