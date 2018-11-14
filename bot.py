import re
import copy
import nltk
from fuzzywuzzy import fuzz
from indra.sources import indra_db_rest, trips
from indra.databases import hgnc_client
from indra.preassembler.grounding_mapper import gm


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
            return ret
            #return self.ask_clarification(matches)
        # If we have no matches, we try to find a similar question
        # and ask for clarification
        elif not matches:
            return {'question': self.find_fuzzy_clarify(question)}
        # Otherwise we respond with the first match
        else:
            ret = self.respond(*matches[0])
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


def get_grounding_from_name(name):
    # See if it's a gene name
    hgnc_id = hgnc_client.get_hgnc_id(name)
    if hgnc_id:
        return ('HGNC', hgnc_id)

    # Check if it's in the grounding map
    try:
        refs = gm[name]
        if isinstance(refs, dict):
            for dbn, dbi in refs.items():
                if dbn != 'TEXT':
                    return (dbn, dbi)
    # If not, search by text
    except KeyError:
        pass

    # If none of these, we try TRIPS
    try:
        print('Looking up %s with TRIPS' % name)   
        tp = trips.process_text(name, service_endpoint='drum-dev')
        terms = tp.tree.findall('TERM')
        if not terms:
            return ('TEXT', name)
        term_id = terms[0].attrib['id']
        agent = tp._get_agent_by_id(term_id, None)
        if 'HGNC' in agent.db_refs:
            return ('HGNC', agent.db_refs['HGNC'])
        if 'FPLX' in agent.db_refs:
            return ('FPLX', agent.db_refs['FPLX'])
    except Exception:
        return ('TEXT', name)
    return ('TEXT', name)


def get_neighborhood(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    stmts = indra_db_rest.get_statements(agents=[key], ev_limit=EV_LIMIT)
    return {'stmts': stmts, 'groundings': {entity: (dbn, dbi)}}


def get_activeforms(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    stmts = indra_db_rest.get_statements(agents=[key], stmt_type='ActiveForm',
                                         ev_limit=EV_LIMIT)
    return {'stmts': stmts, 'groundings': {entity: (dbn, dbi)}}


def get_phos_activeforms(entity):
    ret = get_activeforms(entity)
    ret_stmts = []
    for stmt in ret.get('stmts', []):
        for mc in stmt.agent.mods:
            if mc.mod_type == 'phosphorylation':
                ret_stmts.append(stmt)
    return {'stmts': ret_stmts, 'groundings': ret['groundings']}


def get_binary_directed(entity1, entity2, verb=None):
    dbn1, dbi1 = get_grounding_from_name(entity1)
    key1 = '%s@%s' % (dbi1, dbn1)
    dbn2, dbi2 = get_grounding_from_name(entity2)
    key2 = '%s@%s' % (dbi2, dbn2)
    if not verb or verb not in mod_map:
        stmts = indra_db_rest.get_statements(subject=key1,
                                             object=key2, ev_limit=EV_LIMIT)
    elif verb in mod_map:
        stmt_type = mod_map[verb]
        stmts = indra_db_rest.get_statements(subject=key1,
                                             object=key2,
                                             stmt_type=stmt_type,
                                             ev_limit=EV_LIMIT)
    return {'stmts': stmts, 'groundings': {entity1: (dbn1, dbi1),
                                           entity2: (dbn2, dbi2)}}


def get_binary_undirected(entity1, entity2):
    dbn1, dbi1 = get_grounding_from_name(entity1)
    key1 = '%s@%s' % (dbi1, dbn1)
    dbn2, dbi2 = get_grounding_from_name(entity2)
    key2 = '%s@%s' % (dbi2, dbn2)
    stmts = indra_db_rest.get_statements(agents=[key1, key2],
                                         ev_limit=EV_LIMIT)
    return {'stmts': stmts, 'groundings': {entity1: (dbn1, dbi1),
                                           entity2: (dbn2, dbi2)}}


def get_from_source(entity, verb=None):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    if not verb or verb not in mod_map:
        stmts = indra_db_rest.get_statements(subject=key, ev_limit=EV_LIMIT)
    else:
        stmt_type = mod_map[verb]
        stmts = indra_db_rest.get_statements(subject=key,
                                             stmt_type=stmt_type,
                                             ev_limit=EV_LIMIT)
    return {'stmts': stmts, 'groundings': {entity: (dbn, dbi)}}


def get_complex_one_side(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    stmts = indra_db_rest.get_statements(agents=[key], stmt_type='Complex',
                                         ev_limit=EV_LIMIT)
    return {'stmts': stmts, 'groundings': {entity: (dbn, dbi)}}


def get_to_target(entity, verb=None):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    if not verb or verb not in mod_map:
        stmts = indra_db_rest.get_statements(object=key, ev_limit=EV_LIMIT)
    else:
        stmt_type = mod_map[verb]
        stmts = indra_db_rest.get_statements(object=key,
                                             stmt_type=stmt_type,
                                             ev_limit=EV_LIMIT)
    return {'stmts': stmts, 'groundings': {entity: (dbn, dbi)}}


def makelambda_uni(fun, verb):
    return lambda a: fun(a, verb)


def makelambda_bin(fun, verb):
    return lambda a, b: fun(a, b, verb)
