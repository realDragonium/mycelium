# Worked patterns

Read with `mycelium-guide-authoring`. The link types are illustrations; choose from `list_link_types()`.

## The procedure shape

### Configuration procedure with properties

When a guide is mostly about *gathering values and submitting them* (an admin filling out a configuration form, an integration setup), the dominant shape is the procedure root composing properties:

```
[procedure]  "How to connect a reporting tool to a workspace"
   teaches  → [capability]  "A reporting tool can be connected to a workspace"

   requires → [property]    "Workspace API base URL"
                obtained-by → [action] "Copy the API base URL from the workspace's Developer page"

   requires → [property]    "API key"
                obtained-by → [procedure] "How to create an API key for a workspace"

   accepts  → [property]    "API key role"
                valued-by   → [rule] "API key role is one of Viewer, Editor, Admin"

   accepts  → [property]    "Reporting tool display name"

   contains → [action]      "Paste the API key into the reporting tool's connection form"
                performs → [event] "An API request is authenticated with the key"
```

Notes on this shape:

- **The procedure is the entry point.** Consumers search *"how to connect a reporting tool"* and land on the procedure record. From there, `requires` / `accepts` enumerate what they need to gather; `contains` enumerates the UI steps.
- **Properties are shared, not duplicated.** *"Workspace API base URL"* is one record. A second procedure (a diagnostic, a different setup flow) can `requires` the same property without re-authoring it.
- **`obtained-by` is sparse on purpose.** Most properties have no lookup — the user just types in a display name. Only attach `obtained-by` when there's a real lookup with its own UI steps.
- **Action chains stay short.** If the procedure is mostly *gather values, send them*, the action layer contains the *send*. Pre-send "actions" like *"Identify the stage"* are property tells (§3), not actions.

### UI walkthrough with sequential clicks

When a guide is mostly *clicks in sequence* (*"How to create an API key for a workspace"*, through the product's own UI), the action chain dominates and properties may be minimal:

```
[action]   "Navigate to Settings → API keys"
   next → [action]   "Click New API key"
            next → [action]   "Enter a name for the API key"
                     next → [action]   "Select a role from the dropdown"
                              next → [action]   "Click Create"
                                       next → [action]   "Copy the generated key"
                                                next → [check]   "Verify a test API request with the key returns 200"
                                                         on-success → [action]   "Store the key in the reporting tool"
                                                         on-failure → [cause]   "The API key was created without the required role"
                                                                       ↑ resolves
                                                                       [action]   "Edit the API key's role"
```

Notes on this pattern:

- **The procedure terminates in a check, not a save.** The step that confirms the procedure worked is itself a check — the user (or the diagnostic agent watching) verifies that the system reports success. The final store action only runs on the success branch.
- **Failure branches transition into diagnostic shape.** *"The test call failed"* fans out into causes — missing role, revoked token, wrong base URL — each with its own resolving action. The procedure and the diagnostic share statements; the same `cause` can be reached either way.
- **Pre-conditions live on the first action's incoming edge.** *"The member's role is Admin"* and *"API access is enabled for the workspace"* are descriptive states attached as `when` on the entry edge, not extra action steps.

## The diagnostic shape

Diagnostic trees radiate out from a failing capability. Login can't complete:

```
[capability]   "A user can log in"                                       (descriptive — entry point)
   ↑ (this capability is failing)

[cause]   "User is attempting password login on a social-only account"
   confirms ← [check]   "Inspect the auth_provider field on the account"
                          on-failure → [action]   "Direct the user to the correct social-login button"
   violates → [state]   "Auth provider on account matches submitted method"

[cause]   "Email format is invalid"
   confirms ← [check]   "Verify the email matches the expected format"
                          on-failure → [action]   "Prompt the user to correct the email"
   violates → [state]   "Email is valid format"

[cause]   "Network blocks the auth domain"                               (no `violates` — environmental)
   confirms ← [check]   "Have the user attempt the login from a different network"
                          on-failure → [action]   "Advise the user to contact their network admin"

[cause]   "Account predates current email-verification requirement"      (no `violates` — historical)
   confirms ← [check]   "Look up the account creation date against the policy effective date"
                          on-failure → [action]   "Trigger a one-time verification flow for the account"
```

Notes:

- **The entry point is the capability, not a symptom record.** A diagnostic agent receives a user complaint *"I can't log in"*, resolves it to the `login` capability, and walks the cause neighborhood.
- **Causes are siblings, not ordered.** Unless one cause is strictly more likely or strictly cheaper to check, leave them as parallel branches and let the agent decide ordering.
- **Each cause owns its check and resolution.** Don't share checks across causes unless the check genuinely refutes multiple — that's a real `refutes` fan-out, not a shortcut.
- **Free-standing causes use no `violates`.** The environmental and historical causes above carry no descriptive anchor. They're complete in their own text.
