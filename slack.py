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


def get_channel_name(sc, channel_id):
    channel_name = channel_cache.get(channel_id)
    if channel_name:
        return channel_name
    res = sc.server.api_call('channels.info', channel=channel_id)
    channel_info = json.loads(res)
    channel = channel_info['channel']
    if channel['id'] == channel_id:
        channel_cache[channel_id] = channel['name']
        return channel['name']
    return None


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


def format_stmts(stmts, output_format):
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
        ha = HtmlAssembler(stmts)
        fname = 'indrabot.html'
        ha.save_model(fname)
        return fname
    return None


def dump_to_s3(stmts):
    s3 = boto3.client('s3')
    bucket = 'indrabot-results'
    fname = '%s.html' % uuid.uuid4()
    ha = HtmlAssembler(stmts)
    html_str = ha.make_model()
    url = 'https://s3.amazonaws.com/%s/%s' % (bucket, fname)
    logger.info('Dumping to %s' % url)
    s3.put_object(Key=fname, Body=html_str.encode('utf-8'),
                  Bucket=bucket, ContentType='text/html')
    logger.info('Dumped to %s' % url)
    return url


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
                try:
                    if '<@U2F1KPXEW>' not in msg:
                        continue
                    if 'uploaded a file' in msg:
                        continue
                    msg = msg.replace('<@U2F1KPXEW>', '').strip()

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

                    resp = bot.handle_question(msg)
                    if 'question' in resp:
                        msg = resp['question']
                        send_message(sc, channel, msg)
                        logf.write('C\n')
                        continue

                    resp_stmts = resp['stmts']

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
                    #send_message(sc, channel, reply)
                    reply = format_stmts(resp_stmts, output_format)
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
                    print(resp.keys())
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
