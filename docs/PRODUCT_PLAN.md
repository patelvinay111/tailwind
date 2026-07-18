# Product Plan: Tailwind AI — Voice Trip Booking

## Vision

A voice-first travel assistant that books a complete trip (flights + hotels) in one natural conversation, personalized to the traveler's preferences.

---

## Product Decisions

| Decision | Choice |
|----------|--------|
| First screen | Landing page with hero + "Start Planning" button |
| Voice modes | Both WebRTC (in-browser) + outbound phone call |
| Transcript | Side panel on the left — scrolling chat |
| Options display | Voice + clickable cards (pick by voice OR click) |
| Itinerary | Builds up live as items are booked |
| Visual style | Dark + gold/warm accents — airline premium feel |
| Confirmation | Visual trip summary card before booking |
| Preferences | JSON file, agent mentions them naturally |
| Agent persona | "Tailwind" |
| Layout | Left: voice + transcript. Right: cards + itinerary |

---

## User Journey

### 1. Landing
- Dark premium page, "Tailwind" branding with gold accent
- Hero text: "Your voice travel assistant. Plan and book your entire trip in one conversation."
- Two CTAs: **"Start Planning"** (WebRTC) and **"Call Me"** (outbound)

### 2. Connection
- User clicks "Start Planning" → WebRTC connects, mic activates
- Agent greets by name using preferences: "Hey Pradeep! I'm Tailwind. I've got your preferences loaded — you like Delta, aisle seats, and Hilton hotels. Where are we headed?"

### 3. Flight Search
- User describes trip: "I want to go to Austin next Friday through Sunday"
- Agent confirms details, mentions using preferences: "Since you prefer nonstop, let me look for direct flights first..."
- Right panel: 3 flight option cards appear (preferred airlines first)
- Agent reads top options aloud

### 4. Flight Selection
- User says "I'll take the Delta" OR clicks the card
- Card animates to itinerary section
- Agent confirms + asks about hotels

### 5. Hotel Search
- User: "Find me something downtown"
- Agent: "Checking Hilton and Marriott first since those are your go-to's..."
- Right panel: 2-3 hotel cards appear
- Agent describes top options

### 6. Hotel Selection
- User picks one (voice or click)
- Hotel card moves to itinerary

### 7. Trip Summary & Confirmation
- Right panel shows full Trip Summary card with total price
- "Confirm & Book" button + "Cancel" button
- Agent reads back the summary: "Your total trip is $595 — should I book it all?"
- User confirms by voice ("yes") or clicks button

### 8. Booking Complete
- Confirmation numbers displayed on itinerary cards
- Agent: "Done! Confirmation numbers are on your screen. Have an amazing trip!"
- "Start New Trip" button resets

---

## Alternative Flows

| Scenario | Agent Behavior |
|----------|---------------|
| Vague destination ("somewhere warm") | Uses Flight Search (inspirational) to suggest destinations |
| Change preference ("make it business class") | Re-searches with updated cabin filter |
| Decline ("never mind") | Wraps up politely, offers to help later |
| Budget concern ("that's too expensive") | Searches again with tighter constraints |
| Missing info ("next Friday") | Infers date from context, confirms with user |

---

## Screen Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  TAILWIND ✈                                    [Start Planning]  │
├────────────────────────────┬─────────────────────────────────────┤
│                            │                                     │
│  🎙 Voice Widget           │   Option Cards (when searching)     │
│  [connected / muted]       │   ┌─────┐ ┌─────┐ ┌─────┐         │
│                            │   │ DL  │ │ UA  │ │ WN  │         │
│  ─────────────────────     │   └─────┘ └─────┘ └─────┘         │
│                            │                                     │
│  Transcript:               │   ─────────────────────────────     │
│  🤖 Hey Pradeep! Where...  │                                     │
│  👤 I want to go to Aus... │   📋 Your Itinerary                 │
│  🤖 Found a Delta nonst... │   ┌─────────────────────────┐      │
│  👤 I'll take the Delta    │   │ ✈ Delta DL1420  ✓       │      │
│  🤖 Booked! Need a hotel?  │   │ 🏨 Hilton Downtown  ✓   │      │
│  ...                       │   │                         │      │
│                            │   │ Total: $595             │      │
│                            │   │ [Confirm & Book]        │      │
│                            │   └─────────────────────────┘      │
└────────────────────────────┴─────────────────────────────────────┘
```

---

## Preferences (Knowledge Base)

The agent knows the traveler before they say a word:

- **Name:** Pradeep
- **Home airport:** SFO
- **Airlines:** Delta, United (prioritized in results)
- **Cabin:** Economy, aisle seat
- **Hotels:** Hilton, Marriott (under $250/night)
- **Style:** Mention preferences naturally ("Since you like Delta...")
- **Loyalty:** Auto-apply loyalty numbers to bookings
