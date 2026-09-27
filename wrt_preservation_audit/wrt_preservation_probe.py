#!/usr/bin/env python3
"""Standalone WRT document preservation probe. Python stdlib only.

This is an exploratory diagnostic, not a claim that the WRT format promises
lossless OOXML round-trips. It deliberately reports failures without changing
upstream code. Native binary must be built independently on Linux/WSL.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def inspect_docx(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
        body = root.find(W+'body')
        paragraphs = []
        sequences = []
        for p in body.findall(W+'p'):
            txt=[]; seq=[]
            for run in p.findall(W+'r'):
                for el in run.iter():
                    if el.tag==W+'t':
                        v=el.text or ''; txt.append(v); seq.append(v)
                    elif el.tag==W+'drawing':
                        seq.append('[IMAGE]')
            paragraphs.append(''.join(txt)); sequences.append(seq)
        tables=[]; bold_table_cells=[]
        for table in body.findall(W+'tbl'):
            tab=[]
            for row in table.findall(W+'tr'):
                cells=[]
                for cell in row.findall(W+'tc'):
                    cells.append(''.join(el.text or '' for el in cell.iter(W+'t')))
                    for run in cell.iter(W+'r'):
                        if run.find(W+'rPr/'+W+'b') is not None:
                            bold_table_cells.append(''.join(el.text or '' for el in run.iter(W+'t')))
                tab.append(cells)
            tables.append(tab)
        media={n:{'sha256':hashlib.sha256(z.read(n)).hexdigest(),
                  'jpeg_bytes':z.read(n).startswith(b'\xff\xd8\xff'),
                  'suffix':Path(n).suffix.lower()}
               for n in z.namelist() if n.startswith('word/media/') and not n.endswith('/')}
        return {'paragraphs':paragraphs,'sequences':sequences,'tables':tables,
                'bold_table_cells':bold_table_cells,'media':media}

def test_one(binary, fixture, workspace):
    name=fixture.stem
    original=inspect_docx(fixture)
    wrt=workspace/(name+'.wrt'); out=workspace/(name+'.out.docx')
    p=subprocess.run([str(binary),'docx-to-wrt',str(fixture),str(wrt)],capture_output=True,text=True)
    if p.returncode: return {'case':name,'status':'ERROR','error':'docx-to-wrt: '+p.stderr[-500:]}
    before=wrt.read_text(encoding='utf-8')
    text=before
    if name=='targeted_edit':
        if text.count('Target: DRAFT')!=1:
            return {'case':name,'status':'ERROR','error':'Target string missing/ambiguous in WRT'}
        text=text.replace('Target: DRAFT','Target: FINAL',1)
        wrt.write_text(text,encoding='utf-8')
    p=subprocess.run([str(binary),'wrt-to-docx',str(wrt),str(out)],capture_output=True,text=True)
    if p.returncode: return {'case':name,'status':'ERROR','error':'wrt-to-docx: '+p.stderr[-500:]}
    actual=inspect_docx(out)
    checks={}
    detail={}
    if name=='text_mixed':
        checks['body_text'] = all(x in actual['paragraphs'] for x in original['paragraphs'])
        checks['body_bold'] = '[b]Bold[/b]' in before
        checks['body_italic'] = '[i]Italic[/i]' in before
        detail={'original':original['paragraphs'],'roundtrip':actual['paragraphs']}
    elif name in ('table_plain','table_formatted','table_pipe'):
        checks['table_cell_text_and_shape']=original['tables']==actual['tables']
        if name=='table_formatted':
            checks['bold_table_cell']=('BoldCell' in actual['bold_table_cells'])
        detail={'original_tables':original['tables'],'roundtrip_tables':actual['tables'],
                'original_bold_cells':original['bold_table_cells'],'roundtrip_bold_cells':actual['bold_table_cells']}
    elif name=='inline_png':
        beforepos=before.find('Before picture'); imgpos=before.find('[img '); afterpos=before.find('after picture')
        checks['inline_order_in_wrt']=beforepos>=0 and beforepos<imgpos<afterpos
        original_inline=next((v for v in original['sequences'] if '[IMAGE]' in v),[])
        actual_inline=next((v for v in actual['sequences'] if '[IMAGE]' in v),[])
        checks['inline_order_in_docx']=(''.join(actual_inline)==''.join(original_inline))
        checks['image_count']=len(original['media'])==len(actual['media'])
        detail={'original_inline':original_inline,'roundtrip_inline':actual_inline,'wrt_offsets':{'before':beforepos,'image':imgpos,'after':afterpos}}
    elif name=='jpeg_image':
        checks['jpeg_media_preserved']=len(actual['media'])==1 and all(v['jpeg_bytes'] and v['suffix'] in ('.jpg','.jpeg') for v in actual['media'].values())
        detail={'original_media':original['media'],'roundtrip_media':actual['media']}
    elif name=='targeted_edit':
        checks['target_updated']='Target: FINAL' in actual['paragraphs'] and 'Target: DRAFT' not in actual['paragraphs']
        checks['unrelated_paragraph_unchanged']='Untouched paragraph.' in actual['paragraphs']
        checks['unrelated_table_unchanged']=original['tables']==actual['tables']
        checks['unrelated_image_count']=len(original['media'])==len(actual['media'])
        orig_hashes=sorted(x['sha256'] for x in original['media'].values())
        output_hashes=sorted(x['sha256'] for x in actual['media'].values())
        checks['unrelated_image_bytes']=orig_hashes==output_hashes
        original_inline=next((v for v in original['sequences'] if '[IMAGE]' in v),[])
        actual_inline=next((v for v in actual['sequences'] if '[IMAGE]' in v),[])
        checks['unrelated_inline_image_position']=original_inline==actual_inline
        detail={'original_paragraphs':original['paragraphs'],'roundtrip_paragraphs':actual['paragraphs'],
                'original_tables':original['tables'],'roundtrip_tables':actual['tables'],
                'original_inline':original_inline,'roundtrip_inline':actual_inline}
    return {'case':name,'status':'CHECKED','checks':checks,'detail':detail,
            'wrt_preview':re.sub(r';base64,[A-Za-z0-9+/=]+',';base64,<omitted>',before)[:600]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,help='Path to compiled native wrt-engine')
    parser.add_argument('--fixtures',type=Path,default=Path(__file__).parent/'fixtures')
    parser.add_argument('--out',type=Path,default=Path('wrt_preservation_results.json'))
    parser.add_argument('--check-fixtures-only',action='store_true')
    args=parser.parse_args()
    fixtures=sorted(args.fixtures.glob('*.docx'))
    if not fixtures: parser.error('No DOCX fixtures found')
    if args.check_fixtures_only:
        for f in fixtures:
            info=inspect_docx(f)
            print(f.name,'paragraphs=',len(info['paragraphs']),'tables=',len(info['tables']),'images=',len(info['media']))
        print(f'PASS: {len(fixtures)} fixture files can be parsed structurally')
        return
    if not args.engine or not args.engine.is_file(): parser.error('Specify --engine /path/to/wrt-engine (Linux/WSL binary)')
    with TemporaryDirectory() as td:
        results=[test_one(args.engine,f,Path(td)) for f in fixtures]
    summary={'fixture_count':len(fixtures),'checks_passed':sum(x is True for r in results for x in r.get('checks',{}).values()),
             'checks_failed':sum(x is False for r in results for x in r.get('checks',{}).values()),
             'cases':results}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in results:
        statuses=' '.join(f'{k}={"PASS" if v else "FAIL"}' for k,v in r.get('checks',{}).items())
        print(f'{r["case"]}: {r["status"]} {statuses}')
    print('SUMMARY',f'{summary["checks_passed"]} pass / {summary["checks_failed"]} fail; output: {args.out}')
    print('NOTE: This is an exploratory diagnostic. Failures require interpretation against the format specification.')

if __name__=='__main__': main()
