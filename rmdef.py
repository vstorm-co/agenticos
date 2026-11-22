import ast,sys
f=sys.argv[1]; names=set(sys.argv[2:])
src=open(f,encoding='utf-8').read(); lines=src.split('\n')
tree=ast.parse(src)
cuts=[]
def walk(body):
    for n in body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names:
            start=min([n.lineno]+[d.lineno for d in n.decorator_list])-1
            cuts.append((start,n.end_lineno))
        if isinstance(n,ast.ClassDef): walk(n.body)
walk(tree.body)
for s,e in sorted(cuts,reverse=True):
    # also strip following blank lines
    while e<len(lines) and lines[e].strip()=='' : e+=1
    del lines[s:e]
open(f,'w',encoding='utf-8',newline='\n').write('\n'.join(lines))
print(f,len(cuts),'removed')
