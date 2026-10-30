"""Local database only: take the bulk paging reviews out of the moderators' queue so the queue stays short."""
import os

import psycopg

dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(dsn) as conn:
    n = conn.execute(
        "update moderation_tasks set status='cancelled' where status='open' and subject_id in "
        "(select r.id from reviews r join review_revisions v on v.id = r.current_revision_id where v.title like 'Bulk %')"
    ).rowcount
    conn.commit()
print(n)
