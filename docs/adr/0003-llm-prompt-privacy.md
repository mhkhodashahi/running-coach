# ADR 0003: LLM Prompt Privacy

## Status

Accepted

## Context

Running Coach sends selected training, recovery, goal, and activity detail
metrics to configured LLM providers. Some local runtime outputs include paths,
commands, model locations, and debug logs that are useful for development but
not needed for coaching.

## Decision

LLM prompt context must include only coaching-relevant data. Prompts must not
include raw local paths, checkpoint paths, repo paths, command lines, output
directories, metadata paths, stdout/stderr tails, or local machine paths unless
the user explicitly asks for debugging output.

## Consequences

Prompt builders should have tests that prove sensitive runtime fields are
filtered out. LLM outputs must remain conservative and avoid medical diagnosis.
