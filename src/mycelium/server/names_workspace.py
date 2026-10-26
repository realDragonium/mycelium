"""The names workspace and alias suggestions over every transport.

Reads are open to any caller. Edits need a real writer, and merging concepts or
removing a name a real admin: a names-workspace edit lands live, so a drafter
cannot reach it (a drafter proposes names with `upsert_name` and friends). Alias
suggestions are reviewed by a human writer. The web app's names routes call
these same functions.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .. import alias_suggestions, auth, names_workspace
from .registry import tool
from .runtime import _caller, _db

NamesView = Literal["catalogue", "concept", "dismissed_duplicates", "alias_suggestions"]
AliasStatus = Literal["pending", "accepted", "rejected", "all"]


def catalogue(principal: auth.Principal, query: str = "") -> names_workspace.Catalogue:
    result = names_workspace.catalogue(_db(), query)
    result.can_write = auth.principal_has_real_role(principal, "writer")
    if result.can_write:
        result.allowed_actions = ["add", "correct", "prefer", "move", "split"]
    if auth.principal_has_real_role(principal, "admin"):
        result.allowed_actions.extend(("merge", "remove"))
    return result


class AliasSuggestions(BaseModel):
    suggestions: list[alias_suggestions.Entry]


@tool
def get_names_workspace(
    view: NamesView = "catalogue",
    q: str = "",
    entity_id: str | None = None,
    status: AliasStatus = "pending",
) -> dict[str, JsonValue]:
    """Read the Names & aliases workspace.

    `catalogue` lists concepts with their names, matching `q`, possible
    duplicate concepts and which edits the caller may make;
    `concept` shows one concept (`entity_id`) with its names, example
    statements, relationships, history and the `revision` an edit needs;
    `dismissed_duplicates` lists concept pairs a curator said are not
    duplicates; `alias_suggestions` lists the AI's alias suggestions by
    `status` (pending, accepted, rejected or all) with the revision each
    review needs."""
    result: BaseModel
    if view == "catalogue":
        result = catalogue(_caller(), q)
    elif view == "concept":
        if entity_id is None:
            raise ValueError("Give the concept's entity_id.")
        result = names_workspace.detail(_db(), entity_id)
    elif view == "dismissed_duplicates":
        result = names_workspace.dismissed_duplicates(_db())
    else:
        result = AliasSuggestions(suggestions=alias_suggestions.list_entries(status))
    return result.model_dump(mode="json")


def require_name_edit(action: names_workspace.Action) -> None:
    """Merging concepts and removing a name are an admin's."""
    if action.kind in {"merge", "remove"} and not auth.principal_has_real_role(
        _caller(), "admin"
    ):
        raise auth.RoleRequired("admin role required")


class Preview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["preview"]
    change: names_workspace.Action


class Apply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["apply"]
    change: names_workspace.Action
    #: The `revision` of a fresh preview of the same change.
    expected_revision: str


class DismissDuplicate(names_workspace.DismissDuplicate):
    action: Literal["dismiss_duplicate"]


class RestoreDuplicate(names_workspace.DismissDuplicate):
    action: Literal["restore_duplicate"]


class ScanAliases(alias_suggestions.ScanRequest):
    action: Literal["scan_aliases"]


class ReviewAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["review_alias"]
    draft_id: str
    operation_ref: str
    decision: Literal["accept", "reject", "retarget", "refresh"]
    expected_revision: int = Field(ge=0)
    #: The concept a `retarget` moves the alias to.
    entity_id: str | None = None


NamesEdit = Annotated[
    Preview | Apply | DismissDuplicate | RestoreDuplicate | ScanAliases | ReviewAlias,
    Field(discriminator="action"),
]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_names_edit: TypeAdapter[NamesEdit] = TypeAdapter(NamesEdit)


def _pair(
    request: DismissDuplicate | RestoreDuplicate,
) -> names_workspace.DismissDuplicate:
    return names_workspace.DismissDuplicate(
        a_entity_id=request.a_entity_id, b_entity_id=request.b_entity_id
    )


class Done(BaseModel):
    done: bool = True


@tool(role="writer", real_role=True)
def edit_names(request: NamesEdit) -> dict[str, JsonValue]:
    """Edit names and aliases as the Names & aliases workspace does, landing
    live. Real writers and admins only.

    `preview` shows what `change` would do and its `revision`; `apply`
    makes it, refused when the vocabulary changed since that preview.
    `change` is one of `{"kind": "add", entity_id, text}`, `correct`
    (entity_id, name_id, text), `prefer` (entity_id, name_id), `move`
    (entity_id, name_id, target_entity_id), `split` (entity_id, name_ids,
    preferred_name_id, description), `merge` (entity_id, target_entity_id,
    preferred_name_id, description) or `remove` (entity_id, name_id);
    merge and remove need a real admin. `dismiss_duplicate` and
    `restore_duplicate` (a_entity_id, b_entity_id) say whether two concepts
    are offered as possible duplicates. `scan_aliases` asks the AI for alias
    suggestions from up to 50 `statement_ids`; `review_alias` takes a
    `decision` on one suggestion (`draft_id`, `operation_ref`,
    `expected_revision`): accept, reject, retarget (to `entity_id`) or
    refresh, which needs a human writer."""
    request = _names_edit.validate_python(request)
    return _edit_names(request).model_dump(mode="json")


def _edit_names(request: NamesEdit) -> BaseModel:
    if isinstance(request, Preview):
        require_name_edit(request.change)
        return names_workspace.preview(_db(), request.change)
    if isinstance(request, Apply):
        require_name_edit(request.change)
        return names_workspace.apply(
            names_workspace.ApplyRequest(
                action=request.change, expected_revision=request.expected_revision
            )
        )
    if isinstance(request, DismissDuplicate):
        names_workspace.dismiss_duplicate(_db(), _pair(request))
        return Done()
    if isinstance(request, RestoreDuplicate):
        names_workspace.restore_duplicate(_db(), _pair(request))
        return Done()
    if isinstance(request, ScanAliases):
        return alias_suggestions.scan(
            alias_suggestions.ScanRequest(statement_ids=request.statement_ids),
            _caller(),
        )
    return alias_suggestions.review(
        request.draft_id,
        request.operation_ref,
        alias_suggestions.ReviewRequest(
            action=request.decision,
            expected_revision=request.expected_revision,
            entity_id=request.entity_id,
        ),
        _caller(),
    )
