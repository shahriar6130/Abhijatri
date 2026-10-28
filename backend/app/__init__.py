"""Abhijatri backend package."""

import truststore

# Verify HTTPS certificates (Supabase, Brevo, Turnstile, Upstash) against the operating system's trust
# store instead of Python's bundled list, so a machine whose antivirus or proxy re-signs TLS still works.
truststore.inject_into_ssl()
