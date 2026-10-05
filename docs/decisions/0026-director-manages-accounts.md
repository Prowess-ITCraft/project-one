# ADR 0026: The Director holds every Admin permission

Status: accepted
Date: 2026-10-05
Decided by: Aditya Kumar

## Context

Only the Admin role could create accounts, assign roles and change admin settings. The
Director runs the company and should not have to wait for an admin to add a colleague or
change someone's role.

## Decision

1. Accounts are still created only on the Accounts page, by an Admin or the Director. No other
   role can create an account or change roles (403).
2. The Director holds every Admin permission on top of the Director's own: accounts and roles,
   password and authenticator resets, unlocking, signing people out, deactivating, erasing
   personal data, feature flags, gate settings, rules, deleting customers and projects, and the
   audit log check. In code, `ROLE_PERMISSIONS[Role.DIRECTOR]` is the Admin set plus the
   Director set.
3. An Admin or the Director may assign any role, Admin and Director included.
4. Nobody may remove their own Admin or Director role, or deactivate their own account, so the
   people who manage accounts cannot lock everyone out by mistake.
5. Segregation of duties is unchanged: it is checked per action in the services, so the
   Director still cannot approve their own rule change, BOQ pricing, gate submission or field
   task.

## Consequences

- The Director account is now as powerful as an Admin account. It already needs an
  authenticator; keep its recovery codes safe.
- The permission matrix test checks every route for the new Director rights.
- The Accounts entry appears in the Director's sidebar, and the Help guide shows the Admin
  steps to Directors.
