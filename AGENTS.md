# Robot autonomy harness

## Goal

Enable the G1 to autonomously **fetch a drink from the fridge**: walk there, open and support the door with one hand, retrieve a can with the other, close the door, return, and hand over the drink. Optimize complete task execution and recovery. Image alignment and tool syntax are supporting diagnostics.

Target: G1 Edu 23 DoF, BrainCo hands, Orin NX 16 GB. Evaluate the same Orin-suitable model on the MacBook Pro and RTX 5090 server.

## Preferences

- Use first-principles reasoning and primary evidence; distinguish findings from hypotheses and missing capabilities.
- Establish capability with correct configuration before tuning performance. Avoid local optimization on tiny benchmarks or premature claims that E4B is incapable.
- Explore few-second chunks of feedback-controlled skills with concurrency, persistent holds, and replanning. Keep alternatives open; do not assume the planner must be slow or absent during execution.
- The architecture remains under review: agree on the design before implementing it. Keep code, prompts, and artifacts here; existing configuration files remain the source of truth.

## Checkpoint: 2026-09-17

- Python 3.9+ standard-library harness for llama.cpp and Google's Gemma 4 E4B QAT Q4_0 with its multimodal projector. All actions are mocks; no hardware execution.
- Three generated kitchen views, four tool interfaces, and thinking/serialization experiments; full experiment traces and source snapshots are saved. Git checkpoint: `3ec65bd`.
- Provisional defaults: brief thinking and `plan(actions)`; consult `runner-defaults.json`. The stock template is unchanged; brevity comes from a system instruction with thinking enabled. One response per trial, no final acknowledgement.
- The pilot/comparison produced 99/99 valid native-call responses. Brief prompting reduced mean reasoning tokens by 33% versus normal thinking with matching outcomes across nine trials per mode. This establishes neither general accuracy equivalence nor bounded latency.
- With brief thinking, `plan` scored 13/18 under a permissive rubric but 11/18 under the minimal-sequence check, tying `move(direction)`. It unnecessarily turned in 4/6 centered trials. Repeated seeds on three images do not establish visual generalization or navigation ability.
- Retokenized reasoning was approximately 94% of reported completion tokens in the format comparison. Plan latency had a 6.69 s median on the Mac; this does not establish Orin compatibility or performance. Chunking needs enough valid work to overlap inference.
- Local locomotion, arm IK, and hand APIs are building blocks. Autonomous door manipulation, verified grasping, whole-body coordination, and handover remain unverified.

## Next steps — proposed, not implemented

1. Review `TASK_CHUNK_PROPOSAL.md`; it supersedes the single-frame experiment as the main direction. Image alignment remains an optional diagnostic.
2. Define skill contracts, concurrency, failure/recovery, and safe cancellation. Door support and can grasp persist across chunks; command acceptance is not observed completion.
3. Compare one skill per model call, short guarded chunks, and a whole-task conditional program in complete stateful episodes. Give them identical capabilities and observations. Include failed grasp, interruption during retrieval, stale plans, and requester movement.
4. Measure complete delivery plus door closure, recovery, critical errors, and total elapsed time including stalls. Keep orchestration with simulated skills, visual grounding, and physical execution results separate. Validate target skills before hardware integration.

## Reference files

- `README.md`: operation and artifact layout. Offline checks: `python3 -B check.py`.
- `THINKING_RESULTS.md`, `FORMAT_RESULTS.md`: evidence and limitations.
- `NEXT_EXPERIMENT.md`: retrospective and superseded single-frame proposal.
