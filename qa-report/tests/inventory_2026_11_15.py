from pathlib import Path
import gzip,json,re,sys,importlib.metadata
root=Path(__file__).resolve().parents[2]
out=root/'qa-report/evidence/qa-2026-11-15'
out.mkdir(exist_ok=True)
meta=json.loads((root/'package-lock.json').read_text(encoding='utf-8-sig'))['packages']
assets=sorted((root/'dist/assets').iterdir())
def colors(s):
    return dict(re.findall(r'--([\w-]+):\s*#([0-9a-fA-F]{6})\s*;',s))
def lum(hex):
    def scale(s):
        n=int(s,16)/255
        return n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4
    return sum(x*scale(hex[i:i+2]) for x,i in zip((.2126,.7152,.0722),(0,2,4)))
style=colors((root/'src/theme.css').read_text(encoding='utf-8'))
css=(root/'src/palettes.css').read_text(encoding='utf-8')
themes={'jade':style}
for match in re.finditer(r':root\[data-theme=["\']?([\w-]+)["\']?\][^{]*\{([^}]+)\}',css,re.S):
    themes[match[1]]={**style,**colors(match[2])}
pairs=[]
for theme, tokens in themes.items():
    for fg,bg in [('ink','page'),('ink','paper'),('muted','page'),('muted','paper'),('on-action','action'),('on-action','action-hover'),('ink','selection'),('command-ink','command-paper'),('coord-light','tile-light'),('coord-dark','tile-dark'),('coord-active','last-light'),('coord-active','last-dark'),('x-ink','x-surface'),('o-ink','o-surface'),('ink','hover')]:
        lo,hi=sorted([lum(tokens[fg]),lum(tokens[bg])])
        pairs.append(dict(theme=theme,bg=bg,fg=fg,ratio=round((hi+.05)/(lo+.05),3)))
data=dict(
    npm_entries=len(meta)-1,
    without_integrity=[k for k,v in meta.items() if k and not v.get('integrity')],
    install_scripts=[k for k,v in meta.items() if v.get('hasInstallScript')],
    python_version=sys.version.split()[0],
    python_packages=sorted((p.metadata['Name'],p.version) for p in importlib.metadata.distributions()),
    build=[{'path':str(p.relative_to(root)),'bytes':p.stat().st_size,'gzip_estimate':len(gzip.compress(p.read_bytes(),compresslevel=6))} for p in [root/'dist/index.html',*assets]],
    contrast=pairs,
)
(out/'inventory.json').write_text(json.dumps(data,indent=2),encoding='utf8')
print('npm entries:',data['npm_entries'],'contrast:',len(pairs),'min:',min(p['ratio'] for p in pairs))

