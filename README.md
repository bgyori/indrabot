INDRA Bot
=========

A bot that translatest natural language questions into database queries
and answers with a list of INDRA Statements extracted from the literature
and pathway databases.

The bot backend (bot.py) has two frontends:
- Slack bot (slack.py) which takes questions in a Slack channel or direct messages
- Web app (app.py) which takes questions in a text box on a website

Slack bot
---------
To run the slack bot, do
```bash
python slack.py
```

Website
-------
To run the web app, do
```bash
python app.py
```
or use a WSGI application server like gunicorn.

Funding
-------
The development of indrabot is funded under the DARPA Communicating with Computers program (ARO grant W911NF-15-1-0544).
