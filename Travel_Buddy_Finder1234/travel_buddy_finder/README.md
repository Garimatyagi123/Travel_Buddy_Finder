# Travel Buddy Finder

**Find the right person. Plan the right trip.**

A responsive Flask + SQLAlchemy travel-buddy website with account login, buddy profiles, trip discovery, join requests, shared budgets, editable expenses, itinerary planning, stay/transport/activity catalogs, and ready-made trip packages.

## Features

- Individual registration and login with hashed passwords.
- Seeded demo profiles and trips stored as normal database records (not frontend-only cards).
- Explore trips and find buddies; filters are database-backed.
- Create trips and request to join another traveller's trip.
- Shared trip budget with accommodation, transportation, activities, food and other categories.
- Edit or remove expenses; changes update the shared budget automatically.
- Day-by-day itinerary and starter itinerary for demo trips.
- Browse stays, transportation and activities; select a trip and edit the estimate before adding it to that trip's budget.
- Ready-made packages for Ladakh, Goa, Kerala, Jaipur, Rishikesh and Manali. Starting a package creates an editable trip with itinerary and cost estimates.
- Direct messages for accepted connections or people sharing an accepted trip.
- Google Maps page for destination maps, place/attraction search, and Google Maps directions with route distance and estimated travel time.
- Responsive layout with destination photography. Internet is required for maps, remote photos and Bootstrap/font CDNs.

All catalog/package prices are illustrative planning estimates, not live prices, availability or bookings.

## Requirements

- Python 3.10+
- pip

## Run locally (Windows PowerShell)

Open this project folder in VS Code. The `app.py` and `requirements.txt` files are in the project root.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```

If `py` is unavailable, install Python from https://www.python.org/downloads/windows/ and select **Add python.exe to PATH**, then reopen VS Code.

Open http://127.0.0.1:5000.

## Demo accounts

Demo password for seeded users: `Travel123!`

- `aarav@example.com`
- `sana@example.com`
- `riya@example.com`
- `kabir@example.com`
- `meera@example.com`
- `dev@example.com`
- `ananya@example.com`
- `ishaan@example.com`
- `zoya@example.com`
- `arjun@example.com`
- `tanya@example.com`
- `vihaan@example.com`
- `naina@example.com`
- `rehan@example.com`
- `pooja@example.com`
- `aditya@example.com`

Demo records are added only if missing. The database is stored in `travel_buddy_finder.db` in the project folder. For a clean reset, stop the server and delete that database file; the app will recreate it on next start.

## Database configuration

SQLite is the default for straightforward student-project setup. To use another SQLAlchemy-supported database, set `DATABASE_URL` before starting the app. Set a strong `SECRET_KEY` for deployment. Do not deploy with the development secret.

## Main pages

- `/` landing page
- `/register`, `/login`
- `/maps` destination maps, place search and directions
- `/trips` explore trips
- `/trips/create` create trip (login required)
- `/buddies` discover people (login required)
- `/packages` browse ready-made packages
- `/stays`, `/transportation`, `/activities` catalogs
- `/trips/<id>` trip workspace, budget and itinerary
- `/profile`, `/connections`, `/messages`

## Notes

This is a college-project demo. Stay/transport/activity prices are sample estimates and no ticket or hotel booking occurs. The messaging feature uses regular requests rather than push-based real-time chat. Before public deployment, configure a production secret, CSRF protection, rate limiting, secure cookies, and proper migrations/production database settings.


## Updated catalogue and photography

The Stays, Transportation, and Activities pages have explicit routes and each item has its own relevant photo URL. Use the selector on each card to choose a trip and adjust the estimate before adding it to the trip budget. Trip cards use destination-matched imagery. Buddy cards use human portraits for the seeded demo accounts; new accounts use an initials avatar unless a profile photo feature is configured. Photos are loaded from external image hosts and therefore require an internet connection.

## Latest fixes (11 October 2026)
- The Stays, Transportation, and Activities links have explicit working routes.
- Adding an item now uses a normal POST form that sends the selected trip ID, instead of constructing the request URL in inline JavaScript.
- Each catalogue item has its own image URL; trip cards rotate through destination-relevant photo options to reduce repetition.
- External photos require an internet connection. Catalogue prices are sample planning estimates, not live availability or bookings.

On Windows, from this project folder run:
```powershell
py -m pip install -r requirements.txt
py app.py
```
Then open `http://127.0.0.1:5000` in your browser.


## Google Maps feature

Open **Maps & routes** in the navigation to view a destination map, search places and attractions, and open directions from a starting location to a destination. The app uses Google Maps search/embed URLs, so no API key is needed for this basic integration. Google Maps opens externally for current route choices, distance, estimated travel time, traffic and turn-by-turn navigation. A future fully embedded Places/Routes API integration may require a Google Cloud project, enabled APIs, an API key and billing.


## Expanded international demo content

The catalogue now includes illustrative stays, local transport ideas and activities for Japan, Indonesia/Bali, Portugal, France, Switzerland, Thailand, Türkiye, South Africa and the United States, alongside Indian destinations. Additional fictional demo buddy profiles and international group-trip examples are seeded on app startup. All prices are sample planning estimates in INR, not live quotes, verified availability, or bookings. Demo accounts use the same sample password `Travel123!`. Seeded records are added only when missing, so existing databases are not overwritten.


## Expanded India + international version

Explore Trips and the home-page trip strip interleave India-based and international trips. Added destination trip ideas include Mysuru, Darjeeling, Hampi, Sikkim, Kutch, Orchha, Lakshadweep, Ziro Valley, Jodhpur, Barcelona, London, Rome, Dubai, Seoul, Kathmandu, Maldives, Prague and Vancouver. Demo profiles are fictional and seeded only when their email is missing.

The stays, transportation and activities catalogues include more India and international examples. All prices remain illustrative estimates in INR and are not live quotes, confirmed availability or bookings. Destination, package and catalog cards use separate image assignments to reduce repeated photos; remote image hosts still require internet and may occasionally change/remove an image.

## Install on Android and iPhone

This project is configured as a Progressive Web App (PWA). Deploy it to a public HTTPS host first. On Android, open the HTTPS site in Chrome and choose **Install app** or **Add to Home screen** from the browser menu. On iPhone, open the HTTPS site in Safari, tap **Share**, then **Add to Home Screen**. It opens in an app-like standalone window. The live Flask pages, login, messaging, Google Maps and remote images still need an internet connection; the service worker caches only the static app shell.

This is an installable web app, not a compiled native App Store / Google Play package. Publishing native store apps requires additional build, signing and store-review steps; iOS native packaging generally requires access to macOS/Xcode or a cloud build service.


## Destination photo behavior
The Explore Packages page contains individual destinations in India and abroad, alternating domestic and international entries. Each package card is assigned a distinct Unsplash photo ID. Photos load from Unsplash over the internet; if an external image fails to load, check its URL and replace it with another unique image ID.


## Trust, messaging safety and quiz rewards (prototype)

- **Government ID review:** Profile users can request a review by choosing an ID type. The app stores only the type and review status; it does not upload or retain ID photos or numbers. Set `ADMIN_EMAIL` in the hosting environment to the email account allowed to review requests at `/admin/verifications`. Mark a request verified only after a genuine, authorised identity check. This prototype does not connect to an ID verification provider.
- **In-app chat safeguards:** Message sending is validated server-side, limited to 500 characters, capped at 10 messages per minute per recipient, and blocks common phone/email/social-handle/link patterns. This discourages off-platform planning but cannot guarantee users will never communicate elsewhere.
- **Quizzes and rewards:** Signed-in users can complete each travel quiz once and earn 10 points per correct answer. Redeeming a demo coupon costs 100 points. Coupon codes are prototype rewards, not live merchant discounts.
- New tables are created at startup by `db.create_all()`. For production schema changes to existing tables, use Flask-Migrate migrations.


## Password reset email (OTP) setup

The login page includes a **Forgot password?** flow. To deliver OTP messages, copy `.env.example` to `.env` and configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM` for an SMTP account you control. For Gmail, use a Google App Password (not your normal account password) after enabling 2-Step Verification. Never commit `.env` or share the SMTP password. OTPs expire after 10 minutes, are stored hashed, allow up to five verification attempts, and are limited to three requests per account per 15 minutes. Without valid SMTP settings, email delivery will fail and the UI will show a configuration message.

The UI now uses a darker midnight teal theme with light text and high-contrast form controls.
