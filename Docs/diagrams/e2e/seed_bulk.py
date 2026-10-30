"""Seed N member reviews into the LOCAL database through the application's own service (bypasses the HTTP rate limit)."""
import base64
import os
import sys
import uuid
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.schemas import MemberReviewCreate
from app.services import submit_member_review

email, dest_id, stamp, n, offset = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
today = date.today()
made = 0
with SessionLocal() as s:
    user = s.scalar(select(User).where(User.email == email))
    for i in range(n):
        total = today.year * 12 + today.month - 1 - (offset + i)
        month = date(total // 12, total % 12 + 1, 1)
        payload = MemberReviewCreate.model_validate({
            "destination_id": dest_id, "client_draft_id": str(uuid.uuid4()),
            "receipt_secret": "abr1_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="),
            "language": "EN", "traveller_type": "SOLO", "comfort_tier": "STANDARD", "visit_month": month.isoformat(),
            "title": f"Bulk {stamp} {i:02d}", "body": "A bulk test review used for paging, long enough to pass.",
            "overall_rating": 3, "consent_version": "v1",
        })
        submit_member_review(s, payload, user.id)
        made += 1
    s.commit()
print(made)
