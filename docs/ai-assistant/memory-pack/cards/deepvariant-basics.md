# Minos SN107: DeepVariant Basics

Memory name: Minos SN107 - DeepVariant Basics
Version: 1.0.0
Primary subject: DeepVariant
Subjects: DeepVariant; Variant calling; Docker runtime; Hardware requirements; Scoring basics
Related memories: Minos SN107 - Hardware And Runtime Guide; Minos SN107 - Safe Tuning Workflow; Minos SN107 - Scoring Basics; Minos SN107 - Variant Calling Basics

DeepVariant is a neural-network-based variant caller. It is often strong out of the box and can be a good beginner choice when the machine has suitable runtime resources.

DeepVariant usually exposes fewer simple knobs than highly tunable pipelines. That can make it easier to start with, but it can also limit how much a beginner can safely tune.

Good DeepVariant support:

- confirm Docker and runtime resources first
- run demo mode before live mining
- compare public score behavior over multiple rounds
- avoid changing many variables at once
- watch runtime, completion reliability, and scoring quality together

DeepVariant can be compute-heavy. If a machine cannot complete rounds reliably, a faster or lighter path may be more useful than a theoretically stronger caller.
