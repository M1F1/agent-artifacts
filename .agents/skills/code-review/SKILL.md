---
name: code-review
description: Automated code review skill that checks for common issues, style violations, and potential bugs.
---

# Code Review

Review code changes for correctness, style, and potential issues.

## When to use

- Before merging pull requests
- When reviewing teammate contributions
- As part of CI/CD quality gates

## What it checks

1. **Correctness** - Logic errors, off-by-one mistakes, null handling
2. **Style** - Naming conventions, formatting consistency
3. **Security** - Hardcoded secrets, injection vulnerabilities
4. **Performance** - Unnecessary allocations, N+1 queries

## Instructions

When reviewing code:
- Focus on substance over style when both are present
- Suggest fixes, not just problems
- Note positive patterns worth keeping
- Flag any test gaps for changed logic
