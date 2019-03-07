import re
import sys
import time
import json
import uuid
import boto3
import indra
import pickle
import random
import datetime
import websocket
from indra.config import get_config
from indra.assemblers.english import EnglishAssembler
from indra.assemblers.tsv import TsvAssembler
from indra.assemblers.graph import GraphAssembler
from indra.assemblers.html import HtmlAssembler
import logging
from slackclient import SlackClient
from indra.util import batch_iter
from indra.statements import stmts_to_json

from bot import IndraBot

logger = logging.getLogger('indra_slack_bot')

user_cache = {}
channel_cache = {}


class IndraBotError(Exception):
    pass


def read_slack_token(fname=None):
    # Token can be found at https://api.slack.com/web#authentication
    if fname is None:
        fname = 'indrabot_slack_token'
    try:
        with open(fname, 'rt') as fh:
            token = fh.read().strip()
        return token
    except IOError:
        logger.error('Could not read Slack token from %s.' % fname)
        return None


def get_user_name(sc, user_id):
    user_name = user_cache.get(user_id)
    if user_name:
        return user_name
    res = sc.server.api_call('users.info', users=user_id)
    user_info = json.loads(res)
    for user in user_info['users']:
        if user['id'] == user_id:
            user_cache[user_id] = user['name']
            return user['name']
    return None


def get_channel_info(sc, channel_id):
    # Return from cache if possible
    if channel_id in channel_cache:
        return channel_cache[channel_id]

    # First, we try channels.info which only works for public channels
    res = sc.server.api_call('channels.info', channel=channel_id)
    res_json = json.loads(res)
    # If we got a channel, then this is a public channel and we can
    # cache its info
    if 'channel' in res_json:
        channel_info = res_json['channel']
    # If this is not a public channel, we get groups.info instead which can
    # reveal if this is a private channel
    else:
        res = sc.server.api_call('groups.info', channel=channel_id)
        res_json = json.loads(res)
        if 'channel' in res_json:
            channel_info = res_json['channel']
        elif res_json.get('error') == 'channel_not_found':
            channel_info = 'PRIVATE'
        else:
            print(res_json)
            print('Unexpected channel info.')
            channel_info = 'UNKNOWN'
    channel_cache[channel_id] = channel_info
    return channel_info


def read_message(sc):
    events = sc.rtm_read()
    if not events:
        print('.', end='', flush=True)
        return None
    logger.info('%s events happened' % len(events))
    event = events[0]
    event_type = event.get('type')
    if not event_type:
        return
    if event_type == 'message':
        try:
            msg = event['text']
        except Exception:
            logger.info('Could not get message text, skipping')
            logger.info(event)
            return -1
        try:
            user = event['user']
        except Exception:
            logger.info('Message not from user, skipping')
            #logger.info(msg)
            return -1
        channel = event['channel']
        user_name = get_user_name(sc, user)
        #channel_name = get_channel_name(sc, channel)
        logger.info('Message received - [%s]: %s' %
                    (user_name, msg))
        return (channel, user_name, msg, user)
    return None


def send_message(sc, channel, msg):
    sc.api_call("chat.postMessage",
                channel=channel,
                text=msg, as_user=True)
    logger.info('Message sent: %s' % msg)


def format_stmts(stmts, output_format, ev_counts=None):
    if output_format == 'tsv':
        msg = ''
        for stmt in stmts:
            if not stmt.evidence:
                logger.warning('Statement %s without evidence' % stmt.uuid)
                txt = ''
                pmid = ''
            else:
                txt = '"%s"' % stmt.evidence[0].text if \
                    stmt.evidence[0].text else ''
                pmid = stmt.evidence[0].pmid if stmt.evidence[0].pmid else ''
            try:
                ea_txt = EnglishAssembler([stmt]).make_model()
            except Exception as e:
                ea_txt = ''
                logger.error('English assembly failed for %s' % stmt)
                logger.error(e)
            line = '%s\t%s\t%s\tPMID%s\n' % (stmt, ea_txt, txt, pmid)
            msg += line
        return msg
    elif output_format == 'pkl':
        fname = 'indrabot.pkl'
        with open(fname, 'wb') as fh:
            pickle.dump(stmts, fh)
        return fname
    elif output_format == 'pdf':
        fname = 'indrabot.pdf'
        ga = GraphAssembler(stmts)
        ga.make_model()
        ga.save_pdf(fname)
        return fname
    elif output_format == 'json':
        msg = json.dumps(stmts_to_json(stmts), indent=1)
        return msg
    elif output_format == 'html':
        ev_counts = {} if not ev_counts else ev_counts
        ha = HtmlAssembler(stmts, ev_totals=ev_counts)
        fname = 'indrabot.html'
        ha.save_model(fname)
        return fname
    return None


db_rest_url = get_config('INDRA_DB_REST_URL')


def dump_to_s3(stmts):
    s3 = boto3.client('s3')
    bucket = 'indrabot-results'
    fname = '%s.html' % uuid.uuid4()
    ha = HtmlAssembler(stmts, db_rest_url=db_rest_url, ev_totals=ev_counts)
    html_str = ha.make_model()
    url = 'https://s3.amazonaws.com/%s/%s' % (bucket, fname)
    logger.info('Dumping to %s' % url)
    s3.put_object(Key=fname, Body=html_str.encode('utf-8'),
                  Bucket=bucket, ContentType='text/html')
    logger.info('Dumped to %s' % url)
    return url


def help_message(long=False, topic=None):
    """An instructive message sent to users who ask for help"""
    # TODO
    #  *Add different topics to describe specific functionalities in
    #  detail.

    get_more = "To get a more detailed help message, ask me " \
        "```@indrabot what can you do?```"

    short_help = ("Ask me a question with a direct message "
                  "(using `@indrabot`) about mechanisms and I will "
                  "try to answer them. For example: \n"
                  "```@indrabot what activates NF-kB?```\n or "
                  "```@indrabot what phosphorylates RB1?```\n "
                  "You can try various ways of phrasing your questions, and "
                  "if there is anything I don't understand, I will suggest a "
                  "similar question to yours that I do know how to answer. "
                  "My answer is formatted as a snippet with a list of "
                  "statements with their "
                  "human-readable English language summaries, original "
                  "evidence sentences, and source PMIDs (if available)."
                  "The response also contains a link to an "
                  "HTML interface that show the list of statements in "
                  "more detail.\n\n")

    long_help = ("Scopes and Mechanism Types:\n"
                 "Your question can be mechanism specific, for example you "
                 "can ask a question like ```can BRAF activate Mek1?``` or "
                 "```what does JAK1 phosphorylate?```, and you will get "
                 "answers "
                 "that fit the scope, i.e., with mechanisms that involve "
                 "activation or phosphorylation, respectively. To "
                 "broaden the scope, you can ask ```what affects CDK4?```, to "
                 "get any type of mechanism where CDK4 is downstream, or in "
                 "the same manner: ```what are the targets of EGFR?``` "
                 "to get any mechanism where EGFR is upstream of another "
                 "entity. If you want an even broader scope you can ask "
                 "```what interacts with DOCK5?```, to get both upstream and "
                 "downstream interactions of any kind, including binding."
                 "\n"
                 "Output Formats:\n"
                 "There are five output formats I support that you can. "
                 "specify by ending you message with, for instance, `/json`. "
                 "These formats are as follows:\n"
                 "*tsv: "
                 "A tab separated list of statements, their English "
                 "assembled versions, their evidence texts that "
                 "produced the statement and a PMID (if available) "
                 "where the evidence was found. "
                 "\n"
                 "*json: "
                 "A json representation of the statements found. This "
                 "corresponds to what would be the output of "
                 "`indra.statements.stmts_to_json(statements)` "
                 "where `statements` is a list of INDRA Statement "
                 "objects. "
                 "\n"
                 "*pdf:"
                 "A pdf document containing a directed node-edge "
                 "graph visualization of the statements. "
                 "\n"
                 "*html:"
                 "An HTML document that contains an HTML-formatted "
                 "version of the statements. This is the "
                 "same page that is linked at the bottom of each "
                 "response. "
                 "\n"
                 "*pickle:"
                 "A Python pickle file containing a pickle of the list of "
                 "INDRA Statement objects."
                 "")
    return short_help + long_help if long else short_help + get_more


def _connect():
    token = read_slack_token()
    if not token:
        raise IndraBotError("Could not get slack token.")
    sc = SlackClient(token)
    conn = sc.rtm_connect()
    if not conn:
        raise IndraBotError('Could not connect to Slack.')
    return sc


if __name__ == '__main__':
    logf = open('slack_bot_log.txt', 'a', 1)
    bot = IndraBot()
    bot_id = 'U2F1KPXEW'

    sc = _connect()
    while True:
        try:
            try:
                res = read_message(sc)
            except:
                # Try one more time with a fresh connection.
                sc = _connect()
                res = read_message(sc)
            if res == -1:
                continue
            elif res:
                (channel, username, msg, userid) = res
                # Skip own messages
                if userid == bot_id:
                    continue
                try:
                    channel_info = get_channel_info(sc, channel)
                    # If this is not a private convo and the bot wasn't named,
                    # then we don't answer.
                    if channel_info != 'PRIVATE' and \
                        '<@%s>' % bot_id not in msg:
                        continue
                    # We also skip file uploads
                    if 'uploaded a file' in msg:
                        continue
                    # Replace our own ID in the message if it's in there
                    msg = msg.replace('<@%s>' % bot_id, '').strip()

                    ts = '{:%Y-%m-%d %H:%M:%S}'.format(datetime.datetime.now())

                    logf.write('%s\t%s\t%s\t' % (msg, userid, ts))

                    # Try to get magic modifiers
                    output_format = 'tsv'
                    mods = ['pkl', 'pdf', 'tsv', 'json', 'html']
                    for mod in mods:
                        if msg.endswith('/%s' % mod):
                            output_format = mod
                            msg = msg[:-(len(mod)+1)].strip()
                            break

                    if re.sub('[.,?!;:]', '', msg.lower()) in \
                            ['help', 'what can you do']:
                        msg = re.sub('[.,?!;:]', '', msg.lower())
                        help_resp = help_message(
                            long=msg == 'what can you do')
                        send_message(sc, channel, help_resp)
                        continue

                    resp = bot.handle_question(msg)
                    if 'question' in resp:
                        msg = resp['question']
                        send_message(sc, channel, msg)
                        logf.write('C\n')
                        continue

                    resp_stmts = resp['stmts']
                    ev_counts = resp.get('ev_counts', {})

                    logf.write('%d\n' % len(resp_stmts))

                    prefixes = ['That\'s a great question',
                                'What an interesting question',
                                'As always, I\'m happy to answer that',
                                'Very interesting']
                    prefix = random.choice(prefixes)
                    msg = "%s, <@%s>" % (prefix, userid)
                    if len(resp_stmts) == 0:
                        msg += ' but I couldn\'t find any statements about that.'
                    else:
                        msg += '! I found %d statement%s about that.' % \
                                 (len(resp_stmts),
                                  ('s' if (len(resp_stmts) > 1) else ''))
                    send_message(sc, channel, msg)
                    if resp_stmts:
                        reply = format_stmts(resp_stmts, output_format,
                                             ev_counts)
                        if output_format in ('tsv', 'json'):
                            sc.api_call("files.upload",
                                        channels=channel,
                                        filename='indrabot.%s' % output_format,
                                        filetype=output_format,
                                        content=reply,
                                        text=msg)
                        else:
                            sc.api_call("files.upload",
                                        channels=channel,
                                        filename='indrabot.%s' % output_format,
                                        filetype=output_format,
                                        file=open(reply, 'rb'),
                                        text=msg)
                        # Try dumping to S3
                        try:
                            url = dump_to_s3(resp_stmts)
                            msg = 'You can also view these results here: %s' % url
                            send_message(sc, channel, msg)
                        except Exception as e:
                            logger.error(e)
                    if 'suggestion' in resp:
                        print(resp['suggestion'])
                        send_message(sc, channel, resp['suggestion'])

                except websocket.WebSocketException as e:
                    logger.warning('connection closed')
                    continue
                except Exception as e:
                    logger.exception(e)
                    logf.write('%d\n' % -1)
                    reply = 'Sorry, I can\'t answer that, ask something else.'
                    send_message(sc, channel, reply)
            else:
                time.sleep(2)
        except KeyboardInterrupt:
            logf.close()
            logger.info('Shutting down due to keyboard interrupt.')
            sys.exit()
