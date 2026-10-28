"""Every dashboard panel. Importing a module registers its panel (System-Monitoring-Dashboard 6.1)."""

from app.ops.providers import content, health, members, notifications, reviews, traffic, visitors

__all__ = ["content", "health", "members", "notifications", "reviews", "traffic", "visitors"]
