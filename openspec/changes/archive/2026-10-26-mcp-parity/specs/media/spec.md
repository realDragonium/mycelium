## ADDED Requirements

### Requirement: Editing media over MCP
The system SHALL advertise `edit_media(request)` to real writers and admins, which changes an item's details (alt text required), sets or clears its audience label, confirms a label after its content changed, attaches it to or detaches it from a statement or concept, or deletes it, which needs a real admin. `replace_content` SHALL return a single-use upload link, valid 15 minutes, whose accepted bytes become the item's new content, as replacing it in the web app does.

#### Scenario: Agent replaces a screenshot
- **WHEN** a writer agent asks for a replacement link and posts a PNG to it
- **THEN** the item keeps its id and its content version goes up by one

#### Scenario: Writer deletes media
- **WHEN** a writer agent asks `edit_media` to delete an item
- **THEN** the call is refused for want of the admin role

## MODIFIED Requirements

### Requirement: Listing media for a statement or concept
The system SHALL expose `list_media(statement_id?, entity_id?, media_id?, show="all")`, advertised over MCP, which takes at most one id. With a statement or concept it refuses one that does not exist or the caller may not see and returns the attached items the caller's audience may see; with `media_id` it returns that item; with none it returns the media library filtered by `show`. Each item comes with details, label, attachments, `stale` reasons and `url`.

#### Scenario: Both ids given
- **WHEN** a caller passes both `statement_id` and `entity_id`
- **THEN** the call is refused asking for at most one

#### Scenario: Library over MCP
- **WHEN** an agent calls `list_media` with no id and `show` `unattached`
- **THEN** it gets the same items as `GET /api/media?show=unattached`
