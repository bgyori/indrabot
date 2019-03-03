from itertools import groupby
from flask_wtf import Form
from flask_bootstrap import Bootstrap
from flask_appconfig import AppConfig
from wtforms import TextField, SubmitField
from flask import Flask, render_template, request

from indra.assemblers.html import HtmlAssembler

from bot import IndraBot


class ExampleForm(Form):
    """Create form to enter and submit question."""
    question = TextField('')
    submit_button = SubmitField('Ask INDRA')


def format_stmts_raw(stmts):
    """Return Statements formatted as simple HTML string."""
    stmts = stmts.get('stmts', [])
    stmts = sorted(stmts, key=lambda x: x.__class__.__name__)
    html = ''
    for stmt_type, stmts_this_type in \
        groupby(stmts, key=lambda x: x.__class__.__name__):
        html += '<h3>%s</h3>\n' % stmt_type
        for stmt in stmts_this_type:
            line = '<p>%s, %s</p>\n' % (str(stmt), stmt.evidence[0].text)
            html += line
    return html


def format_stmts_html(stmts):
    """Return Statements assembled with INDRA's HTML assembler."""
    stmts = stmts.get('stmts', [])
    ha = HtmlAssembler(stmts)
    html = ha.make_model()
    return html


def create_app(configfile=None):
    """Cteate and run the app."""
    app = Flask(__name__)
    AppConfig(app, configfile)
    app.config['SECRET_KEY'] = open('app_secret', 'r').read()
    app.config['RECAPTCHA_PUBLIC_KEY'] = \
        '6Lfol9cSAAAAADAkodaYl9wvQCwBMr3qGR_PPHcw'

    Bootstrap(app)

    @app.route('/', methods=('GET', 'POST'))
    def index():
        # Create the form
        form = ExampleForm()
        # Try to get the question from the form
        try:
            question = request.form['question']
            print(question)
        except Exception as e:
            question = None
        kwargs = {'form': form}
        # If we have a question
        if question:
            # Send the question to the bot
            stmts = bot.handle_question(question)
            # If we got some Statements, display them
            if stmts:
                resp_html = format_stmts_html(stmts)
                kwargs['response'] = resp_html
            # Otherwise show sorry message
            else:
                kwargs['response'] = 'Sorry, I couldn\'t find anything!'
        # Finally, render the template
        return render_template('index.html', **kwargs)

    return app


if __name__ == '__main__':
    bot = IndraBot()
    create_app().run(debug=True)

