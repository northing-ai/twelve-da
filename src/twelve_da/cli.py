"""JSON CLI. Exit: 0 complete, 2 failure/usage, 3 partial."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from . import ParseError
from .resolution import load_set, resolve, SuppliedDocument
from .model import clean


def is_source_output(source, target):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        return True
    try:
        return target.exists() and source.samefile(target)
    except FileNotFoundError:
        return False


def argument_parser():
    p = argparse.ArgumentParser(prog='twelve-da')
    sub = p.add_subparsers(dest='command',required=True)
    for name in ('inspect','list','get'):
        c = sub.add_parser(name)
        c.add_argument('source')
        c.add_argument('--companion', action='append', default=[], help='Explicit companion path (maximum 15)')
        if name=='get':
            c.add_argument('object_id')
            c.add_argument('--output',required=True)
    return p


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        sources = [args.source, *args.companion]
        if args.command=='get' and any(is_source_output(source, args.output) for source in sources):
            raise ParseError('output must not overwrite source')
        supplied, rejected = load_set([(str(Path(path).resolve()), 'content', path) for path in sources])
        supplied = [SuppliedDocument(s.file_id, s.document.source_sha256, s.document) for s in supplied]
        doc = supplied[0].document
        resolution = resolve(supplied, rejected=rejected)
        info = doc.inspect()
        info['resolution'] = resolution
        if args.command=='list':
            info['objects'] = [o.summary() for o in doc.objects]
        if args.command=='get':
            obj = doc.get(args.object_id)
            result = dict(document=info, object=obj.to_dict(), model_attributes=clean(doc.models.get(obj.model,[])))
            target = Path(args.output)
            # Exclusive temp file + replace gives atomic publication after full validation.
            fd, tmp = tempfile.mkstemp(prefix='.twelve-da-',dir=target.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:
                    json.dump(result,f,ensure_ascii=False,allow_nan=False)
                    f.write('\n')
                if any(is_source_output(source, target) for source in sources):
                    raise ParseError('output must not overwrite source')
                os.replace(tmp,target)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
            info['output'] = str(target)
        print(json.dumps(info,ensure_ascii=False,allow_nan=False))
        return 3 if doc.coverage=='partial' or rejected else 0
    except (ParseError,OSError,KeyError) as e:
        print(json.dumps({'error':str(e)}),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
