import pytest
from fastapi import HTTPException
from app.admin.deps import scope_clause, assert_visible
from app.db.models import AdminUser, Conversation


class _Obj:
    def __init__(self, country):
        self.country = country


def test_scope_clause_superadmin_is_true():
    su = AdminUser(email="s", password_hash="x", role="superadmin", country=None)
    clause = scope_clause(su, Conversation)
    assert clause.compare(__import__("sqlalchemy").true())


def test_scope_clause_country_admin():
    ca = AdminUser(email="c", password_hash="x", role="country_admin", country="NG")
    clause = scope_clause(ca, Conversation)
    # renders to "conversations.country = :country_1"
    assert "country" in str(clause)


def test_assert_visible():
    su = AdminUser(email="s", password_hash="x", role="superadmin", country=None)
    ca = AdminUser(email="c", password_hash="x", role="country_admin", country="NG")
    assert_visible(su, _Obj("ML"))          # superadmin: no raise
    assert_visible(ca, _Obj("NG"))          # same country: no raise
    with pytest.raises(HTTPException) as e:
        assert_visible(ca, _Obj("ML"))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        assert_visible(ca, _Obj(None))
