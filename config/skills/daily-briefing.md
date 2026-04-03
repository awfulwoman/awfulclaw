# Daily Briefing Skill

Produce a concise morning briefing. Work through each section below; if a tool is unavailable or returns an error, skip that section silently.

## Sections

1. **Calendar** — call `calendar_list_events` for today. List upcoming events with times.
2. **Reminders** — call `reminders_list` filtered to incomplete items due today or overdue. List each reminder.
3. **Weather** — call `weather_get_forecast` for the user's location. Include current conditions and today's high/low.
4. **Email** — if an email tool is available, summarise unread messages. Skip if unavailable.

## Format

- Keep the full briefing under 250 words.
- Use bullet points within each section.
- Omit any section entirely if its tools are unavailable or return no data.
- Lead with a one-line date/time header.
