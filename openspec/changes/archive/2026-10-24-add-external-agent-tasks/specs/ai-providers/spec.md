## MODIFIED Requirements

### Requirement: Selected provider needs a model
The system MUST refuse a model selection whose selected provider has an empty model ID, unless the action is set to External agent and no server model reviews its work (any action other than `docgen`, or `docgen` with `agent_review` `agent`).

#### Scenario: Missing model for the chosen provider
- **WHEN** an admin saves `provider` `openai` with an empty `openai_model`
- **THEN** the request fails with 400 "Choose a model ID for the selected provider."

#### Scenario: External agent without a model
- **WHEN** an admin saves `audience_labelling` with `external_agent: true` and an empty model for the selected provider
- **THEN** the selection is saved
