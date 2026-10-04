# ADR 0023: Icons from Phosphor, and no animation

Status: accepted
Date: 2026-10-04
Decided by: Aditya Kumar

## Context

The first design rules allowed no icon library and one drawn moment of motion (the sign-in
trace lighting up). In use, the screens read as plain text: the sidebar was a list of words,
inputs had no cue, and people new to the tool had to read every label to find their way. The
sign-in animation also made the panel look faint while it played.

## Decision

1. Icons come from Phosphor Icons (`@phosphor-icons/react`, MIT licence, open source). One family
   only, no hand-drawn icon paths.
2. An icon always sits next to a word (sidebar, buttons, inputs, steps). The only icon-only
   control is show or hide password, which has a label for screen readers and a tooltip.
3. Regular weight for controls, fill for the current sidebar item, duotone only for the large
   step icon on the sign-in card.
4. No animation: no entrance effects, no drawn traces, no sliding drawer, no shimmering
   skeletons. Hover and focus change colour instantly.

## Consequences

- One more dependency in the web app; it is tree-shaken, so only the icons used are shipped.
- The step icons are shared vocabulary: the sign-in journey and the in-app guide use the same
  icon for the same step.
