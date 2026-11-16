from pathlib import Path
import gzip
import hashlib
import importlib.metadata
import json
import re
import sys

root = Path(__file__).resolve().parents[2]
out = root / 'qa-report' / 'evidence'
npm = json.loads((root/'package-lock.json').read_text(encoding='utf-8-sig'))['packages']
index = root/'dist'/'index.html'
assets = [root/'dist'/x.removeprefix('./') for x in re.findall(r'(?:src|href)="(\./assets/[^"]+)"', index.read_text(encoding='utf-8-sig'))]
used = [
    {'path': str(p.relative_to(root)), 'bytes':p.stat().st_size, 'gzip_estimate':len(gzip.compress(p.read_bytes(),compresslevel=6))}
    for p in [index, *assets]
]
old = [{'path':str(p.relative_to(root)), 'bytes':p.stat().st_size} for p in sorted((root/'dist/assets').iterdir()) if p.is_file() and p not in assets]
def color(hexcode):
    def scale(v):
        x=int(v,16)/255
        return x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4
    return sum(x*scale(hexcode[i:i+2]) for x,i in zip((.2126,.7152,.0722),(0,2,4)))
def colors(s):
    return dict(re.findall(r'--([\w-]+):\s*#([0-9a-fA-F]{6})\s*;',s))
base=colors((root/'src/theme.css').read_text(encoding='utf-8-sig'))
css=(root/'src/palettes.css').read_text(encoding='utf-8-sig')
themed={'jade':base}
for match in re.finditer(r':root\[data-theme=["\']?([\w-]+)["\']?\][^{]*\{([^}]+)\}',css,re.S):
    themed[match.group(1)]={**base,**colors(match.group(2))}
contrast=[]
for theme, tokens in themed.items():
    for foreground, background in [('ink','page'),('ink','paper'),('muted','page'),('muted','paper'),('ink','selection'),('on-action','action'),('command-ink','command-paper')]:
        a,b=sorted([color(tokens[foreground]),color(tokens[background])])
        contrast.append({'theme':theme,'pair':foreground+'/'+background,'ratio':round((b+.05)/(a+.05),3)})
sources=[p for d in ('backend','src','dist') for p in (root/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
sources.extend(p for p in root.iterdir() if p.is_file())
data={'python':sys.version.split()[0], 'packages':sorted((dist.metadata['Name'],dist.version) for dist in importlib.metadata.distributions()),
      'npm_lock_entries':len(npm)-1,'npm_without_integrity':[k for k,v in npm.items() if k and not v.get('integrity')],
      'npm_install_scripts':[k for k,v in npm.items() if v.get('hasInstallScript')],
      'current_assets':used,'orphan_assets':old,'contrast':contrast,
      'project_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}}
(out/'offline-inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('bytes',sum(p['bytes'] for p in used),'gzip_estimate',sum(p['gzip_estimate'] for p in used),'orphans',len(old))
print('contrast pairs',len(contrast),'minimum',min(x['ratio'] for x in contrast))

