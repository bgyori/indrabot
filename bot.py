import re
import copy
from fuzzywuzzy import fuzz
from indra.sources import indra_db_rest, trips
from indra.databases import hgnc_client
from indra.preassembler.grounding_mapper import gm


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

        t = (".*what do you know about ([^ ]+)", get_neighborhood)
        templates.append(t)

        t = (".*what does ([^ ]+) do", get_neighborhood)
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

        for verb in affect_verbs:
            t = ("does ([^ ]+) %s ([^ ]+)" % verb,
                 makelambda_bin(get_binary_directed, verb))
            templates.append(t)
            t = ("how does ([^ ]+) %s ([^ ]+)" % verb,
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

            t = ("what %ss ([^ ]+)" % verb,
                 makelambda_uni(get_to_target, verb))
            templates.append(t)

        t = ("what is the link between ([^ ]+) and ([^ ]+)",
             get_binary_directed)
        templates.append(t)


        return templates

    @staticmethod
    def sanitize(text):
        marks = ['.', ',', '?', '!', '-', ';', ':']
        for mark in marks:
            text = text.replace(mark, '')
        text = text[0].lower() + text[1:]
        text = text.strip()
        return text

    def handle_question(self, question):
        # First sanitize the string to prepare it for matching
        question = self.sanitize(question)
        matches = []
        for pattern, action  in self.templates:
            match = re.match(pattern, question)
            if match:
                args = list(match.groups())
                matches.append((action, args))
        print('matches', matches)

        if len(matches) > 1:
            return self.respond(*matches[0])
            #return self.ask_clarification(matches)
        elif not matches:
            return self.find_fuzzy_clarify(question)
        else:
            return self.respond(*matches[0])

    def respond(self, action, args):
        print('args', args)
        stmts = action(*args)
        return stmts

    def ask_clarification(self, matches):
        pass

    def find_fuzzy_clarify(self, question):
        ratios = [(t, fuzz.ratio(question, t)) for t in self.templates]
        ratios = sorted(ratios, key=lambda x: x[1], reverse=True)
        print('Your question is similar to "%s", is that what you meant?' %
              ratios[0][0])


mod_map = {'demethylate': 'Demethylation',
           'methylate': 'Methylation',
           'phosphorylate': 'Phosphorylation',
           'dephosphorylate': 'Dephosphorylation',
           'ubiquitinate': 'Ubiquitination',
           'deubiquitinate': 'Deubiquitination'}


affect_verbs = ['affect', 'regulate', 'control', 'target', 'phosphorylate'] + \
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
        tp = trips.process_text(name)
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
    stmts = indra_db_rest.get_statements(agents=[key])
    return stmts

def get_activeforms(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    stmts = indra_db_rest.get_statements(agents=[key], stmt_type='ActiveForm')
    return stmts

def get_phos_activeforms(entity):
    stmts = get_activeforms(entity)
    ret_stmts = []
    for stmt in stmts:
        for mc in stmt.agent.mods:
            if mc.mod_type == 'phosphorylation':
                ret_stmts.append(stmt)
    return ret_stmts

def get_binary_directed(entity1, entity2, verb=None):
    dbn, dbi = get_grounding_from_name(entity1)
    key1 = '%s@%s' % (dbi, dbn)
    dbn, dbi = get_grounding_from_name(entity2)
    key2 = '%s@%s' % (dbi, dbn)
    print(key1, key2)
    if not verb or verb not in mod_map:
        stmts = indra_db_rest.get_statements(subject=key1,
                                             object=key2)
    elif verb in mod_map:
        stmt_type = mod_map[verb]
        stmts = indra_db_rest.get_statements(subject=key1,
                                             object=key2,
                                             stmt_type=stmt_type)
    print(len(stmts))
    return stmts

def get_binary_undirected(entity1, entity2):
    dbn, dbi = get_grounding_from_name(entity1)
    key1 = '%s@%s' % (dbi, dbn)
    dbn, dbi = get_grounding_from_name(entity2)
    key2 = '%s@%s' % (dbi, dbn)
    print(key1, key2)
    stmts = indra_db_rest.get_statements(agents=[key1, key2])
    print(len(stmts))
    return stmts

def get_from_source(entity, verb=None):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    if not verb or verb not in mod_map:
        stmts = indra_db_rest.get_statements(subject=key)
    else:
        stmt_type = mod_map[verb]
        stmts = indra_db_rest.get_statements(subject=key,
                                             stmt_type=stmt_type)
    return stmts

def get_complex_one_side(entity):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    stmts = indra_db_rest.get_statements(agents=[key], stmt_type='Complex')
    return stmts

def get_to_target(entity, verb=None):
    dbn, dbi = get_grounding_from_name(entity)
    key = '%s@%s' % (dbi, dbn)
    if not verb or verb not in mod_map:
        stmts = indra_db_rest.get_statements(object=key)
    else:
        stmt_type = mod_map[verb]
        stmts = indra_db_rest.get_statements(object=key,
                                             stmt_type=stmt_type)

    return stmts


def makelambda_uni(fun, verb):
    return lambda a: fun(a, verb)

def makelambda_bin(fun, verb):
    return lambda a, b: fun(a, b, verb)
