# ADR 0003: LLM Prompt Privacy

## Status

Accepted

## Context

Running Coach sends selected training, recovery, goal, activity detail, and body
scan metrics to configured LLM providers. Some local body scan and SAM outputs
include paths, commands, checkpoint locations, and debug logs that are useful for
development but not needed for coaching.

## Decision

LLM prompt context must include only coaching-relevant data. Body scan prompts
must not include raw local image paths, mesh paths, checkpoint paths, repo paths,
command lines, output directories, metadata paths, stdout/stderr tails, or local
machine paths unless the user explicitly asks for debugging output.

## Consequences

Prompt builders should have tests that prove sensitive runtime fields are
filtered out. LLM outputs must remain conservative: no diagnosis, body-fat
estimates, or injury certainty from photos or meshes.
