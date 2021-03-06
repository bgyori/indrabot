import re
import nltk
import logging
import requests
from fuzzywuzzy import fuzz
from indra.statements import Agent
from indra.sources import indra_db_rest
from indra.databases import hgnc_client
from indra.tools import expand_families


logger = logging.getLogger('indrabot.bot')


EV_LIMIT = 1


class IndraBot(object):
    def __init__(self):
        self.templates = self.make_templates()

    @staticmethod
    def make_templates():
        templates = []

        t = ("what are the targets of ([^ ]+)", get_from_source)
        templates.append(t)

        t = ("^([^ ]+) targets$", get_from_source)
        templates.append(t)

        t = ("targets of ([^ ]+)", get_from_source)
        templates.append(t)

        t = ("what binds ([^ ]+)", get_complex_one_side)
        templates.append(t)

        t = ("what mechanisms trigger ([^ ]+)", get_to_target)
        templates.append(t)

        t = ("what does ([^ ]+) interact with", get_neighborhood)
        templates.append(t)

        t = ("what interacts with ([^ ]+)", get_neighborhood)
        templates.append(t)

        t = ("what do you know about ([^ ]+)", get_neighborhood)
        templates.append(t)

        t = ("what does ([^ ]+) do", get_neighborhood)
        templates.append(t)

        options1 = ['have an effect on', 'affect', 'influence', 'change',
                    'regulate', 'activate', 'inhibit', 'inactivate',
                    'deactivate', 'suppress', 'downregulate',
                    'upregulate', 'positively affect', 'negatively affect',
                    'positively influence', 'negatively influence', 'trigger']
        options2 = ['', ' activity', ' activation', ' function']
        for op1 in options1:
            for op2 in options2:
                t = ("does phosphorylation %s ([^ ]+)%s" % (op1, op2),
                     get_phos_activeforms)
                templates.append(t)
                t = ("how does phosphorylation %s ([^ ]+)%s" % (op1, op2),
                     get_phos_activeforms)
                templates.append(t)
        t = ('what are the active forms of ([^ ]+)', get_activeforms)
        templates.append(t)

        t = ('what forms of ([^ ]+) are active', get_activeforms)
        templates.append(t)

        t = ('how is ([^ ]+) activated', get_activeforms)
        templates.append(t)

        t = ("does ([^ ]+) interact with ([^ ]+)",
             get_binary_undirected)
        templates.append(t)
        t = ("how does ([^ ]+) interact with ([^ ]+)",
             get_binary_undirected)
        templates.append(t)
        t = ("([^ ]+) interacts with ([^ ]+)",
             get_binary_undirected)
        templates.append(t)
        t = ("how ([^ ]+) interacts with ([^ ]+)",
             get_binary_undirected)
        templates.append(t)

        t = ("does ([^ ]+) bind ([^ ]+)", get_binary_undirected)
        templates.append(t)

        for verb in affect_verbs:
            t = ("does ([^ ]+) %s ([^ ]+)" % verb,
                 makelambda_bin(get_binary_directed, verb))
            templates.append(t)
            t = ("how does ([^ ]+) %s ([^ ]+)" % verb,
                 makelambda_bin(get_binary_directed, verb))
            templates.append(t)
            t = ("can ([^ ]+) %s ([^ ]+)" % verb,
                 makelambda_bin(get_binary_directed, verb))
            templates.append(t)

            options = ['all the things', 'all the things that', 'what',
                       'things', 'things that']
            for option in options:
                t = ("show me %s ([^ ]+) %ss" % (option, verb),
                     get_from_source)
                templates.append(t)

            t = ("what does ([^ ]+) %s" % verb,
                 makelambda_uni(get_from_source, verb))
            templates.append(t)

            t = ("what genes does ([^ ]+) %s" % verb,
                 makelambda_uni(get_from_source, verb))
            templates.append(t)

            t = ("what %ss ([^ ]+)" % verb,
                 makelambda_uni(get_to_target, verb))
            templates.append(t)

        t = ("what is the link between ([^ ]+) and ([^ ]+)",
             get_binary_directed)
        templates.append(t)


        return templates

    @staticmethod
    def sanitize(text):
        marks = ['.', ',', '?', '!', ';', ':']
        for mark in marks:
            text = text.replace(mark, '')
        text = text.strip()
        return text

    def handle_question(self, question):
        # First sanitize the string to prepare it for matching
        question = self.sanitize(question)
        # Next, collect all the patterns that match
        matches = []
        for pattern, action  in self.templates:
            match = re.match(pattern, question, re.IGNORECASE)
            if match:
                args = list(match.groups())
                matches.append((action, args))
        print('matches', matches)

        # If we have multiple matches, we ask the first one
        # (possibly ask for clarification)
        if len(matches) > 1:
            ret = self.respond(*matches[0])
            suggestions = suggest_relevant_relations(ret['groundings'])
            if suggestions:
                ret['suggestion'] = suggestions
            return ret
            #return self.ask_clarification(matches)
        # If we have no matches, we try to find a similar question
        # and ask for clarification
        elif not matches:
            return {'question': self.find_fuzzy_clarify(question)}
        # Otherwise we respond with the first match
        else:
            ret = self.respond(*matches[0])
            suggestions = suggest_relevant_relations(ret['groundings'])
            if suggestions:
                ret['suggestion'] = suggestions
            print(ret)
            return ret

    def respond(self, action, args):
        print('args', args)
        stmts = action(*args)
        return stmts

    def ask_clarification(self, matches):
        pass

    def find_fuzzy_clarify(self, question):
        best_score = [0, 0]
        for i, (pattern, action) in enumerate(self.templates):
            pat_words = ' '.join(get_pattern_words(pattern))
            question_words = ' '.join(get_pattern_words(question))
            score = fuzz.token_sort_ratio(pat_words, question_words)
            if score > best_score[1]:
                best_score = [i, score]

        suggest = get_pattern_example(self.templates[best_score[0]][0])
        msg = 'Your question is similar to "%s?". Try asking it that way.' % \
              suggest
        return msg



def get_pattern_example(pattern):
    pattern = pattern.replace('([^ ]+)', 'X')
    return pattern


def get_pattern_words(pattern):
    pattern = pattern.replace('([^ ]+)', '')
    words = nltk.word_tokenize(pattern)
    return words


mod_map = {'demethylate': 'Demethylation',
           'methylate': 'Methylation',
           'phosphorylate': 'Phosphorylation',
           'dephosphorylate': 'Dephosphorylation',
           'ubiquitinate': 'Ubiquitination',
           'deubiquitinate': 'Deubiquitination',
           'activate': 'Activation',
           'inhibit': 'Inhibition'}


affect_verbs = ['affect', 'regulate', 'control', 'target'] + \
    list(mod_map.keys())


expander = expand_families.Expander()
def suggest_relevant_relations(groundings):
    def make_nice_list(lst):
        if len(lst) == 1:
            return lst[0]
        pre = ', '.join(lst[:-1])
        full = '%s, or %s' % (pre, lst[-1])
        return full
    prefix1 = 'By the way, I recognized'
    prefix2 = 'I also recognized'
    msg_parts = []
    for entity_txt, (dbn, dbi) in groundings.items():
        if dbn == 'FPLX':
            ag = Agent(name=entity_txt, db_refs={dbn: dbi})
            children = expander.get_children(ag)
            print(children)
            if not children:
                continue
            children_names = [ch[1] for ch in children]
            children_str = make_nice_list(children_names)
            prefix = prefix1 if not msg_parts else prefix2
            msg = ('%s "%s" as a family or complex, '
                   'you might be interested in asking about some of its '
                   'specific members like %s.') % (prefix, entity_txt,
                                                   children_str)
            msg_parts.append(msg)
        if dbn == 'HGNC':
            name = hgnc_client.get_hgnc_name(dbi)
            uri = expander.entities.get_uri(dbn, name)
            print(uri)
            parent_uris = expander.entities.get_parents(uri)
            parents = [expand_families._agent_from_uri(uri)
                       for uri in parent_uris]
            print(parents)
            if not parents:
                continue
            parent_names = [p.name for p in parents]
            parents_str = make_nice_list(parent_names)
            prefix = prefix1 if not msg_parts else prefix2
            msg = ('%s "%s" as a protein that is part of a family or complex, '
                   'you might be interested in asking about some of those too '
                   'like %s.') % (prefix, entity_txt, parents_str)
            msg_parts.append(msg)

    full_msg = ' '.join(msg_parts)
    return full_msg


def get_grounding_from_name(name):
    try:
        res = requests.post('http://grounding.indra.bio/ground',
                            json={'text': name})
        if not res:
            logger.info('Could not ground %s with Gilda, looking up by name.'
                        % name)
            return 'TEXT', name
        top_term = res.json()[0]['term']
        logger.info('Grounded %s with Gilda to %s:%s' % (name, top_term['db'],
                                                         top_term['id']))
        return top_term['db'], top_term['id']
    except Exception as e:
        logger.exception(e)
    return 'TEXT', name


def get_neighborhood(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    res = get_statements(agents=[key], ev_limit=EV_LIMIT)
    res['groundings'] = {entity: (dbn, dbi)}
    return res


def get_activeforms(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    res = get_statements(agents=[key], stmt_type='ActiveForm',
                         ev_limit=EV_LIMIT)
    res['groundings'] = {entity: (dbn, dbi)}
    return res


def get_phos_activeforms(entity):
    ret = get_activeforms(entity)
    ret_stmts = []
    for stmt in ret.get('stmts', []):
        for mc in stmt.agent.mods:
            if mc.mod_type == 'phosphorylation':
                ret_stmts.append(stmt)
    return {'stmts': ret_stmts, 'groundings': ret['groundings'],
            'ev_counts': ret['ev_counts'],
            'source_counts': ret['source_counts']}


def get_binary_directed(entity1, entity2, verb=None):
    dbn1, dbi1 = get_grounding_from_name(entity1)
    key1 = '%s@%s' % (dbi1, dbn1)
    dbn2, dbi2 = get_grounding_from_name(entity2)
    key2 = '%s@%s' % (dbi2, dbn2)
    if not verb or verb not in mod_map:
        res = get_statements(subject=key1, object=key2, ev_limit=EV_LIMIT)
    elif verb in mod_map:
        stmt_type = mod_map[verb]
        res = get_statements(subject=key1, object=key2,
                             stmt_type=stmt_type, ev_limit=EV_LIMIT)
    res['groundings'] = {entity1: (dbn1, dbi1), entity2: (dbn2, dbi2)}
    return res


def get_binary_undirected(entity1, entity2):
    dbn1, dbi1 = get_grounding_from_name(entity1)
    key1 = '%s@%s' % (dbi1, dbn1)
    dbn2, dbi2 = get_grounding_from_name(entity2)
    key2 = '%s@%s' % (dbi2, dbn2)
    res = get_statements(agents=[key1, key2], ev_limit=EV_LIMIT)
    res['groundings'] = {entity1: (dbn1, dbi1), entity2: (dbn2, dbi2)}
    return res


def get_from_source(entity, verb=None):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    if not verb or verb not in mod_map:
        res = get_statements(subject=key, ev_limit=EV_LIMIT)
    else:
        stmt_type = mod_map[verb]
        res = get_statements(subject=key, stmt_type=stmt_type,
                             ev_limit=EV_LIMIT)
    res['groundings'] = {entity: (dbn, dbi)}


def get_complex_one_side(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    res = get_statements(agents=[key], stmt_type='Complex', ev_limit=EV_LIMIT)
    res['groundings'] = {entity: (dbn, dbi)}
    return res


def get_to_target(entity, verb=None):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    if not verb or verb not in mod_map:
        res = get_statements(object=key, ev_limit=EV_LIMIT)
    else:
        stmt_type = mod_map[verb]
        res = get_statements(object=key, stmt_type=stmt_type,
                             ev_limit=EV_LIMIT)
    res['groundings'] = {entity: (dbn, dbi)}
    return res


def get_statements(**kwargs):
    # We first run the actual query and ask for a non-simple response
    res = indra_db_rest.get_statements(simple_response=False, **kwargs)
    # We get a dict of stmts keyed by stmt hashes
    hash_stmts_dict = res.get_hash_statements_dict()
    # From this we can get a dict of evidence totals fore ach stmt
    ev_totals = {int(stmt_hash): res.get_ev_count_by_hash(stmt_hash)
                 for stmt_hash, stmt in hash_stmts_dict.items()}
    source_counts = res.get_source_counts()
    # We now sort the statements by most to least evidence by looking at
    # the evidence totals
    sorted_stmts = [it[1] for it in
                    sorted(hash_stmts_dict.items(),
                           key=lambda x: ev_totals.get(int(x[0]), 0),
                           reverse=True)]
    return {'stmts': sorted_stmts, 'ev_totals': ev_totals,
            'source_counts': source_counts}


def makelambda_uni(fun, verb):
    return lambda a: fun(a, verb)


def makelambda_bin(fun, verb):
    return lambda a, b: fun(a, b, verb)
