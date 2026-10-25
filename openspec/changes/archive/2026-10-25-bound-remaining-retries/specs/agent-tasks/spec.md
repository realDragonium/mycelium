## ADDED Requirements

### Requirement: Release limit
The system SHALL count each lease that runs out and each `release_agent_task` toward the task's `releases`, keeping the latest reason as `release_reason` for the next claimant. Once a task was released more often than `task_release_retries` (Automation limits, default 2), the system SHALL fail it with the reason and the count, and close what it served as when its work fails.

#### Scenario: Lease runs out past the limit
- **WHEN** `task_release_retries` is 0 and the lease of a documentation run's task runs out
- **THEN** the task is `failed` with a reason naming the expired claim, and the run wrote nothing

#### Scenario: Give-back keeps its reason
- **WHEN** an agent gives a task back with a reason and the task is within its limit
- **THEN** the next claimant receives the task with that `release_reason` and `releases` 1
