# Hackathon research corpus (2026-10-18)

Inputs behind `../../HACKATHON_PLAN.md`. Everything here was produced by research agents and fact-checkers; treat the `corrections` fields as authoritative over the digests, and verify any claim before relying on it on the robot.

- `brief.md`: hackathon facts, our hardware and software, and the seven fact-checked research digests (Gemma 4 and runtimes, LiteRT/LiteRT-LM, the G1, judging history, the Android/Pixel path, prior art and demo primitives, hardware-award stacking) with open questions.
- `research_full.json`: every claim with evidence, source URLs, confidence, and the fact-checker's verdict per load-bearing claim.
- `brainstorm_concepts.json`: 17 concepts from six ideation angles (stage-demo, expected value, feasibility, Gemma-native, human interaction, learn-from-watching), each with demo script, architecture, prize targets, build plan, risks and fallback.
- `judge_scores.json`: three judge personas' scores, top-3 picks, grafts and warnings. Note: the summed ranking merged two unrelated concepts named "Show Me Once"; read the per-judge top-3 instead.
- `red_team_findings.json`: technical, rules and demo-day attacks on the synthesized plan, with fixes.
- `plan_before_red_team.md`: the synthesized plan before the red team (kept the EmbeddingGemma 2 memory tier and a stage walk that the revision cut).
