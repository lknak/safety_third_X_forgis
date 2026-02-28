# Forgis Robotics Hackathon – Context

## Challenge Overview

Build working software that makes factory machines smarter by programming them through intelligent skill composition.

You are building an **agentic intelligence layer** on top of the Forgis Skill Engine.

High-level goal (natural language) → reasoning → skill selection → executable flow → real robot execution.

No manual robot programming. The system must dynamically compose skills.

---

## What Forgis Provides

* Skill Engine (robot behaviors as reusable blocks)
* Unified cross-vendor machine abstraction layer
* 8 real robotics workstations (on-site hardware)
* Mock hackathon platform for development/testing
* Access to Google DeepMind models

---

## What Is Expected

Your system should:

1. Accept high-level goals (plain English)
2. Decompose goals into atomic robot skills
3. Compose executable skill graphs or flows
4. Execute on real hardware
5. Adapt to changing conditions
6. Demonstrate real reasoning (not simple formatting)

Judging Criteria:

* Working end-to-end pipeline
* Real task reasoning
* Creative and smart use of skill engine
* Adaptability to changes
* Clean system architecture

---

## Example Scope

User goal:
"Assemble part A onto B, then label and place in output bin."

System should:

* Parse intent
* Select relevant skills (pick, place, convey, label)
* Order them logically
* Handle constraints (missing part, different robot, bin full)
* Deploy to robot cell

---

## Available Repositories

Dobot / UR Robot Cell:
[https://github.com/ForgisX/Hackathon_Forgis_Dobot_URR](https://github.com/ForgisX/Hackathon_Forgis_Dobot_URR)

ABB YuMi Cell:
[https://github.com/ForgisX/Hackathon__FORGIS_YUMI](https://github.com/ForgisX/Hackathon__FORGIS_YUMI)

These repos contain:

* Docker-based robot drivers
* ROS 2 interfaces
* Pick-and-place pipelines
* IO triggers
* URScript integration (for UR robots)

---

## Using Google DeepMind Gemini

Recommended components:

* Gemini 3 (Vision-Language reasoning)
* Gemini Robotics ER (task orchestration)
* Agentic Vision (zoom/localize industrial objects)
* Live API (voice + real-time perception)

Use Gemini for:

* Task decomposition
* Perception understanding
* Conditional branching
* Skill graph planning
* Failure handling logic

Best Practice:

* Separate reasoning layer from execution layer
* Validate generated plans before execution
* Keep skill schema structured (JSON/tool format)
* Add guardrails for safety and constraints

---

## Suggested Architecture

User Input → Gemini Reasoning Layer → Skill Graph Builder → Forgis Skill Engine → Robot Execution

Optional modules:

* Perception node (camera + VLM)
* State monitor
* Execution validator
* Recovery planner

---

## Goal for a Strong Demo

Demonstrate:

* Natural language goal
* Dynamic skill composition
* Conditional logic
* Real hardware execution
* Visible adaptability

The more autonomous the reasoning and composition, the stronger the demo.


Hello friends! I'm Paul, the developer relations lead for Google DeepMind Robotics. I work with all of our partners through our Trusted Tester Program and am very familiar with the ecosystem, write samples/docs/other educational content, and have a background as a software engineer within the robotics space with an additional business degree if people want to bounce ideas off of me.

As you're planning out your projects, I just wanted to share some resources from GDM that might be useful for your projects.


AI Studio (https://ai.dev/) is a great starting point for trying our models and prototyping with our code generation build tool. I also have $25 credits available for participants, so come find me near where the opening presentation was this morning.
Vision Language Models: Gemini 3 (https://ai.google.dev/gemini-api/docs/gemini-3) and Gemini Robotics ER (https://ai.google.dev/gemini-api/docs/robotics-overview). These models are perfect for perception problems, task orchestration, video and task understanding, and a variety of other things related to robotics. We have a cookbook of small tasks (https://github.com/google-gemini/cookbook/blob/main/quickstarts/gemini-robotics-er.ipynb) and I wrote a tutorial for the SOARM101 + SmolVLA project last week (https://dev.to/googleai/teaching-a-robot-to-play-a-toddler-game-vlas-gemini-3-flash-and-first-orchard-14g4)
Agentic Vision is a feature that was added into Gemini 3 Flash, and I think it has a lot of value for perception tasks, so I wanted to highlight it separately. We've seen this used with some of our robotics partners for zooming in on and localizing images in manufacturing and warehouse environments. You can read up on the feature (https://blog.google/innovation-and-ai/technology/developers-tools/agentic-vision-gemini-3-flash/) or try it in AI Studio (https://aistudio.google.com/apps/bundled/gemini_visual_thinking?showPreview=true&showAssistant=true)
The Live API is *really* useful for Human-Robot Interaction. You can speak directly with the model, get audio responses back, send video frames for visual context, and a few other things. https://ai.google.dev/gemini-api/docs/live?example=mic-stream
If simulation is more your thing, I put together a MuJoCo example in AI Studio using a Franka Panda with Gemini for orchestrating pick-and-place operations if you want to test some ideas before moving to real hardware (https://aistudio.google.com/apps/bundled/robotics_franka_pick_and_place?showPreview=true&showAssistant=true)