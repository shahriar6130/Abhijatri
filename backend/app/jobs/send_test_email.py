"""Send one test email through the configured provider, to check the email settings.

    python -m app.jobs.send_test_email --to you@example.com

Prints the provider and the result. Never prints the password.
"""

import argparse
import sys
import uuid

from app.config import get_settings
from app.notify.providers import Email, SendAmbiguous, SendFailed, get_provider


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test email.")
    parser.add_argument("--to", required=True)
    arguments = parser.parse_args()
    settings = get_settings()
    provider = get_provider()
    if provider is None:
        print("EMAIL_PROVIDER is 'none': nothing to send.", file=sys.stderr)
        sys.exit(2)
    print(f"provider={provider.name} from={settings.email_from}")
    try:
        message_id = provider.send(
            Email(
                to=arguments.to,
                subject="Abhijatri test email / পরীক্ষামূলক ইমেইল",
                text="If you can read this, Abhijatri can send email.\n\nএটি পড়তে পারলে অভিযাত্রী ইমেইল পাঠাতে পারে।",
                html="<p>If you can read this, Abhijatri can send email.</p><p>এটি পড়তে পারলে অভিযাত্রী ইমেইল পাঠাতে পারে।</p>",
                idempotency_key=f"test-{uuid.uuid4()}",
            )
        )
    except (SendFailed, SendAmbiguous) as error:
        print(f"FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"SENT: {message_id}")


if __name__ == "__main__":
    main()
