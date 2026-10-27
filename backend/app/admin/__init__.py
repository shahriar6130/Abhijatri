"""Staff operations behind `/api/v1/admin` (Moderation-Dashboard-Specification, Gantt R10 and R11).

Every operation re-reads the actor's role from the database, validates state, version and claim
lease, writes the immutable action and audit rows, and queues any event, all in one transaction
that the route commits once (spec 8.5).
"""
