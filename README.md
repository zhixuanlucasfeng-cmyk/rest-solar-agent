# Rest Solar Agent

Multilingual AI customer service for solar businesses. It answers from a real product catalogue, follows price and inventory rules, captures enquiries, and hands conversations to staff when a human should take over.

[![AI customer service deployment](https://powvy.org/assets/social/ai-customer-service.png)](https://powvy.org/)

## What is already working

- English and French chat, with language detection and friendly fallback responses.
- Country-scoped product catalogues, conversations, orders and admin access.
- Product, stock and quote tools that avoid inventing unavailable prices.
- Live human handoff with a waiting queue and real-time WebSocket messages.
- Admin pages for products, rules, conversations, orders and support tickets.

The current system powers Restar Solar's country websites. [Open the Cameroon site](https://restarsolar.net/?country=CM) and use the chat button to try it.

## Need this for your business?

I can adapt the same system to your catalogue, languages and staff workflow. The first usable version can be live in seven days.

[Ask about a deployment on WhatsApp](https://wa.me/8618707737002?text=Hi%20Lucas%2C%20I%27m%20interested%20in%20an%20AI%20customer%20service%20deployment.)

## Local development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Run the test suite with `pytest`.
