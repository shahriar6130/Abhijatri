"""Member and staff authentication (Gantt R04, Moderation-Dashboard-Specification 2 and 4).

Supabase Auth (GoTrue) is the identity provider. The browser never calls it: this package proxies
it, keeps the tokens in HttpOnly cookies and decides every permission from application data.
"""
