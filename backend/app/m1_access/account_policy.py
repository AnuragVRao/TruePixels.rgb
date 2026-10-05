"""Who may change whose account status (F.17 write half).

One rule set, shared by M1's ``PATCH /users/{id}/status`` and M3's
``PATCH /admin/users/{id}/status`` so the two cannot drift (Phase 5b).

What the statuses mean - this is a SOFT state change, nothing is deleted:

* ``disabled`` / ``removed``: sign-in is refused and every existing session
  token is rejected on its next use (``security.current_session`` re-reads
  the status on each request). The user's D2 images, D4 predictions, D5
  panels, D6 log rows and stored files are all KEPT, untouched, and stay
  reachable to nobody but their owner - who can no longer sign in.
* ``enable`` returns either state to ``active``; all data reappears as it was.

"removed" differs from "disabled" only in its label today. There is no hard
delete and no file cleanup; orphaned files cannot arise from this action.

Re-registration: the D1 row is kept, and the unique index on lower(email)
still holds its address, so the same e-mail cannot register a new account
while a removed (or disabled) row exists. The attempt gets exactly the
answer any taken address gets - 409 AUTH_EMAIL_TAKEN, same message - so it
does not reveal that the account is removed (test_account_status_enforcement).
To let the person back in, an admin re-enables the account; there is no
erase-and-reuse path (a hard delete would need a retention decision first).
Sign-in reports "disabled"/"removed" only AFTER a correct password, i.e. only
to the account's owner.

Refused (409 ``ADM_ACTION_NOT_PERMITTED``), whatever the UI shows:

* an administrator changing their OWN status;
* any change that would leave no ACTIVE administrator.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.m1_access.models import User
from app.shared.errors import AdmActionNotPermittedException, AppException

STATUS_FOR_ACTION = {"enable": "active", "disable": "disabled", "remove": "removed"}


def apply_status_change(db: Session, actor_id: int, target_id: int, action: str) -> tuple[User, str]:
    """Validate and apply; returns (user, old_status). The caller commits."""
    if target_id == actor_id:
        raise AdmActionNotPermittedException("Administrators cannot change their own account status.")

    target = db.query(User).filter(User.user_id == target_id).first()
    if target is None:
        raise AppException(code="USER_NOT_FOUND", message=f"User #{target_id} does not exist.", status_code=404)

    new_status = STATUS_FOR_ACTION[action]
    if target.role == "Admin" and target.account_status == "active" and new_status != "active":
        # Lock the active administrators so two concurrent requests cannot
        # each see "one other admin left" and both succeed (Postgres; SQLite
        # serialises writers and ignores FOR UPDATE).
        active_admins = (db.query(User.user_id)
                         .filter(User.role == "Admin", User.account_status == "active")
                         .with_for_update().all())
        if len(active_admins) <= 1:
            raise AdmActionNotPermittedException("This would leave no active administrator.")

    old_status = target.account_status
    target.account_status = new_status
    return target, old_status
