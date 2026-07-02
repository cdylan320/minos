# Minos SN107 Scoring And AdvancedScorer

Memory name: Minos SN107 - Scoring And AdvancedScorer
Version: 1.0.0
Primary subject: Scoring basics
Subjects: Minos SN107; Scoring basics; AdvancedScorer; hap.py benchmarking; SNPs and indels; Rewards and emissions
Related memories: Minos SN107 - Scoring Basics; Minos SN107 - Protocol Rules And Rewards; Minos SN107 - Variant Calling Basics; Minos SN107 - Safe Tuning Workflow

This is public-safe scoring education for Minos subnet 107. It explains concepts without exposing private benchmark data or validator-private details.

## Scoring Flow

Miners submit variant-calling configs or pipelines. Validators rerun those configs, generate variant calls, and score the generated calls.

The validator-side scoring compares called variants against benchmark/reference truth data. Miners should not ask for, paste, or use private truth files.

## hap.py Concepts

hap.py-style benchmarking compares predicted variant calls with truth data and reports concepts such as:

- true positives: correct calls
- false positives: calls that should not be there
- false negatives: real variants missed by the caller
- precision: how many called variants were correct
- recall: how many real variants were found
- F1: a balance of precision and recall
- SNP and indel behavior

## AdvancedScorer Concept

AdvancedScorer is Minos scoring logic that combines benchmark signals into a public score. At a high level, good scores require more than "more variants." Strong miners balance precision, recall, completeness, false-positive control, quality, and runtime reliability.

## Common Tradeoff

Overcalling may improve recall but can hurt precision and false-positive control. Over-filtering may reduce false positives but can miss real variants and hurt recall/completeness.

## Beginner Rule

Do not tune before the miner can complete demo mode, participate live, produce valid output, and receive public scored results. When tuning, change one category at a time and compare over multiple rounds.

## Safety Boundary

Do not expose private truth files, private benchmark data, private validator files, private scoring details, private configs, presigned URLs, signatures, nonces, or admin output.
