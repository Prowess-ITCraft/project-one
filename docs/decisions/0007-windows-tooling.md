# ADR 0007: Windows hosts use scripts/dev.ps1

Status: accepted
Date: 2026-09-30

## Context

make and gh are not installed on the Windows development machine.

## Decision

A Makefile serves Linux, macOS and CI. scripts/dev.ps1 offers the same commands on Windows.

## Consequences

Two files to keep in step. They only wrap docker compose and pytest, so drift is small.
