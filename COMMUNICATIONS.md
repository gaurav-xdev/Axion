# Communication Gateway & Anti-Spam Architecture

## 1. Provider Abstractions
The gateway coordinates three pluggable channels:
- **Email**: SMTP / Mailgun provider
- **WhatsApp**: Official Meta WhatsApp Cloud API
- **Voice**: WebRTC / Twilio Voice adapter

If a provider is not configured:
`STATUS = NOT_CONFIGURED`.
The agent **never** fakes communication success.

## 2. Mandatory 10-Point Anti-Spam Policy
Before any message is transmitted:
1. **Recipient Check**: Valid email/phone format.
2. **Business Fit**: Legitimate commercial relevance.
3. **Channel Check**: Channel is active and verified.
4. **Duplicate Content Check**: SHA-256 hash comparison prevents duplicate messages.
5. **Opt-Out Check**: Verifies prospect/contact has not unsubscribed.
6. **Cooldown Check**: Enforces a 30-day quiet period between contacts.
7. **Fact Check**: Evidence URLs must back up every observed pain point.
8. **Authority Check**: Pricing and revisions strictly adhere to configured limits.
9. **Spam Risk Check**: Scans for aggressive marketing trigger words.
10. **Identity Disclosure**: Must disclose automated AI agency assistance. Never deceptively impersonate a human employee.
