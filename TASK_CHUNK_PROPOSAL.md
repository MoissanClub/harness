# Proposal: complete the drink-fetching task with short, revisable skill plans

Status: architecture proposal for review. No new inference, simulator, robot controller, or physical execution was introduced. This supersedes single-frame alignment as the main next experiment in [NEXT_EXPERIMENT.md](NEXT_EXPERIMENT.md); that diagnostic remains available for investigating a specific failure later.

## Goal and recommendation

The objective is to autonomously get a drink from a fridge: navigate there, open and maintain the door with one hand, retrieve a can with the other, clear and close the door, return to the requester, and transfer the drink.

Evaluate the whole episode from the beginning. Start with a task-level environment in which motion skills are explicitly simulated, then replace them with grounded perception and validated robot implementations. Report these levels separately. A symbolically successful episode is not a physically successful one.

The leading architecture is a VLM that proposes short, revisable plans over feedback-controlled skills. A plan can include sequencing, overlapping activities, and observed start/stop conditions. Existing contact and grasp activities survive plan boundaries. An executor dispatches those plans, maintains their lifecycle, and feeds observations/results back to the VLM. The same VLM can maintain the task-level goal and choose the next chunk; separate software responsibilities do not imply additional language models.

Keep a strong alternative: a task program or behavior tree with event-driven model calls only for ambiguity and recovery. For a fixed drink-fetching procedure it may be simpler, faster, and more reliable than repeatedly asking a VLM to plan. The experiment must be able to choose that alternative.

## Why this is a different question from the previous benchmark

- The meaningful unit is a completed task with feedback, not a syntactically complete list emitted from a single kitchen photograph.
- A turn-only response can be valid progress when followed by a fresh observation. Conversely, a complete plan can become wrong before it finishes executing.
- The tool-call interface is an encoding. Chunk duration, feedback, concurrency, grounded goals, and ownership of active contacts are the architectural decisions.
- Model speed is a measured constraint, not the reason for decomposition. Even a fast planner needs physically meaningful completion conditions and coherent controller ownership. A planner may run while the current activity continues; there is always an active caller/executor.
- Our previous results establish native tool support and some interface sensitivity. They establish neither end-to-end competence nor the best action abstraction.
- Reliability compounds over the episode: if each of eight necessary stages succeeds with probability 0.95 conditional on all earlier stages succeeding, completion without recovery is only `0.95^8 ≈ 0.66`. This illustrative calculation explains why recovery and skill execution quality can dominate minor planner-output improvements.

## Decisions and constraints

| Decision | Proposed starting point | What can change |
| --- | --- | --- |
| Output abstraction | Parameterized skills with feedback and completion conditions | A learned joint-action chunk policy can replace a skill implementation |
| Lookahead | A few seconds of expected execution, ending earlier at information-dependent boundaries | Longer chunks in stable free motion, shorter ones around uncertain contact |
| Commitment | Execute only eligible actions; preserve active contacts and replace the pending suffix | Optional conditional branches can reduce unnecessary model calls |
| Concurrency | Allow explicitly compatible activities with shared whole-body coordination | Do not equate different arm names with physical independence |
| Model scheduling | New result, meaningful observation change, or low remaining valid lookahead | Measure the benefit/cost of periodic refresh and faster inference |
| Representation | Goal/object IDs, robot/tool status, fresh images, and typed geometry with timestamps | Perception need not be reduced to prose or repeatedly recomputed by every layer |
| Success | Observed complete episode and verified terminal conditions | Intermediate progress is a diagnostic, not a substitute for completion |

Fundamental constraints include partial observability, contact dynamics, finite actuation speed, shared body balance, and the fact that future observations do not exist yet. Current limitations include measured model latency and unverified task skills on our G1. Assumptions we can change include hand assignment, one-shot versus recurrent planning, fixed chunk duration, whether a separate model handles grounding, and which portions use learned versus engineered control.

## Mechanisms and interfaces

| Component | Inputs → outputs | Responsibility and enabling mechanism |
| --- | --- | --- |
| VLM task executive | User goal, relevant images, observed state, active activities, recent failures, available skill contracts → proposed next chunk or recovery | Semantic interpretation and task composition using the model's learned capabilities. Its proposed effects remain predictions until verified. |
| State/grounding service | RGB/depth where available, joint/hand/base state, tracking and controller feedback → timestamped object IDs, geometry, task predicates and uncertainty | Estimation and sensor association. Handle pose, hinge geometry, grasp security and human readiness each require actual estimators; a component name does not solve them. |
| Chunk executor | Proposed graph + current state + active activities → accepted/rejected starts, progress events, cancellations and terminal outcomes | Validates capabilities, prerequisites, dependencies, ownership and fresh-state assumptions. Schedules compatible work; does not invent missing motion policies. |
| Feedback skills | Grounded target + current sensor state + constraints → bounded motion goals and progress/ready/success/failure signals | Navigation, trajectory control, IK/contact control, or learned policies. They keep adapting during model inference. Each needs a tested termination condition and failure behavior. |
| Robot control/coordination | Motion goals + measured robot state → actuator commands | Enforces joint/velocity/contact limits and compatible whole-body behavior at measured control rates. Hardware control owns interpolation and continuity; high-level JSON does not make movement smooth. |

The model can receive a compact state summary plus selected images without requiring every downstream controller to use text. Geometry, transforms, trajectories and tactile/proprioceptive measurements should remain typed data where appropriate. Avoid a serial VLM → narrative description → second LLM pipeline unless it demonstrates a benefit.

### A chunk describes commitments, not a timed script

A conceptual chunk contains:

- The observation/state revision it was based on.
- Existing activities to maintain (e.g., left-hand door support).
- New skill invocations with target bindings and ordered/parallel dependencies.
- Observed conditions under which a dependent action may start.
- A stopping/replanning condition and allowed controller transitions.

Example while the fridge is already open:

```text
Maintain: left hand supports door; body remains in manipulation stance.
Right arm: reach can_7 → grasp can_7 → withdraw can_7 from door sweep.
Start grasp only when pre-grasp positioning is verified.
Start withdrawal only when a secure grasp is verified.
Continue door support until right arm and can are clear.
If support or grasp is lost, invoke the skill's supported protective behavior
and report the event; do not continue the stale suffix.
```

This can be represented by one native `submit_chunk` tool call. The syntax is illustrative; the proposal does not choose a final schema. Skill catalog defaults should own fixed resource requirements, limits, and completion semantics rather than making the VLM redeclare them on every call.

The executor distinguishes accepted, running, ready/maintaining, succeeded, failed, and safely terminated. A command acknowledgement is not evidence of physical success. Model-request cancellation is not robot-action cancellation. A new plan must explicitly transition or retain existing activities; omission must not release the door or can.

Holding a door is a persistent feedback activity. It may be ready for the other arm to work while remaining running. It should not be modeled as a terminal `hold_door()` function that returns and relinquishes control. Resource locking alone is insufficient: two arms acting on the same articulated object or body need coordinated motion/contact handling.

## Walkthrough of the entire episode

The rows are semantic phases, not a promise that each completes in one few-second chunk.

| Phase | Chunked activity | New evidence that permits progress | Example complication/recovery |
| --- | --- | --- | --- |
| Find and approach fridge | Navigate toward a grounded fridge/approach region; update approach stance | Localization/path progress, clear route, handle reachable from stance | Person blocks path: local controller pauses/reroutes; executive revises goal if blocked persists |
| Acquire and open door | Position selected hand, verify handle contact, follow an articulated opening motion | Handle contact and sufficient opening clearance | Hinge/handle geometry differs: re-ground/reposition rather than replaying an assumed pull |
| Maintain door, locate drink | Keep the supporting hand active while observing newly exposed shelves | A uniquely identified requested drink is visible/reachable | Wrong/missing drink: inspect other shelf, clarify substitution if needed, or close and report inability |
| Retrieve drink with other hand | Reach → verified grasp → withdraw; support activity continues | Stable possession and arm/can clear of the door sweep | Grasp failure: keep door supported, retry/reposition based on new observation; never claim possession from a close-hand command |
| Close door | Supporting hand guides closure while other hand retains can | Door closed and hands/can clear, then release support | Obstruction: stop closure, withdraw obstruction/adjust stance, reattempt |
| Return | Navigate to the requester's current location while maintaining grasp/carry configuration | Recipient localized and a feasible handover stance reached | Requester moved: update target; do not navigate only to an old pose |
| Handover | Present can and maintain grasp until transfer is supported | Receiver readiness/contact/transfer observation, then robot releases | Person does not take it: continue a supported hold or withdraw; elapsed time alone is not a release condition |

Hand assignment should be parameterized and geometry-dependent. The user's left-open/right-fetch example is one valid arrangement when reachability and door geometry permit it. Goal state includes the correct drink transferred, fridge closed, robot no longer retaining the can, and no unresolved active door-support task.

## Timing: few-second chunks do not erase inference latency

Let B be the remaining valid executable duration when a new request starts, and L the request-to-validated-plan latency. Ignoring other costs, unavoidable waiting at a fixed boundary is at least `max(0, L - B)` unless a feedback skill can legitimately continue. Asynchrony helps only when there is enough still-valid work to overlap.

Our prior brief-plan requests had a 6.69 s median and a 16.18 s maximum. Those are measurements of the old image task, not forecasts for this task or Orin. They nevertheless invalidate the assumption that simply buffering a 3 s chunk guarantees continuous operation. With only 3 s remaining, a 6.69 s request leaves approximately 3.69 s uncovered.

Options to compare include shorter model output/reasoning, longer validated lookahead, persistent goal-conditioned skills, event-driven task programs, or a faster planner implementation. Queuing more blind motion is not equivalent to maintaining a feedback-controlled navigation/hold/grasp goal.

Replanning must account for observation age and already executed actions. Preserve the committed prefix and active contact state, then replace a compatible pending suffix. Do not restart a grasp or pull because a delayed response proposes it again. Deadline misses and time spent in supported waiting/holding are measured outcomes.

## Alternatives and relevant evidence

| Approach | Strongest case | Main concern / when it wins |
| --- | --- | --- |
| One skill per model call | Simple feedback semantics and frequent opportunities to adapt | Repeated inference can stall progress. Wins when skills are long and internally reactive or coordination is simple. |
| Short guarded skill chunks (leading candidate) | Batches predictable decisions while preserving feedback and concurrent persistent activity | Lifecycle and compatibility rules add complexity. Must demonstrate better episode outcomes/latency, not merely fewer calls. |
| Whole-task guarded program with event-driven exceptions | Encodes stable structure and local branches once; minimizes repeated deliberation | More structure is specified or generated up front. A serious contender for this fixed procedure. |
| Learned VLA/motor-action chunks | Jointly learned visual feedback and coordinated motions can avoid an over-fragmented skill library | Needs an appropriate trained policy, data and embodiment integration. A tool schema alone does not supply these. |

Established primary results:

- [ACT](https://tonyzhaozh.github.io/aloha/) predicts chunks of joint actions from observations and demonstrations. It supports the general value of temporal abstraction; it is not evidence that a text model producing a list of skill names inherits the same control behavior.
- [SayCan](https://say-can.github.io/) grounds language-based skill selection using robot skill feasibility. This supports separating a plausible semantic plan from executable capability; it does not validate our bimanual G1 skill set.
- [Code as Policies](https://code-as-policies.github.io/) demonstrates model-generated policy programs over perception/control APIs. It motivates treating a guarded program as a strong alternative to repeated flat lists.
- [Real-Time Chunking](https://www.pi.website/research/real_time_chunking) overlaps inference/execution while conditioning the new trajectory on the committed portion. Our prefix-preservation idea is an analogy at the skill level, not a direct application of its flow/diffusion algorithm to Gemma tool calls.
- [π0.5](https://www.pi.website/blog/pi05) combines semantic subtask prediction and continuous motor chunks within a trained VLA. Hierarchical responsibility need not require separate models. This is not evidence of out-of-box compatibility with our G1/BrainCo/Orin setup.

Promising but untested combination: generate a small conditional chunk with a few locally verifiable branches (continue if grasp secure; reposition if grasp failed), execute the branch supported by actual observations, and request the next chunk asynchronously. This could bridge occasional inference delays without repeating full planning. Constrain branch depth; otherwise generation cost and verification complexity may erase the benefit. Existing program/control components are established; this exact Gemma/G1 composition is a hypothesis.

## What exists locally, and what remains unsolved

A read-only source inspection found:

- `unitree_sdk2_python/.../g1_loco_client.py`: locomotion velocity and stop interfaces. They do not themselves locate/navigate to a fridge or guarantee clearance.
- `xr_teleoperate/.../robot_arm_ik.py` and `robot_arm.py`: explicit G1_23 arm IK/controller classes. The local joint index lists five joints per arm, so arbitrary six-dimensional hand poses cannot simply be assumed reachable without coordinating other motion. IK does not establish collision-free, compliant, force-aware door manipulation or whole-body stability under door forces.
- `brainco_hand_service/README.md`: hand command/state DDS transport with normalized finger commands. Closing fingers is not verified can possession or safe human transfer.

No task-level capability is claimed merely because a lower-level API exists. This inspection was not an exhaustive capability audit or target validation. Before physical integration, each proposed skill must be classified as verified on this robot, implemented but unverified, simulated/oracle-only, or missing. The local teleoperation simulator example uses a different G1/hand configuration; no dynamics/contact parity is assumed.

The hardest unproven parts may be handle/hinge grounding, stable bimanual door interaction, reliable grasp-state estimation, and whole-body coordination. A successful VLM plan does not solve any of those by naming them.

## Revised evaluation and proposed next work

### First milestone: a complete episode under explicit skill contracts

Build a small task-level virtual kitchen with stateful, duration-bearing skill doubles and observation events. It must model hand occupancy, persistent door support, visibility changing when the door opens, object possession, door sweep clearance, movement of the requester, and failures. Skills may reject inapplicable invocations. They must not contain a hidden hardcoded next-step planner that makes all executive outputs succeed.

Use actual E4B inference latency while the virtual clock/environment continue advancing. Start with truthful oracle observations of what the agent could currently know, not hidden future states or next-action hints. This isolates orchestration. A visually grounded variant must supply images consistent with the selected branch/state; linear prerecorded success frames cannot validate counterfactual recovery.

Compare on identical scenarios and skill implementations:

1. One feedback skill per model response.
2. Short guarded chunks with persistent activities and asynchronous replanning.
3. A whole-task guarded program with event-driven exceptions.

Include a transparent handwritten task-program baseline. Its success is a valid result: it tells us whether recurring model planning is adding value on the fixed task. Measure whether the VLM helps with instruction/environment variations, not merely whether it can recite the nominal sequence.

Initial scenario families: nominal retrieval; opposite door/hand arrangement; door requiring continuous support; failed first grasp; requested drink missing or occluded; requester moving; execution duration longer than predicted; and an obsolete plan arriving after state changes. Vary both setup and disturbances in held-out combinations. Do not tune to a single known sequence or reward the simulator for repairing invalid proposals.

### Metrics

- Primary: complete task success within an episode time budget, with correct drink delivered and door closed.
- For impossible requests (e.g., no permitted drink is present), score correct inability/recovery reporting separately; it is not a successful delivery. Include false completion claims explicitly.
- Report critical errors separately: release without receiver support, close with arm/can in sweep, drop door support, conflicting resource use, and execution of stale/inapplicable actions. A rejected dangerous proposal remains an executive error even when a monitor prevents execution.
- Completion time and progress versus wall time including all inference stalls, recovery, and failures; report planner-wait fraction and latency distribution. Stage completion is diagnostic, not full success.
- Recovery rate after injected failures; repeated actions, model calls, unnecessary replans, and human interventions.
- Distinguish model proposals, accepted commands, executed actions, and observed effects in logs.
- Keep scores separate for oracle-state contract testing, visually grounded simulation/replay, and actual robot execution.

Then replace one difficult boundary with reality while preserving the end-to-end interface: for example, validated handle engagement/open-and-maintain behavior followed by retrieval and controlled closure in a matched simulator or constrained physical setup. The choice must follow a capability inventory. Do not assume a household simulator already models our exact G1_23/BrainCo dynamics. [OmniGibson](https://behavior.stanford.edu/omnigibson/overview.html) is a relevant existing household simulation platform; exact robot, asset, controller and contact fidelity must be checked before selecting it.

### What would change the recommendation?

- If one-skill feedback matches or exceeds chunking on success/time, do not add chunk complexity.
- If the whole-task guarded program wins, use it and invoke the VLM at semantic/uncertain boundaries.
- If oracle-state orchestration works but visual grounding fails, investigate perception at the failed boundaries without abandoning the episode-level goal.
- If actual skill execution dominates failure, prioritize those skills/data/controllers rather than further prompting.
- If few-second lookahead cannot cover model latency under realistic disturbances, change scheduling/representation/controller autonomy or runtime; do not hide the gap by allowing stale execution.

The first experiment should compare execution contracts and identify orchestration bottlenecks under the simulated skill contracts. It should not claim to establish autonomous physical drink fetching from successful simulated skill invocations.
