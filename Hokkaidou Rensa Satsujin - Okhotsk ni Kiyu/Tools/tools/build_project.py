#!/usr/bin/env python3
from __future__ import annotations
import argparse,subprocess,sys,tempfile
from pathlib import Path

def run(cmd):
    print('+',' '.join(str(x) for x in cmd),flush=True)
    subprocess.run(cmd,check=True)

def main():
    ap=argparse.ArgumentParser(description='One-command Okhotsk RU build: BPE -> QA -> font -> RU engine -> safe repack -> dictionaries.')
    ap.add_argument('rom',help='clean supported Japanese ROM')
    ap.add_argument('workfile',help='script_work.txt with TR blocks')
    ap.add_argument('-o','--out',required=True)
    ap.add_argument('--font',default=None,help='font .bin/.png; default assets/font_ru.bin')
    ap.add_argument('--ru-bpe',default=None,help='use an existing BPE TSV instead of rebuilding one')
    ap.add_argument('--shared-translations',default=None,help='JSON translations for original F2 shared streams')
    ap.add_argument('--bpe-pair-rules',type=int,default=79)
    ap.add_argument('--bpe-max-ngram',type=int,default=20)
    ap.add_argument('--extra-dict-max-bytes',type=int,default=384)
    ap.add_argument('--legacy-ru-dict',default=None,help='legacy v0.6 phrase dictionary mode (no D0..EF extension)')
    ap.add_argument('--skip-qa',action='store_true')
    ap.add_argument('--strict-qa',action='store_true')
    ap.add_argument('--no-known-padding',action='store_true')
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];py=sys.executable
    font=Path(args.font) if args.font else root/'assets/font_ru.bin'
    with tempfile.TemporaryDirectory(prefix='okhotsk_build_') as td:
        td=Path(td);temp_font=td/'fontpatched.nes';temp_lower=td/'lowerpatched.nes';temp_static=td/'staticuipatched.nes';temp_phone=td/'phonepatched.nes';temp_title=td/'titlecreditspatched.nes';temp_blackjack=td/'blackjackpatched.nes';temp_engine=td/'enginepatched.nes';temp_repacked=td/'repacked.nes'
        bpe=None
        if not args.legacy_ru_dict:
            if args.ru_bpe:bpe=Path(args.ru_bpe)
            else:
                bpe=td/'ru_bpe.tsv'
                cmd=[py,str(root/'tools/build_ru_bpe.py'),args.rom,args.workfile,'-o',str(bpe),'--pair-rules',str(args.bpe_pair_rules),'--max-ngram',str(args.bpe_max_ngram),'--extra-dict-max-bytes',str(args.extra_dict_max_bytes)]
                if args.shared_translations:cmd+=['--shared-translations',args.shared_translations]
                run(cmd)
        if not args.skip_qa:
            cmd=[py,str(root/'tools/check_script.py'),args.workfile]
            if bpe:cmd+=['--ru-bpe',str(bpe)]
            elif args.legacy_ru_dict:cmd+=['--ru-dict',args.legacy_ru_dict]
            if args.shared_translations:cmd+=['--shared-translations',args.shared_translations]
            if args.strict_qa:cmd.append('--strict')
            run(cmd)
            if args.shared_translations:
                run([py,str(root/'tools/check_dialogue_layout.py'),args.workfile,
                     '--shared-translations',args.shared_translations,'--max-x','30','--max-lines','3'])
            if args.shared_translations:
                run([py,str(root/'tools/check_dialogue_layout.py'),args.workfile,'--shared-translations',args.shared_translations])
        run([py,str(root/'tools/font_insert.py'),args.rom,str(font),'-o',str(temp_font)])
        run([py,str(root/'tools/patch_ru_direct_lowercase.py'),str(temp_font),'-o',str(temp_lower)])
        run([py,str(root/'tools/patch_static_ui_ru.py'),str(temp_lower),'-o',str(temp_static)])
        run([py,str(root/'tools/patch_phone_names_ru.py'),str(temp_static),'-o',str(temp_phone)])
        run([py,str(root/'tools/patch_title_credits_ru.py'),str(temp_phone),'-o',str(temp_title)])
        run([py,str(root/'tools/patch_blackjack_ru.py'),str(temp_title),'-o',str(temp_blackjack)])
        if bpe:
            run([py,str(root/'tools/patch_ru_extended_dictionary.py'),str(temp_blackjack),'-o',str(temp_engine)])
            cmd=[py,str(root/'tools/repack_pool.py'),str(temp_engine),args.workfile,'-o',str(temp_repacked),'--ru-bpe',str(bpe)]
            if args.shared_translations:cmd+=['--shared-translations',args.shared_translations]
            if not args.no_known_padding:cmd.append('--use-known-padding')
            run(cmd)
            # Dictionary DATA is patched last: the D0..EF table occupies a reserved\n            # old-text hole and must not be present while the original stream graph is scanned.
            run([py,str(root/'tools/patch_ru_dictionary.py'),str(temp_repacked),str(bpe),'-o',args.out])
        elif args.legacy_ru_dict:
            temp_dict=td/'dictpatched.nes'
            run([py,str(root/'tools/patch_ru_dictionary.py'),str(temp_blackjack),args.legacy_ru_dict,'-o',str(temp_dict)])
            run([py,str(root/'tools/repack_script.py'),str(temp_dict),args.workfile,'-o',args.out,'--ru-dict',args.legacy_ru_dict,'--use-dictionary-slack'])
        else:
            run([py,str(root/'tools/repack_script.py'),str(temp_blackjack),args.workfile,'-o',args.out])
    print('Build complete:',args.out)
if __name__=='__main__':main()
