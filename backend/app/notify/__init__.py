"""Notifications from the shared outbox (Moderation spec 6.7 and 11).

Business code only writes `outbox_events` rows in its own transaction. The worker turns each event
into in-app notifications (unique per event, recipient and kind) and sends email outside any
database transaction. Browsers receive new notifications live over Server-Sent Events.
"""
