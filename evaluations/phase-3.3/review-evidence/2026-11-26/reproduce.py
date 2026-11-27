"""Reproduce historical audit counterexamples against the pinned public checkout."""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REVIEWED_COMMIT = 'a0b92acc02e1c5fbe94ffaa04159288fa72cea3a'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', required=True, type=Path,
                    help='clean checkout of the reviewed commit, not the fixed branch')
ROOT = parser.parse_args().repo.resolve()
try:
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                   text=True, stderr=subprocess.PIPE).strip()
    clean = subprocess.run(
        ['git', '-C', str(ROOT), 'diff', '--quiet', 'HEAD', '--',
         'evaluations/phase-3.2/harness', 'evaluations/phase-3.3/oracle',
         'evaluations/phase-3.3/live'], check=False).returncode == 0
except (OSError, subprocess.CalledProcessError) as exc:
    parser.error(f'cannot inspect repository: {exc}')
if head != REVIEWED_COMMIT or not clean:
    parser.error(f'requires {REVIEWED_COMMIT} with unchanged tracked harness/oracle/live files')
sys.path.insert(0, str(ROOT / 'evaluations/phase-3.3/oracle'))
sys.path.insert(0, str(ROOT / 'evaluations/phase-3.3/live'))
import validate_task as vt
import results_record as rr
import inspect_invocation as ii
import aqd_common as common

out = {}
with tempfile.TemporaryDirectory(prefix='aqd-review-') as tmp:
    pkg = Path(tmp) / 'pkg'
    shutil.copytree(ROOT / 'evaluations/phase-3.3/oracle/toy-package', pkg)
    def write(rel, text):
        p = pkg / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    allow = json.loads((pkg / 'allowlist.json').read_text())
    allow['tasks']['TOY-SPLIT']['files']['ledger/ready.py'] = 'mutable'
    write('allowlist.json', json.dumps(allow))
    write('tasks/TOY-SPLIT/project/ledger/ready.py', 'READY = 0\n')
    write('oracle/reference/ledger/ready.py', 'READY = 1\n')
    write('oracle/alternatives/loop-ceil/ledger/ready.py', 'READY = 1\n')
    testfile = 'oracle/hidden/hidden_tests/test_toy_split_hidden.py'
    write(testfile, (pkg / testfile).read_text() + '\n    def test_H05_ready(self):\n        from ledger.ready import READY\n        self.assertEqual(READY, 1)\n')
    sm = json.loads((pkg / 'oracle/source-map.json').read_text())
    sm['checks']['H05'] = {'obligation': 'READY must be 1.', 'sources': {v: {'kind': 'prompt', 'quote': 'READY must be 1.'} for v in ('S', 'D')}}
    write('oracle/source-map.json', json.dumps(sm))
    for variant in ('S', 'D'):
        p = f'prompts/{variant}.md'
        write(p, (pkg / p).read_text() + '\nREADY must be 1.\n')
    package = vt.Package(str(pkg))
    validator = vt.Validator(package, 20)
    try:
        survivor = next(files for label, files in vt.mechanical_mutants(package, 100) if label == 'ledger/split.py#const4')
        ref = str(pkg / 'oracle/reference')
        out['multi_file_mutation'] = {
            'full_reference': validator.score(ref),
            'unmutated_split_on_pristine': validator.score(files={'ledger/split.py': (pkg / 'oracle/reference/ledger/split.py').read_text()}),
            'current_mutation_path': validator.score(files=survivor),
            'correct_full_reference_overlay': validator.score(ref, files=survivor),
        }
    finally:
        validator.close()
    report = vt.validate(str(pkg), max_mutations=100, timeout=20)
    out['multi_file_validation'] = {k: report[k] for k in ('valid', 'reasons', 'mechanical_mutation')}

    cap = Path(tmp) / 'capture'
    (cap / 'driver').mkdir(parents=True)
    (cap / 'run-status.json').write_text(json.dumps({'valid': True, 'tokens': {'input': 1, 'cache_read': 2, 'cache_write': 3}, 'workspace_findings': {}}))
    (cap / 'export-checks.json').write_text(json.dumps({'group': 'treatment'}))
    rec = rr.record_run(str(cap), 'r-0000000000', 'TOY', 'treatment')
    out['missing_fields_record'] = {k: rec[k] for k in ('tokens', 'total_prompt_tokens', 'tokens_missing_reason', 'invoked', 'loaded')}
    events = [
        {'type':'system', 'subtype':'init'},
        {'type':'assistant', 'message':{'content':[{'type':'tool_use', 'id':'bash1', 'name':'Bash', 'input':{'command':"printf changed > source.py"}}]}},
        {'type':'assistant', 'message':{'content':[{'type':'tool_use', 'id':'skill1', 'name':'Skill', 'input':{'skill':'code-discipline'}}]}},
        {'type':'user', 'message':{'content':[{'type':'tool_result', 'tool_use_id':'skill1', 'content':'\n'.join(common.SKILL_SENTINELS)}]}},
        {'type':'assistant', 'message':{'content':[{'type':'tool_use', 'id':'edit1', 'name':'Edit', 'input':{}}]}},
    ]
    (cap / 'driver/transcript.ndjson').write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
    out['bash_before_load'] = ii.inspect_run(str(cap))

print(json.dumps(out, indent=2))
