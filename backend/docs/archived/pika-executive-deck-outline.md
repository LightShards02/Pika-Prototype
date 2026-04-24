# PIKA Executive Deck Outline

**Goal:** a 15-minute leadership presentation introducing PIKA clearly and credibly  
**Recommended length:** 10 slides  
**Primary audience:** manager / executive sponsor  
**Instruction to slide-creating agent:** use the text below as the default on-slide content; tighten phrasing only if needed for fit, but preserve the meaning and structure

## Slide 1: Title

**Slide purpose**

- Open with a crisp definition of PIKA
- Signal that this is about controlled AI-assisted software delivery, not just "an AI coding tool"

**Text to display on the slide**

**Title**

PIKA  
AI-Assisted Software Delivery With Control, Traceability, and Human Oversight

**Subtitle**

A platform for moving from requirements and design to implementation and resolution through a governed multi-agent workflow

**Optional footer line**

Runtime orchestration + desktop operating experience

**Visual / layout instructions**

- Use a clean title slide with text on the left 40% to 45% of the slide.
- Reserve the right 55% to 60% for a strong hero visual.
- Preferred hero visual: a polished desktop-app screenshot or product montage showing workflow, documents, and progress.
- If a real screenshot is used, crop it so UI chrome is visible but small text is not relied on for readability.
- Add 2 or 3 subtle callout labels on the screenshot only if they are legible at presentation size, for example: `Workflow`, `Progress`, `Resolution`.
- Keep the slide visually clean; do not add bullet points beyond the subtitle/footer line.

## Slide 2: The Problem

**Slide purpose**

- Explain why PIKA exists
- Make the problem legible to a non-technical leader

**Text to display on the slide**

**Title**

The Problem: AI Can Generate Code, But Delivery Still Breaks Down

**Body copy**

- Raw agent workflows are hard to trust.
- Outputs are difficult to trace back to requirements and design.
- Human decisions often happen outside the system, with weak auditability.
- Teams need more than speed. They need control, reviewability, and repeatability.

**Bottom takeaway**

PIKA is designed to make AI usable inside a real software delivery process.

**Visual / layout instructions**

- Use a two-column comparison layout.
- Left column header: `Without PIKA`
- Right column header: `With PIKA`
- In the left column, use 3 to 4 short phrases such as `ad hoc prompts`, `opaque outputs`, `unclear ownership`, `manual patchwork`.
- In the right column, use 3 to 4 short phrases such as `governed workflow`, `structured outputs`, `traceable decisions`, `reviewable runs`.
- Add a simple center arrow or transition marker between the columns.
- Keep this visual conceptual; do not use technical diagrams yet.

## Slide 3: What PIKA Is

**Slide purpose**

- Define the platform clearly
- Correct the misconception that PIKA is only a CLI

**Text to display on the slide**

**Title**

What PIKA Is

**Body copy**

PIKA is a software delivery platform with two connected product surfaces:

- A governed workflow runtime that executes planning, refinement, implementation, and resolution flows
- A desktop application that makes those flows easier to launch, monitor, and operate

**Bottom takeaway**

PIKA is not just an AI prompt layer. It is a controlled operating model for AI-assisted engineering.

**Visual / layout instructions**

- Use a clean two-panel layout with equal visual weight.
- Left panel title: `Workflow Runtime`
- Left panel short labels: `orchestrates`, `validates`, `applies`, `logs`
- Right panel title: `Desktop App`
- Right panel short labels: `launches`, `monitors`, `guides`, `resolves`
- Use simple iconography for each side.
- Add a short connector line or arrow between the two panels to show they are parts of one platform, not separate products.
- Avoid screenshots on this slide unless they are very minimal; use a product model graphic instead.

## Slide 4: End-to-End Workflow

**Slide purpose**

- Show the lifecycle in one view
- Demonstrate that PIKA is a staged workflow, not a single-shot generation tool

**Text to display on the slide**

**Title**

How PIKA Moves Work Forward

**Stage labels**

1. Plan  
Create design direction from requirements

2. Refine  
Harden spec quality before code generation

3. Review  
Check for gaps, contradictions, and ambiguity

4. Map  
Trace design requirements to code

5. Implement  
Plan, batch, generate, apply, and verify changes

6. Resolve  
Turn issues and blockers into structured next actions

**Bottom takeaway**

Each stage adds control and confidence before the next one begins.

**Visual / layout instructions**

- Build this slide as a horizontal lifecycle across the full width.
- Use six evenly spaced stage cards with arrows between them.
- Each stage card should contain the stage name and one short explanatory line only.
- Highlight `Implement` slightly more than the others because it is the center of the build story.
- Under the lifecycle, add a thin secondary bar labeled `Human decision points appear where ambiguity or conflict requires review`.
- Keep the diagram simple and presentation-sized; avoid command names or CLI flags beyond the stage labels.

## Slide 5: Why The Architecture Is Different

**Slide purpose**

- Explain the core control model
- Make the architecture memorable in one slide

**Text to display on the slide**

**Title**

Why PIKA Is Different

**Body copy**

PIKA separates reasoning from mutation.

- Agents propose structured outputs
- PIKA validates those outputs against contracts and schemas
- PIKA alone applies permitted changes to documents and code
- Humans stay in the loop when the system hits ambiguity or blocking decisions

**Bottom takeaway**

This design keeps AI flexible without asking the engineering process to trust raw agent output.

**Visual / layout instructions**

- Use a centered left-to-right architecture diagram.
- Sequence:
  - `Project inputs`
  - `Agents`
  - `Structured outputs`
  - `PIKA validation + apply layer`
  - `Updated documents / code / issue trackers`
- Place the labels as 5 boxes across the slide with directional arrows.
- Use a distinct color for `PIKA validation + apply layer` so it visually reads as the control point.
- Add a small human icon or `Human review` badge above the `PIKA validation + apply layer` box with a dotted line to indicate intervention points.
- Do not include implementation-level file formats in the diagram.

## Slide 6: Desktop App Experience

**Slide purpose**

- Show that PIKA is developing into an operable product experience
- Make the workflow feel tangible

**Text to display on the slide**

**Title**

The Desktop App Makes The Workflow Operable

**Body copy**

- Launch guided workflow runs from a visual interface
- Track progress across major phases
- Handle blocking review items without dropping into raw files
- Bring more of the workflow into a usable product surface

**Bottom takeaway**

The desktop app reduces friction without weakening the underlying controls.

**Visual / layout instructions**

- Use a large real product screenshot as the main visual, occupying roughly 60% to 65% of the slide.
- Place the screenshot on the right if the body text is on the left, or on the left if that screenshot composition works better.
- Overlay 3 to 4 small numbered callouts directly on the screenshot:
  1. `Run launch`
  2. `Phase progress`
  3. `Blocking item review`
  4. `Project inputs`
- Keep callout lines short and thin; do not clutter the image.
- If multiple screenshots exist, use one large primary screenshot and one small inset showing a blocking-resolution panel.
- Do not use a collage of many small screenshots; one strong screenshot is better.

## Slide 7: Key Innovation Points

**Slide purpose**

- Summarize the strongest design differentiators
- Give leadership a short list worth remembering

**Text to display on the slide**

**Title**

What Is Innovative About PIKA

**Four innovation cards**

**1. Structured Agent Outputs**  
Agents are constrained to produce outputs that can be validated and applied safely.

**2. Human-Gated Workflow**  
When ambiguity matters, PIKA escalates it instead of guessing.

**3. Document-Centric Delivery**  
Requirements, specs, issues, and logs remain durable system assets.

**4. Controlled Implementation Loop**  
Implementation is planned, batched, verified, and traceable rather than one-shot generated.

**Bottom takeaway**

PIKA is designed to make AI operationally usable, not just technically impressive.

**Visual / layout instructions**

- Use a 2x2 card grid.
- Each card should have a short heading, one sentence of body copy, and a simple icon.
- Keep the card bodies to one line or two short lines only.
- Use consistent icon style and equal spacing; the cards should feel like product principles, not feature bullets.
- Avoid diagrams here; the card layout itself is the visual.

## Slide 8: Why It Matters

**Slide purpose**

- Convert the design story into leadership-level value
- Make the business case explicit

**Text to display on the slide**

**Title**

Why This Matters

**Value pillars**

**Faster Execution**  
Move from design intent to implementation more efficiently

**Higher Trust**  
Validate outputs, preserve audit trails, and keep humans in control

**Better Traceability**  
Connect requirements, design rows, code changes, and issues in one workflow

**Safer AI Adoption**  
Use agents inside a disciplined delivery model instead of ad hoc experiments

**Bottom takeaway**

PIKA increases leverage without giving up governance.

**Visual / layout instructions**

- Use four vertical pillars or four equal-width value blocks across the slide.
- Each pillar should have:
  - a short label
  - one supporting line
  - one icon
- Keep the bottom takeaway centered underneath the pillars.
- If you need extra emphasis, make `Higher Trust` and `Safer AI Adoption` slightly more visually prominent than the other two.

## Slide 9: Honest Boundaries

**Slide purpose**

- Preserve credibility
- Make it clear that the platform is promising and disciplined, not overclaimed

**Text to display on the slide**

**Title**

What PIKA Is Not

**Body copy**

- It is not fully autonomous software delivery
- It works best in structured engineering environments
- It intentionally adds process in exchange for control and auditability
- Its product maturity is still stronger in workflow rigor than in polished end-user simplicity

**Bottom takeaway**

The tradeoff is deliberate: more control, more traceability, and fewer blind leaps.

**Visual / layout instructions**

- Use a two-column `What PIKA is` / `What PIKA is not` format.
- Left column should be short and affirmative:
  - `Governed`
  - `Traceable`
  - `Human-supervised`
  - `Workflow-driven`
- Right column should carry the caveats:
  - `Not fully autonomous`
  - `Not zero-process`
  - `Not best for unstructured work`
  - `Not a polished general-market SaaS product`
- Keep the design restrained; this slide should feel candid and calm.

## Slide 10: Closing

**Slide purpose**

- End with a clear summary and a forward-looking message
- Leave the audience with one memorable line

**Text to display on the slide**

**Title**

PIKA Is A Strong Foundation For Controlled AI-Assisted Software Delivery

**Body copy**

- It combines multi-agent automation with guardrails, traceability, and human oversight
- It already demonstrates both a disciplined runtime model and a usable desktop direction
- The opportunity is to keep turning this governed workflow into a higher-leverage software delivery platform

**Closing line**

PIKA’s core value is not just generating output faster. It is making AI-driven delivery more reliable, reviewable, and usable.

**Visual / layout instructions**

- Use a strong closing composition rather than another dense content slide.
- Preferred visual:
  - a simplified architecture or workflow graphic faded into the background
  - or a clean desktop-app hero screenshot with low-opacity treatment behind the text
- Keep the body copy centered or left-centered over the visual.
- The closing line should be visually separated, slightly larger, and placed near the bottom third of the slide.
- Avoid adding new concepts here; this slide should feel like a confident synthesis.

## Presenter Timing Notes

- Slide 1: 45 seconds
- Slide 2: 1.5 minutes
- Slide 3: 1.5 minutes
- Slide 4: 2 minutes
- Slide 5: 2 minutes
- Slide 6: 1.5 minutes
- Slide 7: 1.5 minutes
- Slide 8: 2 minutes
- Slide 9: 1 minute
- Slide 10: 1 minute

## General Design Instructions For The Slide Agent

- Keep the deck visually clean and executive-facing.
- Prefer one strong visual per slide over multiple small visuals.
- Use diagrams to simplify, not to prove technical completeness.
- Avoid terminal screenshots.
- Prefer desktop-app screenshots, product-model diagrams, lifecycle diagrams, and architecture flows.
- Keep on-slide text concise enough to read in presentation mode, but preserve the exact messages above.
