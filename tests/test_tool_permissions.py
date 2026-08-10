from backend.domain import UserContext
from backend.services.tool_permissions import check_tool_permission


def test_employee_can_call_qa_tools() -> None:
    user = UserContext(user_id="alice", roles=("employee",))

    assert check_tool_permission("search_knowledge_base", user).allowed is True
    assert check_tool_permission("ask_knowledge_base", user).allowed is True


def test_employee_cannot_call_admin_document_tool() -> None:
    decision = check_tool_permission(
        "list_documents",
        UserContext(user_id="bob", roles=("employee",)),
    )

    assert decision.allowed is False
    assert decision.reason == "missing_required_role"
    assert decision.required_roles == ("admin",)


def test_admin_can_call_every_known_tool() -> None:
    user = UserContext(user_id="root", roles=("admin",))

    assert check_tool_permission("list_documents", user).allowed is True
    assert check_tool_permission("search_knowledge_base", user).allowed is True
