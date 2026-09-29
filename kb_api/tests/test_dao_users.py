from kb_api.api.dao.users import UsersDAO


def test_users_dao_lists_org_subtree(system):
    dao = system["dao"]
    app, root = dao.create_app("Directory", "directory")
    child = dao.create_org(app["id"], root["id"], "Department")
    _, other_root = dao.create_app("Other", "other")
    root_user = dao.create_user(org_id=root["id"], name="root-member", password_hash=None)
    child_user = dao.create_user(org_id=child["id"], name="child-member", password_hash=None)
    dao.create_user(org_id=other_root["id"], name="other-member", password_hash=None)

    users = UsersDAO(dao.database_url).list_users(root["id"])

    assert {user["id"] for user in users} == {root_user["id"], child_user["id"]}
    assert all("password_hash" not in user for user in users)
