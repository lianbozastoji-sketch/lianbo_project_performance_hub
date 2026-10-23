"""Tiny static check: report names that are loaded but never defined anywhere."""
import ast, builtins, sys

def check(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    defined = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
            for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs if hasattr(node, "args") else []:
                defined.add(a.arg)
            if hasattr(node, "args"):
                if node.args.vararg: defined.add(node.args.vararg.arg)
                if node.args.kwarg: defined.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            for a in node.args.args + node.args.kwonlyargs:
                defined.add(a.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            defined.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            defined.add(node.name)
    missing = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in defined:
            missing.setdefault(node.id, node.lineno)
    return missing

for p in sys.argv[1:]:
    m = check(p)
    print(p, "->", m if m else "OK")
