import ast
import os
import zipfile

ROOT = os.path.dirname(__file__)
PREVIOUS_ZIP = os.environ.get("V48_ZIP", "/mnt/data/odoo-ai-rebuild-v48-full-runtime-e2e.zip")

def source_files(folder):
    return {
        os.path.relpath(os.path.join(dp, f), folder)
        for dp, _, fs in os.walk(folder) for f in fs
        if f not in {"__pycache__"} and not f.endswith(".pyc")
    }

def main():
    wizard = os.path.join(ROOT, "custom_addons", "ai_customer_plane", "wizard", "excel_role_import.py")
    review = os.path.join(ROOT, "custom_addons", "ai_customer_plane", "models", "access_review.py")
    scim = os.path.join(ROOT, "custom_addons", "ai_customer_plane", "controllers", "scim_api.py")
    for p in (wizard, review, scim):
        ast.parse(open(p, encoding="utf-8").read(), filename=p)
    assert "Import is blocked; no silent fallback." in open(wizard, encoding="utf-8").read()
    assert "savepoint()" in open(wizard, encoding="utf-8").read()
    assert "action_revoke_now()" in open(review, encoding="utf-8").read()
    assert 'Group.create' not in open(scim, encoding="utf-8").read()
    if os.path.exists(PREVIOUS_ZIP):
        with zipfile.ZipFile(PREVIOUS_ZIP) as z:
            previous = {n for n in z.namelist() if not n.endswith("/")}
        current = source_files(ROOT)
        # ZIP paths have the top-level root; normalize them.
        prev_rel = {n.split("/",1)[1] for n in previous if "/" in n}
        missing = sorted(prev_rel - current)
        assert not missing, "Deleted files: " + repr(missing)
    print("PASS v49 customer governance static checks")

if __name__ == "__main__":
    main()
