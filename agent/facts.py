"""Local verified facts with provenance and revocation."""

import json
from contextlib import closing

from . import core


def store_fact(con, key, value, source):
    con.execute("""INSERT INTO verified_facts(key,value,source,scope,verified_at,active)
                   VALUES (?, ?, ?, ?, ?, 1)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,source=excluded.source,
                   scope=excluded.scope,verified_at=excluded.verified_at,active=1""",
                (key, json.dumps(value), source, 'exact question' if key.startswith('question:') else 'candidate',
                 core.utc_now()))


def sync_config_facts(cfg):
    config_facts = dict(cfg['verified_answers'])
    config_facts.update({'question:' + key: value for key, value in cfg.get('verified_questions', {}).items()})
    with closing(core.connect()) as con, con:
        for key, value in config_facts.items():
            if value is None or value == '':
                continue
            con.execute("""INSERT OR IGNORE INTO verified_facts(key,value,source,scope,verified_at,active)
                           VALUES (?, ?, 'local config import', ?, ?, 1)""",
                        (key, json.dumps(value), 'exact question' if key.startswith('question:') else 'candidate',
                         core.utc_now()))


def effective_answers(cfg):
    sync_config_facts(cfg)
    cfg = {**cfg, 'verified_answers': dict(cfg['verified_answers']),
           'verified_questions': dict(cfg.get('verified_questions', {}))}
    with closing(core.connect()) as con:
        for row in con.execute('SELECT * FROM verified_facts'):
            key, value = row['key'], json.loads(row['value']) if row['active'] else None
            if key.startswith('question:'):
                question = key.removeprefix('question:')
                if value is None:
                    cfg['verified_questions'].pop(question, None)
                else:
                    cfg['verified_questions'][question] = value
            else:
                cfg['verified_answers'][key] = value
    if (cfg.get('_candidate_profile', {}).get('employment_evidence')
            and cfg['verified_answers'].get('has_employment_history') is False):
        cfg['verified_answers']['has_employment_history'] = None
    return cfg


def revoke_fact(con, key):
    return bool(con.execute('UPDATE verified_facts SET active=0 WHERE key=? AND active=1', (key,)).rowcount)
