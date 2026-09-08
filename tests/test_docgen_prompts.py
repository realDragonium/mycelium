import pytest

from mycelium.docgen import prompts


@pytest.mark.parametrize("retry", [False, True])
def test_review_preserves_frontmatter_at_start_of_document(retry: bool):
    body = "---\ntitle: Match score\ntype: explanation\n---\n\n# Match score\n"
    if retry:
        message = prompts.review_retry_message(
            prompt="Explain match score",
            title="Match score",
            body=body,
            exposure_findings=[],
            conformance_findings=[],
        )
    else:
        message = prompts.review_message(
            prompt="Explain match score",
            title="Match score",
            body=body,
            statements=[],
        )

    context, document = message.split("=== DOCUMENT ===\n", 1)
    document, _ = document.split("\n=== END DOCUMENT ===", 1)
    assert document == body
    assert "DOCUMENT TITLE (metadata, not document content): Match score" in context
