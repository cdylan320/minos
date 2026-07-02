# Minos SN107 Safe Config-Tuning Basics

Memory name: Minos SN107 - Safe Config-Tuning Basics
Version: 1.0.0
Primary subject: Config tuning
Subjects: Minos SN107; Config tuning; How to compete well; GATK; DeepVariant; BCFtools; Scoring basics; Safe support behavior
Related memories: Minos SN107 - Safe Tuning Workflow; Minos SN107 - GATK Basics; Minos SN107 - DeepVariant Basics; Minos SN107 - BCFtools Basics; Minos SN107 - Scoring Basics

This public guide gives beginner-safe tuning principles for Minos miners.

## When Tuning Is Appropriate

Tune only after:

1. demo mode works
2. live participation is confirmed
3. submissions are succeeding
4. valid scored results exist
5. the target problem is understood

## When Tuning Is Not Appropriate

Do not tune when:

- Docker is failing
- files are not downloading
- no result is produced
- no live submission exists
- the miner has not received scored results
- the issue is wallet, hotkey, registration, or platform connectivity

## Scoring Tradeoff

Good mining is not "call more variants." Strong configs balance recall, precision, false-positive control, completeness, quality, and runtime.

## Overcalling And Over-Filtering

Overcalling means calling too many variants. It may improve recall but hurt precision and false-positive score.

Over-filtering means being too strict. It may reduce false positives but miss real variants and hurt recall/completeness.

## Tool Overview

GATK is highly tunable and powerful, but random changes can easily make it worse.

DeepVariant is strong out of the box and simpler for beginners, but has fewer knobs.

BCFtools is fast and lightweight, useful for smaller machines or learning, but may need careful filtering.

## GATK Categories

Explain these as tradeoffs, not magic values:

- base quality filters
- mapping quality filters
- confidence thresholds
- PCR indel model
- pruning parameters
- haplotype and assembly search limits
- active region thresholds
- contamination filtering
- soft-clipped base handling

## Safe Workflow

1. Identify the score component or failure mode.
2. Change one category at a time.
3. Record the exact change.
4. Compare multiple rounds.
5. Keep improvements that help the target component without breaking others.

Do not claim any config is guaranteed to win. Do not optimize against private truth data.
