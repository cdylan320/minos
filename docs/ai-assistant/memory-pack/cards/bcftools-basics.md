# Minos SN107: BCFtools Basics

Memory name: Minos SN107 - BCFtools Basics
Version: 1.0.0
Primary subject: BCFtools
Subjects: BCFtools; Variant calling; Config tuning; Runtime operations; Scoring basics
Related memories: Minos SN107 - Safe Tuning Workflow; Minos SN107 - Safe Config-Tuning Basics; Minos SN107 - Scoring Basics; Minos SN107 - Variant Calling Basics

BCFtools is a fast and lightweight toolkit for variant calling and VCF processing.

In Minos, BCFtools can be useful for learning, smaller machines, fast iteration, or cases where runtime reliability matters. It may need careful filtering to compete well.

Beginner-safe BCFtools support:

- confirm input and reference handling
- avoid random filter changes
- test one filtering category at a time
- compare score components across multiple rounds
- watch false positives and false negatives together

BCFtools being faster does not automatically mean better scoring. DeepVariant or GATK may perform better in some contexts. The right choice depends on machine resources, completion reliability, and public scoring evidence.
