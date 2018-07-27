from flask import Flask, render_template, flash, request
from flask_bootstrap import Bootstrap
from flask_appconfig import AppConfig
from flask_wtf import Form, RecaptchaField
from flask_wtf.file import FileField
from wtforms import TextField, HiddenField, ValidationError, RadioField,\
    BooleanField, SubmitField, IntegerField, FormField, validators
from wtforms.validators import Required


from itertools import groupby
from bot import IndraBot


class ExampleForm(Form):
    question = TextField('')
    submit_button = SubmitField('Ask INDRA')


def format_stmts(stmts):
    stmts = sorted(stmts, key=lambda x: x.__class__.__name__)
    html = ''
    for stmt_type, stmts_this_type in \
        groupby(stmts, key=lambda x: x.__class__.__name__):
        html += '<h3>%s</h3>\n' % stmt_type
        for stmt in stmts_this_type:
            line = '<p>%s, %s</p>\n' % (str(stmt), stmt.evidence[0].text)
            html += line
    return html

def create_app(configfile=None):
    app = Flask(__name__)
    AppConfig(app, configfile)
    app.config['SECRET_KEY'] = open('app_secret', 'r').read()
    app.config['RECAPTCHA_PUBLIC_KEY'] = \
        '6Lfol9cSAAAAADAkodaYl9wvQCwBMr3qGR_PPHcw'

    Bootstrap(app)


    @app.route('/', methods=('GET', 'POST'))
    def index():
        form = ExampleForm()
        try:
            question = request.form['question']
            print(question)
        except Exception as e:
            question = None
        kwargs = {'form': form}
        if question:
            stmts = bot.handle_question(question)
            if stmts:
                resp_html = format_stmts(stmts)
                kwargs['response'] = resp_html
            else:
                kwargs['response'] = 'Sorry, I couldn\'t find anything!'
        return render_template('index.html', **kwargs)

    return app

if __name__ == '__main__':
    bot = IndraBot()
    create_app().run(debug=True)

