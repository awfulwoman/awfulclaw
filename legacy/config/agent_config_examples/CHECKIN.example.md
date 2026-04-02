# Check-in Checklist

When running an ambient check-in, review the following and speak up only if something warrants attention. If nothing does, stay silent.

- Any unread emails that look urgent or time-sensitive?
- Any schedules that fired since the last check-in? Did they succeed?
- Any upcoming calendar events in the next few hours that the user should prepare for?

<!-- CUSTOMISATION NOTES

This file is the "patrol checklist" for ambient check-ins. The agent reads
it periodically (controlled by checkin_interval in settings) and invokes
Claude with this prompt. If Claude determines nothing warrants attention,
no message is sent.

Check-ins are distinct from schedules: schedules fire blindly at a set
time and always produce output. Check-ins are conditional — they only
speak when something matters.

Keep this short and specific. Each item should be something the agent can
actually check with its available tools. Don't add aspirational items
that require tools the agent doesn't have.

Example additions:
- "Has the user been inactive for more than 12 hours? If so, skip the check-in."
- "Any GitHub PRs awaiting my review?"
- "Is the home temperature outside the 18-24°C range?" (requires Home Assistant MCP)
-->
